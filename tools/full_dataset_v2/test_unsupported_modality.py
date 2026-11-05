"""Synthetic modality contracts; actual production preprocessing/viewing calls."""
from copy import deepcopy
import csv
import gzip
from pathlib import Path
import sys
from unittest.mock import patch

import numpy as np

import full_dataset as f
import project_adapter as a
from test_full_dataset import Fixture, FakeND2, ND2


class UnsupportedModalityTests(Fixture):
    def setUp(self):
        super().setUp()
        for well in ["E05", "F05"]:
            path = self.raw / f"Day8_Well{well}_BF.nd2"
            path.write_bytes(("synthetic-brightfield-" + well).encode())
            array = np.arange(2 * 12 * 14, dtype=np.uint16).reshape(2, 12, 14)
            FakeND2.files[str(path)] = {"sizes": {"P": 2, "Y": 12, "X": 14}, "channels": ["Transmitted"], "array": array}
        self.all_inv = f.inventory(self.raw, self.root / "all_modalities", nd2_module=ND2)
        self.bf_profile = {"name": "synthetic_brightfield", "modality": "brightfield", "days": [8],
            "channels": ["BF"], "identity_channel": "BF", "luts": {"BF": [0, 1000]},
            "processing": {"downstream": "unsupported", "candidate_tracking": False, "trace_arrays": False, "array_storage": "npy.gz"}}
        observations = []
        for header in self.all_inv["headers"]:
            if header["modality"] != "brightfield":
                continue
            for position in range(header["declared_positions"]):
                observations.append({"path": header["path"], "well": header["well"], "day": header["day"],
                    "site": f"authentic_fixture_site_{position}", "position": position, "time": 0, "z": 0,
                    "channel_map": {"BF": "Transmitted"},
                    "evidence": {"path": str(self.evidence), "reason": "Synthetic acquisition correspondence fixture"}})
        self.bf_map = {"observations": observations}
        self.actual_repo = f.HERE.parents[1]

    def plan(self, profile=None, mapping=None, out=None, actual=False):
        return f.make_plan(self.all_inv, mapping or self.bf_map, profile or self.bf_profile,
            self.actual_repo if actual else self.repo, out or self.root / "bf_results")

    def test_separate_modality_plans_account_every_actual_position(self):
        bf = self.plan()
        fluorescence = f.make_plan(self.all_inv, self.mapping, self.profile, self.repo, self.root / "fluorescence")
        self.assertEqual(bf["declared_positions"], 4)
        self.assertEqual(fluorescence["declared_positions"], 8)
        self.assertEqual(bf["inventory_positions_by_modality"], {"fluorescence": 8, "brightfield": 4})
        self.assertEqual(bf["profile"]["days"], [8])
        self.assertTrue(bf["all_declared_positions_mapped"])
        self.assertFalse(bf["subset_requested"])
        self.assertTrue(all(t["scope"] == "extraction_only_series" for t in bf["tasks"]))

    def test_missing_brightfield_position_is_not_silently_omitted(self):
        mapping = deepcopy(self.bf_map)
        mapping["observations"].pop()
        with self.assertRaisesRegex(ValueError, "unmapped"):
            self.plan(mapping=mapping)

    def test_brightfield_channel_mapping_must_match_metadata(self):
        mapping = deepcopy(self.bf_map)
        mapping["observations"][0]["channel_map"] = {"BF": "assumed channel"}
        with self.assertRaisesRegex(ValueError, "own metadata"):
            self.plan(mapping=mapping)

    def test_brightfield_requires_explicit_unsupported_downstream(self):
        profile = deepcopy(self.bf_profile)
        del profile["processing"]["downstream"]
        with self.assertRaisesRegex(ValueError, "Brightfield downstream"):
            self.plan(profile=profile)

    def test_unsupported_mode_refuses_neuronal_tracking_request(self):
        profile = deepcopy(self.bf_profile)
        profile["processing"]["candidate_tracking"] = True
        with self.assertRaisesRegex(ValueError, "cannot request neuronal"):
            self.plan(profile=profile)

    def test_february_brightfield_requires_full_collection_even_if_subset_requested(self):
        profile = deepcopy(self.bf_profile)
        profile["name"] = "february_brightfield"
        with self.assertRaisesRegex(ValueError, "complete original collection"):
            self.plan(profile=profile)
        with self.assertRaisesRegex(ValueError, "complete original collection"):
            f.make_plan(self.all_inv, self.bf_map, profile, self.repo, self.root / "not_full", allow_subset=True)

    def test_february_fluorescence_still_requires_all_nine_visits_and_full_collection(self):
        profile = deepcopy(self.profile)
        profile["name"] = "february_neuron"
        with self.assertRaisesRegex(ValueError, "all nine visits"):
            f.make_plan(self.all_inv, self.mapping, profile, self.repo, self.root / "incomplete_fluorescence")

    def test_brightfield_count_flag_cannot_hide_missing_well_or_wrong_acquisition_day(self):
        profile = deepcopy(self.bf_profile)
        profile["name"] = "february_brightfield"
        for problem in ["missing_well", "wrong_day", "contradictory_roster"]:
            with self.subTest(problem=problem):
                inv = deepcopy(self.all_inv)
                inv["summary"]["file_counts_192x9_plus_192_BF"] = True
                if problem == "missing_well":
                    inv["headers"] = [r for r in inv["headers"] if not (r["modality"] == "brightfield" and r["well"] == "F05")]
                elif problem == "wrong_day":
                    next(r for r in inv["headers"] if r["modality"] == "brightfield")["day"] = 12
                else:
                    inv["summary"]["expected_wells"].append("G05")
                with self.assertRaisesRegex(ValueError, "roster/day mismatch"):
                    f.make_plan(inv, self.bf_map, profile, self.repo, self.root / problem)

    def test_site_table_uses_explicit_modality_and_actual_channel_labels(self):
        from prepare_site_map import prepare
        profile = deepcopy(self.bf_profile)
        profile["metadata_labels"] = {"BF": "Transmitted"}
        table = self.root / "synthetic_acquisition.csv"
        with table.open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=["path", "position", "site"])
            writer.writeheader()
            writer.writerows({k: r[k] for k in ["path", "position", "site"]} for r in self.bf_map["observations"])
        mapping = prepare(self.all_inv, profile, table, "Synthetic authentic site fixture")
        manifest = self.plan(profile=profile, mapping=mapping)
        self.assertEqual(manifest["mapped_positions"], 4)
        self.assertTrue(all(r["channel_map"] == {"BF": "Transmitted"} for r in mapping["observations"]))

    def test_actual_preprocess_preview_without_registration_or_neuron_models(self):
        self.bf_profile["processing"]["background_radius"] = 2
        manifest = self.plan(actual=True)
        pilot, tracker, preprocessing = a.attach_repo(self.actual_repo)
        with patch.dict(sys.modules, {"nd2": ND2}):
            task = manifest["tasks"][0]
            receipt = f.run_task(manifest, task["id"])
            self.assertTrue(f.run_task(manifest, task["id"])["resumed"])
        root = Path(manifest["out_root"]) / task["id"] / "artifacts"
        with gzip.open(root / "day08_raw.npy.gz", "rb") as stream:
            raw = np.load(stream, allow_pickle=False)
        with gzip.open(root / "day08_preprocessed.npy.gz", "rb") as stream:
            processed = np.load(stream, allow_pickle=False)
        np.testing.assert_array_equal(preprocessing.preprocess_image(raw, background_radius=2), processed)
        self.assertFalse(np.array_equal(raw, processed))
        self.assertEqual(raw.dtype, np.uint16)
        self.assertEqual(raw.shape, (1, 12, 14))
        self.assertIsNone(receipt["result"]["well_registration_qc_pass"])
        self.assertFalse(list(root.glob("*registered*")))
        self.assertFalse((root / "REGISTRATION_QC_PRIVATE.json").exists())
        self.assertEqual(receipt["result"]["days"], [8])
        for name in ["registration", "segmentation", "tracking"]:
            self.assertEqual(receipt["result"]["operation_status"][name]["status"], "unsupported")
        stages = f.load(root / "stages/STAGES.json")
        self.assertTrue(all(s.get("source_provenance") for s in stages))
        self.assertEqual(sum(s.get("display_only", False) for s in stages), 2)
        summary = f.aggregate(manifest, hash_inputs=True)
        completed = next(r for r in summary["tasks"] if r["status"] == "completed")
        self.assertEqual(completed["operation_status"]["tracking"]["status"], "unsupported")
        missing = next(r for r in summary["tasks"] if r["status"] == "missing")
        self.assertEqual(missing["operation_status"]["extraction"]["status"], "not_executed")
        self.assertEqual(missing["operation_status"]["tracking"]["status"], "unsupported")

    def test_single_visit_pilot_exception_preserves_exact_hash_and_swarm_gates(self):
        # This is an orchestration unit check using an inline synthetic executor;
        # it does not assert real parallel ND2 validation.
        manifest = self.plan(actual=True)
        manifest_path = self.root / "bf_manifest.json"
        f.atomic_json(manifest_path, manifest)
        def child(job):
            path, task_id = job
            f.run_task(f.load(path), task_id)
            return {"task": task_id, "returncode": 0}
        class InlinePool:
            def __init__(self, max_workers):
                if max_workers != 2:
                    raise AssertionError("Pilot worker cap changed")
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def map(self, function, jobs): return map(function, jobs)
        with patch.dict(sys.modules, {"nd2": ND2}), patch.object(f, "_child_run", side_effect=child), patch.object(f, "ProcessPoolExecutor", InlinePool):
            report = f.pilot(manifest_path, self.root / "bf_pilot", ["E05", "F05"])
        self.assertTrue(report["passed"])
        self.assertEqual(report["days"], [8])
        self.assertEqual(len(report["comparisons"]), 4)
        self.assertTrue(all(r["byte_equal_all_outputs_and_diagnostics"] and r["resume_noop"] for r in report["comparisons"]))
        with patch.dict(sys.modules, {"nd2": ND2}):
            result = f.swarm_commands(manifest_path, self.root / "bf_pilot/REAL_PILOT_REPORT_PRIVATE.json", self.root / "bf.swarm")
        self.assertEqual(result["commands"], 4)

    def test_single_visit_neuronal_pilot_remains_rejected(self):
        profile = deepcopy(self.profile)
        profile["days"] = [8]
        mapping = {"observations": [r for r in self.mapping["observations"] if r["day"] == 8]}
        manifest = f.make_plan(self.all_inv, mapping, profile, self.repo, self.root / "one_visit")
        path = self.root / "one_visit.json"
        f.atomic_json(path, manifest)
        with self.assertRaisesRegex(ValueError, "at least two real visits"):
            f.pilot(path, self.root / "rejected_pilot", ["E05", "F05"])
