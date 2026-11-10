"""Contract and integration tests. All ND2 sources here are explicitly synthetic.

These tests cannot stand in for a real original-image pilot or biological QC.
"""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

import full_dataset as f
import project_adapter as a


class Lazy:
    def __init__(self, array):
        self.array = array
    def __getitem__(self, key):
        return Lazy(self.array[key])
    def compute(self):
        return self.array


class FakeND2:
    files = {}
    pixel_reads = 0
    def __init__(self, path):
        data = self.files[str(path)]
        self.sizes = data["sizes"]
        self.dtype = data.get("dtype", "uint16")
        self.is_rgb = data.get("is_rgb", False)
        self.array = data.get("array")
        self.metadata = SimpleNamespace(channels=[SimpleNamespace(channel=SimpleNamespace(name=n)) for n in data["channels"]])
        self.experiment = []
    def __enter__(self):
        return self
    def __exit__(self, *exc):
        return False
    def to_dask(self):
        type(self).pixel_reads += 1
        return Lazy(self.array)
    def asarray(self):
        raise AssertionError("Whole-file ND2 asarray is forbidden")


ND2 = SimpleNamespace(ND2File=FakeND2)


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        # macOS /var aliases /private/var. Match the inventory's canonical paths
        # before indexing FakeND2; real ND2 readers already resolve filesystem aliases.
        self.root = Path(self.tmp.name).resolve()
        self.raw = self.root / "originals"
        self.raw.mkdir()
        self.repo = self.root / "repo"
        (self.repo / "src").mkdir(parents=True)
        (self.repo / "src/science.py").write_text("# synthetic source fixture\n")
        self.evidence = self.root / "instrument_positions.json"
        self.evidence.write_text('{"fixture": "synthetic site correspondence"}\n')
        self.profile = {"name": "synthetic_test", "days": [8, 12], "channels": ["405", "561", "488"],
                        "identity_channel": "488", "luts": {c: [0, 1000] for c in ["405", "561", "488"]},
                        "processing": {"trace_arrays": False, "candidate_tracking": False}}
        FakeND2.files = {}
        FakeND2.pixel_reads = 0
        for w in ["E05", "F05"]:
            for day in [8, 12]:
                path = self.raw / f"Day{day}_Well{w}.nd2"
                path.write_bytes(f"synthetic-source-{w}-{day}".encode())
                names = ["DAPI 405", "RFP 561", "GFP 488"] if day == 8 else ["GFP 488", "DAPI 405", "RFP 561"]
                array = np.empty((2, 3, 10, 12), dtype=np.uint16)
                lookup = {"DAPI 405": 100, "RFP 561": 200, "GFP 488": 300}
                for p in range(2):
                    for ci, name in enumerate(names):
                        array[p, ci] = lookup[name] + p * 10
                FakeND2.files[str(path)] = {"sizes": {"P": 2, "C": 3, "Y": 10, "X": 12}, "channels": names, "array": array}
        self.inv = f.inventory(self.raw, self.root / "inventory", nd2_module=ND2)
        obs = []
        for h in self.inv["headers"]:
            for p in [0, 1]:
                obs.append({"path": h["path"], "well": h["well"], "day": h["day"], "site": f"S{p}",
                            "position": p, "time": 0, "z": 0,
                            "channel_map": {"405": "DAPI 405", "561": "RFP 561", "488": "GFP 488"},
                            "evidence": {"path": str(self.evidence), "reason": "Synthetic fixture only"}})
        self.mapping = {"observations": obs}
        self.manifest = f.make_plan(self.inv, self.mapping, self.profile, self.repo, self.root / "results")

    def processor(self, manifest, task, out):
        arrays = []
        for obs in task["observations"]:
            image, remap = a.read_selection(obs, self.profile["channels"], 10000, nd2_module=ND2)
            arrays.append(image)
        np.save(out / "canonical.npy", np.stack(arrays), allow_pickle=False)
        return {"days": self.profile["days"], "qc_failed_days": [12], "fixture_only": True}


class PlatformPathTests(unittest.TestCase):
    def test_fixture_through_symlinked_temp_parent_matches_canonical_reader_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory).resolve()
            real = base / "real"
            real.mkdir()
            alias = base / "alias"
            alias.symlink_to(real, target_is_directory=True)
            with patch.object(tempfile, "tempdir", str(alias)):
                fixture = Fixture(methodName="runTest")
                try:
                    fixture.setUp()
                    self.assertEqual(fixture.root, fixture.root.resolve())
                    self.assertFalse(fixture.inv["summary"]["header_errors"])
                    self.assertEqual(len(fixture.manifest["tasks"]), 4)
                finally:
                    fixture.doCleanups()


class InventoryTests(Fixture):
    def test_ambiguous_filename_identity_is_not_selected(self):
        self.assertEqual(f.parse_name("Day8_Day12_WellE05_WellF05.nd2")[:2], (None, None))

    def test_rgb_fails_header_contract(self):
        path = Path(self.inv["headers"][0]["path"])
        FakeND2.files[str(path)]["is_rgb"] = True
        self.assertIn("RGB", f.header(path, ND2)["error"])

    def test_hardlinked_original_is_reported(self):
        import os
        path = Path(self.inv["headers"][0]["path"])
        duplicate = self.raw / "Day8_WellG05.nd2"
        os.link(path, duplicate)
        FakeND2.files[str(duplicate)] = FakeND2.files[str(path)]
        inv = f.inventory(self.raw, self.root / "linked_inventory", nd2_module=ND2)
        self.assertEqual(len(inv["summary"]["duplicate_source_inodes"]), 1)

    def test_private_output_directory_is_owner_only(self):
        path = f.new_directory(self.root / "owner_only")
        self.assertEqual(path.stat().st_mode & 0o077, 0)

    def test_inventory_never_reads_pixels(self):
        self.assertEqual(FakeND2.pixel_reads, 0)
        self.assertEqual(len(self.inv["headers"]), 4)
        self.assertFalse(self.inv["summary"]["whole_well_coverage_verified"])
        self.assertFalse(self.inv["summary"]["file_counts_192x9_plus_192_BF"])

    def test_empty_inventory_fails(self):
        empty = self.root / "empty"; empty.mkdir()
        with self.assertRaisesRegex(ValueError, "No original ND2"):
            f.inventory(empty, self.root / "bad_inv", nd2_module=ND2)

    def test_source_output_overlap_fails(self):
        with self.assertRaisesRegex(ValueError, "disjoint"):
            f.inventory(self.raw, self.raw / "outputs", nd2_module=ND2)

    def test_linked_external_source_excluded_and_reported(self):
        (self.raw / "Day8_WellG05.nd2").symlink_to(self.evidence)
        paths, links = f.find_nd2(self.raw)
        self.assertEqual(len(paths), 4)
        self.assertEqual(len(links), 1)

    def test_bounded_inventory_stops(self):
        with self.assertRaisesRegex(ValueError, "exceeds"):
            f.find_nd2(self.raw, 2)

    def test_invalid_well_column_and_brightfield(self):
        self.assertEqual(f.parse_name("Day08_WellC99_BF.nd2"), (None, 8, "brightfield"))

    def test_entire_absent_expected_well_is_visible(self):
        inv = f.inventory(self.raw, self.root / "expected_inv", nd2_module=ND2, expected_wells=["G05"])
        self.assertEqual(len(inv["summary"]["missing_fluorescence"]), 9)

    def test_ambiguous_header_channels_are_not_assumed(self):
        path = Path(self.inv["headers"][0]["path"])
        FakeND2.files[str(path)]["channels"] = ["GFP", "GFP", "RFP"]
        self.assertIn("ambiguous", f.header(path, ND2)["error"])


class PlanTests(Fixture):
    def test_all_declared_sites_get_ordered_tasks(self):
        self.assertEqual(len(self.manifest["tasks"]), 4)
        self.assertEqual(self.manifest["mapped_positions"], 8)
        for task in self.manifest["tasks"]:
            self.assertEqual([o["day"] for o in task["observations"]], [8, 12])

    def test_cannot_skip_one_declared_site(self):
        mapping = {"observations": [o for o in self.mapping["observations"] if o["site"] == "S0"]}
        with self.assertRaisesRegex(ValueError, "unmapped"):
            f.make_plan(self.inv, mapping, self.profile, self.repo, self.root / "subset")

    def test_cannot_use_bare_P_index_as_authenticated_site(self):
        mapping = deepcopy(self.mapping)
        mapping["observations"][0]["site"] = None
        with self.assertRaisesRegex(ValueError, "Authenticated site"):
            f.make_plan(self.inv, mapping, self.profile, self.repo, self.root / "invalid")

    def test_requires_source_evidence(self):
        mapping = deepcopy(self.mapping)
        mapping["observations"][0]["evidence"] = None
        with self.assertRaisesRegex(ValueError, "acquisition evidence"):
            f.make_plan(self.inv, mapping, self.profile, self.repo, self.root / "invalid")

    def test_rejects_duplicate_acquisition_position(self):
        mapping = deepcopy(self.mapping)
        mapping["observations"].append(mapping["observations"][0])
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            f.make_plan(self.inv, mapping, self.profile, self.repo, self.root / "invalid")

    def test_channel_map_checked_on_each_visit(self):
        mapping = deepcopy(self.mapping)
        mapping["observations"][-1]["channel_map"]["488"] = "invented 488"
        with self.assertRaisesRegex(ValueError, "this file"):
            f.make_plan(self.inv, mapping, self.profile, self.repo, self.root / "invalid")

    def test_extra_channels_must_be_declared(self):
        inv = deepcopy(self.inv)
        inv["headers"][0]["sizes"]["C"] = 4
        inv["headers"][0]["channels"].append("extra detector")
        with self.assertRaisesRegex(ValueError, "every source channel"):
            f.make_plan(inv, self.mapping, self.profile, self.repo, self.root / "invalid")

    def test_multiple_z_planes_not_silently_dropped(self):
        inv = deepcopy(self.inv)
        inv["headers"][0]["sizes"]["Z"] = 3
        with self.assertRaisesRegex(ValueError, "T/Z>1"):
            f.make_plan(inv, self.mapping, self.profile, self.repo, self.root / "invalid")

    def test_no_invisible_parameter_or_threshold_override(self):
        profile = deepcopy(self.profile)
        profile["processing"]["min_post_correlation"] = 0
        with self.assertRaisesRegex(ValueError, "Unknown processing"):
            f.make_plan(self.inv, self.mapping, profile, self.repo, self.root / "invalid")

    def test_out_of_range_tuning_rejected(self):
        profile = deepcopy(self.profile)
        profile["processing"]["tracking"] = {"search_radius": 100000}
        with self.assertRaisesRegex(ValueError, "outside declared"):
            f.make_plan(self.inv, self.mapping, profile, self.repo, self.root / "invalid")

    def test_geometry_requires_all_sites_every_visit(self):
        geom = {"wells": {"E05": {"coordinate_model": "verified_integer_translation", "canvas_yx": [10, 24],
                "visits": {"8": [{"site": "S0", "offset_yx": [0, 0]}], "12": []},
                "evidence": {"path": str(self.evidence), "reason": "fixture"}}}}
        with self.assertRaisesRegex(ValueError, "every authentic"):
            f.make_well_plan(self.manifest, geom, self.root / "well")


class PixelExtractionTests(Fixture):
    def test_decoded_shape_must_match_declared_header(self):
        obs = self.manifest["tasks"][0]["observations"][0]
        FakeND2.files[obs["path"]]["array"] = np.zeros((2, 3, 9, 12), dtype=np.uint16)
        with self.assertRaisesRegex(ValueError, "Decoded pixels disagree"):
            a.read_selection(obs, self.profile["channels"], 10000, nd2_module=ND2)

    def test_channel_swap_restored_independently_per_visit(self):
        obs = self.manifest["tasks"][0]["observations"]
        one, _ = a.read_selection(obs[0], self.profile["channels"], 10000, nd2_module=ND2)
        two, mapping = a.read_selection(obs[1], self.profile["channels"], 10000, nd2_module=ND2)
        np.testing.assert_array_equal(one, two)
        self.assertEqual(mapping["canonical_to_source_indices"], [1, 2, 0])

    def test_all_positions_are_distinct(self):
        tasks = self.manifest["tasks"]
        images = [a.read_selection(t["observations"][0], self.profile["channels"], 10000, nd2_module=ND2)[0] for t in tasks[:2]]
        np.testing.assert_array_equal(images[1] - images[0], 10)

    def test_memory_limit_checked_before_decoding(self):
        with self.assertRaisesRegex(ValueError, "max_read_bytes"):
            a.read_selection(self.manifest["tasks"][0]["observations"][0], self.profile["channels"], 1, nd2_module=ND2)
        self.assertEqual(FakeND2.pixel_reads, 0)

    def test_changed_header_stops_before_decoding(self):
        obs = self.manifest["tasks"][0]["observations"][0]
        FakeND2.files[obs["path"]]["channels"] = ["new", "metadata", "order"]
        with self.assertRaisesRegex(ValueError, "header changed"):
            a.read_selection(obs, self.profile["channels"], 10000, nd2_module=ND2)
        self.assertEqual(FakeND2.pixel_reads, 0)

    def test_five_channel_assay_not_coerced_to_neuron_channels(self):
        obs = deepcopy(self.manifest["tasks"][0]["observations"][0])
        roles = ["DNA", "ER", "RNA", "AGP", "Mito"]
        names = ["RNA", "DNA", "Mito", "ER", "AGP"]
        FakeND2.files[obs["path"]] = {"sizes": {"P": 2, "C": 5, "Y": 10, "X": 12}, "channels": names,
            "array": np.stack([np.stack([np.full((10, 12), roles.index(c), dtype=np.uint16) for c in names])] * 2)}
        obs["header"] = f.header(Path(obs["path"]), ND2)
        obs["channel_map"] = {c: c for c in roles}
        array, _ = a.read_selection(obs, roles, 10000, nd2_module=ND2)
        self.assertEqual(array.shape, (5, 10, 12))
        np.testing.assert_array_equal(array[:, 0, 0], np.arange(5))


class DurableIntegrationTests(Fixture):
    def test_two_well_two_visit_two_site_durable_execution_and_aggregation(self):
        original_hashes = {p: f.digest(p) for p in FakeND2.files}
        for task in self.manifest["tasks"]:
            receipt = f.run_task(self.manifest, task["id"], processor=self.processor)
            self.assertEqual(receipt["accepted_identities"], 0)
        report = f.aggregate(self.manifest, hash_inputs=True)
        self.assertTrue(report["execution_complete"])
        self.assertEqual(report["completed"], 4)
        self.assertTrue(all(row["qc_failed_days"] == [12] for row in report["tasks"]))
        self.assertEqual(original_hashes, {p: f.digest(p) for p in FakeND2.files})

    def test_exact_source_resume_does_not_call_processor(self):
        task = self.manifest["tasks"][0]
        f.run_task(self.manifest, task["id"], processor=self.processor)
        def forbidden(*args):
            raise AssertionError("Completed task recomputed")
        self.assertTrue(f.run_task(self.manifest, task["id"], processor=forbidden)["resumed"])

    def test_input_mutation_never_reuses_completed_receipt(self):
        task = self.manifest["tasks"][0]
        f.run_task(self.manifest, task["id"], processor=self.processor)
        Path(task["observations"][0]["path"]).write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "size/mtime changed"):
            f.run_task(self.manifest, task["id"], processor=self.processor)

    def test_same_stat_different_pixels_detected_by_checksum(self):
        import os
        task = self.manifest["tasks"][0]
        f.run_task(self.manifest, task["id"], processor=self.processor)
        path = Path(task["observations"][0]["path"])
        old = path.stat()
        path.write_bytes(b"X" * old.st_size)
        os.utime(path, ns=(old.st_atime_ns, old.st_mtime_ns))
        with self.assertRaisesRegex(ValueError, "conflicts"):
            f.run_task(self.manifest, task["id"], processor=self.processor)

    def test_source_code_change_invalidates_run(self):
        (self.repo / "src/science.py").write_text("# changed science\n")
        with self.assertRaisesRegex(ValueError, "Source/environment changed"):
            f.run_task(self.manifest, self.manifest["tasks"][0]["id"], processor=self.processor)

    def test_evidence_change_invalidates_run(self):
        self.evidence.write_text("changed positions")
        with self.assertRaisesRegex(ValueError, "site evidence changed"):
            f.run_task(self.manifest, self.manifest["tasks"][0]["id"], processor=self.processor)

    def test_concurrent_claim_rejected(self):
        task = self.manifest["tasks"][0]
        lock = Path(self.manifest["out_root"]) / task["id"] / "ACTIVE.lock"
        lock.mkdir(parents=True)
        with self.assertRaises(FileExistsError):
            f.run_task(self.manifest, task["id"], processor=self.processor)

    def test_failure_retained_then_successful_retry(self):
        task = self.manifest["tasks"][0]
        def fails(manifest, task, out):
            (out / "partial.txt").write_text("real partial fixture output")
            raise ValueError("synthetic processing failure")
        with self.assertRaisesRegex(ValueError, "synthetic processing failure"):
            f.run_task(self.manifest, task["id"], processor=fails)
        root = Path(self.manifest["out_root"]) / task["id"]
        self.assertEqual(len(list(root.glob("attempts/*/FAILED.json"))), 1)
        self.assertFalse((root / "COMPLETED.json").exists())
        f.run_task(self.manifest, task["id"], processor=self.processor)
        self.assertEqual(len(list(root.glob("attempts/*/FAILED.json"))), 1)

    def test_corrupted_output_not_counted_complete(self):
        task = self.manifest["tasks"][0]
        f.run_task(self.manifest, task["id"], processor=self.processor)
        path = Path(self.manifest["out_root"]) / task["id"] / "artifacts/canonical.npy"
        path.write_bytes(b"corrupt")
        report = f.aggregate(self.manifest)
        self.assertEqual(report["completed"], 0)
        self.assertEqual(report["tasks"][0]["status"], "invalid")

    def test_unreceipted_extra_result_invalidates_completed_inventory(self):
        task = self.manifest["tasks"][0]
        f.run_task(self.manifest, task["id"], processor=self.processor)
        path = Path(self.manifest["out_root"]) / task["id"] / "artifacts/unbound.csv"
        path.write_text("unbound metric\n")
        self.assertEqual(f.aggregate(self.manifest)["tasks"][0]["status"], "invalid")

    def test_preflight_input_failure_gets_a_durable_failed_receipt(self):
        task = self.manifest["tasks"][0]
        Path(task["observations"][0]["path"]).write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "size/mtime changed"):
            f.run_task(self.manifest, task["id"], processor=self.processor)
        root = Path(self.manifest["out_root"]) / task["id"]
        self.assertEqual(len(list(root.glob("attempts/*/FAILED.json"))), 1)
        self.assertEqual(f.aggregate(self.manifest)["tasks"][0]["status"], "failed")

    def test_unexpected_receipt_not_hidden(self):
        p = Path(self.manifest["out_root"]) / "UNPLANNED" / "COMPLETED.json"
        f.atomic_json(p, {"unexpected": True})
        self.assertEqual(f.aggregate(self.manifest)["unexpected_task_receipts"], ["UNPLANNED"])

    def test_manifest_modification_detected(self):
        manifest = deepcopy(self.manifest)
        manifest["profile"]["luts"]["488"] = [0, 2000]
        with self.assertRaisesRegex(ValueError, "Manifest bytes changed"):
            f.run_task(manifest, manifest["tasks"][0]["id"], processor=self.processor)

    def test_swarm_not_generated_without_matching_real_pilot(self):
        path = self.root / "manifest.json"
        f.atomic_json(path, self.manifest)
        receipt = self.root / "not_a_real_pilot.json"
        f.atomic_json(receipt, {"passed": False})
        with self.assertRaisesRegex(ValueError, "pilot has not passed"):
            f.swarm_commands(path, receipt, self.root / "commands.swarm")


class GraphicsTests(Fixture):
    def test_registration_uses_frozen_plate_policy_without_threshold_changes(self):
        policy = {"ref_mode": "anchored", "anchor_corr_thresh": .1, "min_post_correlation": .07,
                  "plate_offsets": None, "max_sites": 1}
        result = a.resolve_registration_parameters({"name": "february_neuron"}, frozen=policy)
        self.assertEqual(result, {k: v for k, v in policy.items() if k != "max_sites"})
        self.assertEqual(a.resolve_registration_parameters({"name": "external_assay"}, frozen=policy), {})
    def test_registration_observer_preserves_science_arguments_and_returns(self):
        calls = []
        def registration(x, y, *, scale=1, trace=None, trace_prefix="default"):
            calls.append(scale)
            if trace is not None:
                trace.capture(trace_prefix + "_input", x, channel="488")
            return (x-y)*scale
        pilot = SimpleNamespace(register_translation=registration)
        observer = a.Observer(self.root / "stages", self.profile["channels"], self.profile["luts"], "488")
        x, y = np.ones((4, 5))*3, np.ones((4, 5))
        expected = registration(x, y, scale=2)
        with a.observe_registration(pilot, observer):
            actual = pilot.register_translation(x, y, scale=2)
        np.testing.assert_array_equal(actual, expected)
        self.assertEqual(calls, [2, 2])
        self.assertIs(pilot.register_translation, registration)
        self.assertEqual(observer.records[0]["id"], "actual_alignment_estimation_000_input")

    def test_registration_observer_accepts_none_details_from_production_hook(self):
        # register_translation emits details=None for raw inputs and masks.
        source = np.arange(20, dtype=np.uint16).reshape(4, 5)
        before = source.copy()
        observer = a.Observer(self.root / "stages", self.profile["channels"], self.profile["luts"], "488", arrays=True)
        observer.capture("registration_raw", source, channel="488", details=None)
        observer.capture("registration_mask", source > 5, channel="488", details=None)
        observer.finish()
        self.assertIsNone(observer.records[0]["details"])
        self.assertEqual(observer.records[0]["preview_lut"], self.profile["luts"]["488"])
        self.assertEqual(observer.records[1]["preview_lut"], [0, 1])
        np.testing.assert_array_equal(source, before)
        np.testing.assert_array_equal(np.load(self.root / "stages/registration_raw.npy"), before)

    def test_registration_without_hook_is_marked_unavailable_without_fabrication(self):
        pilot = SimpleNamespace(register_translation=lambda x, y: x-y)
        observer = a.Observer(self.root / "stages", self.profile["channels"], self.profile["luts"], "488")
        with a.observe_registration(pilot, observer):
            self.assertEqual(pilot.register_translation(5, 3), 2)
        self.assertEqual(observer.records[0]["status"], "unavailable")

    def test_actual_image_graphics_and_stage_arrays_are_bound_without_pixel_mutation(self):
        image = np.arange(120, dtype=np.uint16).reshape(10, 12)
        before = image.copy()
        observer = a.Observer(self.root / "stages", self.profile["channels"], self.profile["luts"], "488", arrays=True)
        observer.capture("before", image, channel="488", why="synthetic fixture")
        observer.capture("not_supplied", status="skipped", why="No calibration supplied")
        observer.finish()
        np.testing.assert_array_equal(image, before)
        np.testing.assert_array_equal(np.load(self.root / "stages/before.npy"), image)
        svg = (self.root / "stages/ACTUAL_IMAGE_FLOWCHART.svg").read_text()
        self.assertIn("data:image/png;base64,", svg)
        stages = f.load(self.root / "stages/STAGES.json")
        self.assertEqual(stages[1]["status"], "skipped")

    def test_compact_policy_declares_omitted_numeric_intermediates(self):
        observer = a.Observer(self.root / "stages", self.profile["channels"], self.profile["luts"], "488")
        observer.capture("plane", np.ones((10, 12)), channel="488")
        self.assertIsNone(observer.records[0]["numeric_array"])
        self.assertIn("compact", observer.records[0]["numeric_array_omission"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
