"""Manual-review safety boundaries; no image segmentation or display assumptions."""
import copy
import csv
from pathlib import Path
import tempfile
import unittest

from tmem_align.audit_v1.review_gate import (
    CRITERIA, DAYS, EVIDENCE_FILES, SCHEMA_VERSION, evidence_manifest,
    evaluate_review, make_review_template,
)


def write_fixture(root, neuron_id="J05_N015"):
    folder = root / neuron_id
    folder.mkdir()
    for filename in EVIDENCE_FILES:
        (folder / filename).write_bytes(b"small deterministic evidence\n")
    for filename in ["metrics.csv", "fixture_tracks.csv"]:
        with (folder / filename).open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["neuron_id", "well", "day"])
            writer.writeheader()
            writer.writerows(dict(neuron_id=neuron_id, well=neuron_id[:3], day=day) for day in DAYS)
    return folder


def accepted_review(manifest):
    document = make_review_template(manifest)
    document["reviewer"] = "Example Scientist"
    document["reviewed_at"] = "2026-10-20T16:00:00+00:00"
    for track in document["tracks"]:
        track["track_decision"] = "accept"
        track["notes"] = "Inspected all nine visits using the stated channel-specific criteria."
        for visit in track["visits"]:
            visit.update({key: "pass" for key in CRITERIA})
    return document


class ManifestTests(unittest.TestCase):
    def test_hash_is_repeatable_and_independent_of_root_location(self):
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            a, b = Path(first), Path(second)
            write_fixture(a); write_fixture(b)
            x, y = evidence_manifest(a, ["J05_N015"]), evidence_manifest(b, ["J05_N015"])
            self.assertEqual(x, y)
            self.assertEqual(set(x[0]["files"]), set(EVIDENCE_FILES))
            self.assertEqual(x[0]["days"], list(DAYS))

    def test_every_required_evidence_file_is_bound(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); folder = write_fixture(root)
            original = evidence_manifest(root, ["J05_N015"])[0]["evidence_sha256"]
            for filename in ["small_fixture.npz", "parameters.json", "luts.json"]:
                with self.subTest(filename=filename):
                    original_bytes = (folder / filename).read_bytes()
                    (folder / filename).write_bytes(original_bytes + b"changed")
                    self.assertNotEqual(evidence_manifest(root, ["J05_N015"])[0]["evidence_sha256"], original)
                    (folder / filename).write_bytes(original_bytes)

    def test_missing_file_and_unsafe_id_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); folder = write_fixture(root)
            (folder / "small_fixture.npz").unlink()
            with self.assertRaises(ValueError): evidence_manifest(root, ["J05_N015"])
            with self.assertRaises(ValueError): evidence_manifest(root, ["../J05_N015"])

    def test_duplicate_neuron_id_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); write_fixture(root)
            with self.assertRaises(ValueError): evidence_manifest(root, ["J05_N015", "J05_N015"])

    def test_csv_row_from_another_neuron_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); folder = write_fixture(root)
            path = folder / "metrics.csv"
            path.write_text(path.read_text().replace("J05_N015", "N05_N011", 1))
            with self.assertRaises(ValueError): evidence_manifest(root, ["J05_N015"])

    def test_missing_or_reordered_metric_visit_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); folder = write_fixture(root)
            path = folder / "metrics.csv"; lines = path.read_text().splitlines()
            path.write_text("\n".join(lines[:-1]) + "\n")
            with self.assertRaises(ValueError): evidence_manifest(root, ["J05_N015"])
            path.write_text("\n".join([lines[0], *reversed(lines[1:])]) + "\n")
            with self.assertRaises(ValueError): evidence_manifest(root, ["J05_N015"])


class ReviewGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        write_fixture(self.root)
        self.manifest = evidence_manifest(self.root, ["J05_N015"])

    def result(self, document, exclusions=None):
        return evaluate_review(document, self.manifest, exclusions or {})

    def test_fully_reviewed_nine_visit_track_can_export(self):
        result = self.result(accepted_review(self.manifest))
        self.assertEqual(result["accepted_ids"], ["J05_N015"])
        self.assertEqual(result["tracks"][0]["reasons"], [])
        self.assertFalse(result["biological_inference_approved"])

    def test_template_and_missing_document_are_blocked(self):
        for document in [None, {}, make_review_template(self.manifest)]:
            with self.subTest(document=document):
                result = self.result(document)
                self.assertEqual(result["accepted_ids"], [])
                self.assertFalse(result["tracks"][0]["eligible"])

    def test_pending_track_cannot_pass_even_if_visit_checks_are_passes(self):
        document = accepted_review(self.manifest)
        document["tracks"][0]["track_decision"] = "not_reviewed"
        self.assertEqual(self.result(document)["accepted_ids"], [])

    def test_named_reviewer_and_timezone_timestamp_are_required(self):
        for name, value in [("reviewer", "  "), ("reviewed_at", ""),
                            ("reviewed_at", "2026-10-20T16:00:00"),
                            ("reviewed_at", "not-a-date")]:
            with self.subTest(name=name, value=value):
                document = accepted_review(self.manifest); document[name] = value
                self.assertEqual(self.result(document)["accepted_ids"], [])

    def test_missing_schema_cannot_be_used_for_approval(self):
        document = accepted_review(self.manifest); document.pop("schema_version")
        self.assertEqual(self.result(document)["accepted_ids"], [])

    def test_contaminated_roi_blocks_a_centered_identity_track(self):
        document = accepted_review(self.manifest)
        document["tracks"][0]["visits"][3]["roi_purity_488"] = "fail"
        result = self.result(document)
        self.assertEqual(result["accepted_ids"], [])
        self.assertIn("day_20_roi_purity_488_fail", result["tracks"][0]["reasons"])

    def test_known_f05_exclusion_cannot_be_overridden_by_accepted_form(self):
        write_fixture(self.root, "F05_N025")
        manifest = evidence_manifest(self.root, ["F05_N025"])
        document = accepted_review(manifest)
        document["known_exclusions"] = {}
        result = evaluate_review(document, manifest, {"F05_N025": "Known multi-neuron ROI"})
        self.assertEqual(result["accepted_ids"], [])
        self.assertIn("known_exclusion: Known multi-neuron ROI", result["tracks"][0]["reasons"])

    def test_stale_evidence_hash_blocks_review(self):
        document = accepted_review(self.manifest)
        document["tracks"][0]["evidence_sha256"] = "0" * 64
        self.assertEqual(self.result(document)["accepted_ids"], [])

    def test_evidence_changed_after_review_invalidates_acceptance(self):
        document = accepted_review(self.manifest)
        path = self.root / "J05_N015" / "small_fixture.npz"
        path.write_bytes(path.read_bytes() + b"changed after review")
        fresh = evidence_manifest(self.root, ["J05_N015"])
        self.assertEqual(evaluate_review(document, fresh, {})["accepted_ids"], [])

    def test_missing_visit_blocks_and_duplicate_visit_is_malformed(self):
        document = accepted_review(self.manifest)
        document["tracks"][0]["visits"].pop()
        result = self.result(document)
        self.assertEqual(result["accepted_ids"], [])
        self.assertIn("day_39_review_missing", result["tracks"][0]["reasons"])
        document = accepted_review(self.manifest)
        document["tracks"][0]["visits"].append(copy.deepcopy(document["tracks"][0]["visits"][0]))
        with self.assertRaises(ValueError): self.result(document)

    def test_missing_track_is_blocked_and_unknown_track_rejected(self):
        document = accepted_review(self.manifest)
        document["tracks"] = []
        self.assertEqual(self.result(document)["accepted_ids"], [])
        document = accepted_review(self.manifest)
        document["tracks"][0]["neuron_id"] = "N05_N011"
        with self.assertRaises(ValueError): self.result(document)

    def test_duplicate_track_and_invalid_criterion_are_malformed(self):
        document = accepted_review(self.manifest)
        document["tracks"].append(copy.deepcopy(document["tracks"][0]))
        with self.assertRaises(ValueError): self.result(document)
        document = accepted_review(self.manifest)
        document["tracks"][0]["visits"][0]["identity_488"] = "probably"
        with self.assertRaises(ValueError): self.result(document)

    def test_phenotype_failure_does_not_mutate_identity_decisions_or_geometry(self):
        document = accepted_review(self.manifest)
        document["tracks"][0]["visits"][0]["phenotype_qc_561"] = "fail"
        before_review, before_manifest = copy.deepcopy(document), copy.deepcopy(self.manifest)
        result = self.result(document)
        self.assertEqual(result["accepted_ids"], [])
        self.assertEqual(document, before_review)
        self.assertEqual(self.manifest, before_manifest)
        self.assertEqual(document["tracks"][0]["visits"][0]["identity_488"], "pass")

    def test_explicit_exclusion_is_not_reinterpreted_as_acceptance(self):
        document = accepted_review(self.manifest)
        document["tracks"][0]["track_decision"] = "exclude"
        self.assertEqual(self.result(document)["accepted_ids"], [])


if __name__ == "__main__":
    unittest.main()
