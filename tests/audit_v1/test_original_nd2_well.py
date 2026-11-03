"""Strict ND2 manifest/selection guards; fixture bytes are NOT microscopy data."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("original_nd2_well", ROOT / "scripts/trace_original_nd2_well.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class OriginalND2Contracts(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=ROOT.parent)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        for name in ["original.nd2", "flat.npy", "dark.npy"]:
            (self.root / name).write_bytes(("CONTROL CONTRACT FIXTURE, NOT AN IMAGE: " + name).encode())
        for day in runner.DAYS:
            (self.root / f"original_day{day}.nd2").write_bytes(
                f"CONTROL CONTRACT FIXTURE, NOT AN IMAGE: visit {day}".encode())
        self.item = dict(path="original.nd2", sha256=runner.digest(self.root / "original.nd2"),
            time_index=0, z_index=0, max_project_z=False, source_channel_names=["405", "561", "488"],
            channel_indices=[0, 1, 2],
            tiles=[dict(position=0, tile_id="A", y_px=0, x_px=0)])
        ic = dict(coordinate_system="detector", channel_order=["405", "561", "488"],
            calibration_id="control fixture, no real calibration",
            provenance="control fixture, no acquisition evidence",
            flatfield_path="flat.npy", flatfield_sha256=runner.digest(self.root / "flat.npy"),
            darkfield_path="dark.npy", darkfield_sha256=runner.digest(self.root / "dark.npy"))
        self.plan = dict(schema_version="tmem.original_nd2_well.v1", well="E05",
            channel_mapping_evidence="contract fixture only", background_radius_px=None,
            geometry=dict(well="E05", geometry_id="control", orientation_validated=True,
                coordinate_evidence="contract fixture only", coordinate_convention="top-left YX",
                pixel_size_um=1.0, channel_order=["405", "561", "488"], canvas_yx=[4, 8], expected_tile_ids=["A"]),
            visits=[dict(day=day, ic=copy.deepcopy(ic), files=[copy.deepcopy(self.item)]) for day in runner.DAYS])
        for visit in self.plan["visits"]:
            name = f"original_day{visit['day']}.nd2"
            visit["files"][0].update(path=name, sha256=runner.digest(self.root / name))
        self.report = dict(sizes=dict(P=1, T=1, C=3, Y=4, X=4), is_rgb=False,
            channel_names=["405", "561", "488"], voxel_size=dict(x_um=1.0, y_um=1.0, z_um=1.0))

    def test_contract_resolves_original_sources_without_claiming_reader_execution(self):
        result = runner.validate_manifest(self.plan, self.root)
        self.assertEqual(len(result["visits"]), 9)
        self.assertEqual(len(result["input_sha256"]), 11)
        self.assertTrue(Path(result["visits"][0]["files"][0]["path"]).is_absolute())

    def test_each_of_nine_visits_is_required(self):
        self.plan["visits"].pop()
        with self.assertRaisesRegex(ValueError, "nine"):
            runner.validate_manifest(self.plan, self.root)

    def test_unreviewed_geometry_is_blocked(self):
        self.plan["geometry"]["orientation_validated"] = False
        with self.assertRaisesRegex(ValueError, "reviewed"):
            runner.validate_manifest(self.plan, self.root)

    def test_registered_tiff_cannot_substitute_for_original_nd2(self):
        image = self.root / "registered.tif"
        image.write_bytes(b"NOT ORIGINAL ND2")
        self.plan["visits"][0]["files"][0].update(path="registered.tif", sha256=runner.digest(image))
        with self.assertRaisesRegex(ValueError, "original regular .nd2"):
            runner.validate_manifest(self.plan, self.root)

    def test_source_checksum_change_is_blocked(self):
        (self.root / "original_day8.nd2").write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "SHA256"):
            runner.validate_manifest(self.plan, self.root)

    def test_missing_detector_field_is_not_faked_as_correction(self):
        (self.root / "flat.npy").unlink()
        with self.assertRaisesRegex(ValueError, "regular .npy"):
            runner.validate_manifest(self.plan, self.root)

    def test_stitched_coordinate_ic_is_rejected(self):
        self.plan["visits"][0]["ic"]["coordinate_system"] = "stitched_well"
        with self.assertRaisesRegex(ValueError, "detector coordinates"):
            runner.validate_manifest(self.plan, self.root)

    def test_correction_channel_order_cannot_silently_follow_source_reordering(self):
        self.plan["visits"][0]["ic"]["channel_order"] = ["488", "561", "405"]
        with self.assertRaisesRegex(ValueError, "IC channel_order"):
            runner.validate_manifest(self.plan, self.root)

    def test_duplicate_file_is_not_overwritten_or_treated_as_another_fov(self):
        self.plan["visits"][0]["files"].append(copy.deepcopy(self.plan["visits"][0]["files"][0]))
        with self.assertRaisesRegex(ValueError, "each ND2 file once"):
            runner.validate_manifest(self.plan, self.root)

    def test_identical_observation_cannot_be_relabelled_as_another_day(self):
        self.plan["visits"][1]["files"] = copy.deepcopy(self.plan["visits"][0]["files"])
        with self.assertRaisesRegex(ValueError, "same ND2 observation"):
            runner.validate_manifest(self.plan, self.root)

    def test_invalid_metadata_axis_count_is_rejected_before_decoding(self):
        self.report["sizes"]["P"] = 0
        with self.assertRaisesRegex(ValueError, "axis sizes"):
            runner.validate_nd2_metadata(self.item, self.report, self.plan["geometry"])

    def test_manifest_mutation_during_execution_invalidates_run(self):
        manifest = self.root / "manifest.json"
        manifest.write_text(json.dumps(self.plan))
        output = self.root / "changed_manifest"
        def mutate(plan, out):
            manifest.write_text(manifest.read_text() + "\n")
            return {"status": "executed"}
        with patch.object(runner, "execute", side_effect=mutate):
            result = runner.main(["--manifest", str(manifest), "--out", str(output)])
        self.assertEqual(result, 2)
        status = json.loads((output / "RUN_STATUS.json").read_text())
        self.assertIn("Manifest changed", status["error"])
        self.assertFalse(status["scientific_inference_ready"])

    def test_complete_expected_tile_roster_is_required(self):
        self.plan["geometry"]["expected_tile_ids"].append("missing")
        with self.assertRaisesRegex(ValueError, "cannot claim complete well"):
            runner.validate_manifest(self.plan, self.root)

    def test_declared_positions_are_not_implicitly_truncated_to_p_zero(self):
        self.report["sizes"]["P"] = 2
        with self.assertRaisesRegex(ValueError, "Every acquired ND2 position"):
            runner.validate_nd2_metadata(self.item, self.report, self.plan["geometry"])
        self.item["tiles"].append(dict(position=1, tile_id="B", y_px=0, x_px=4))
        runner.validate_nd2_metadata(self.item, self.report, self.plan["geometry"])

    def test_source_channel_identity_is_verified_against_declared_labels(self):
        self.report["channel_names"] = ["488", "561", "405"]
        with self.assertRaisesRegex(ValueError, "channel labels"):
            runner.validate_nd2_metadata(self.item, self.report, self.plan["geometry"])

    def test_source_channel_index_mapping_is_explicit_and_bijective(self):
        for indices in [None, [0, 0, 2], [0, 1], [0, 1, True], [1, 2, 3]]:
            with self.subTest(indices=indices):
                plan = copy.deepcopy(self.plan)
                plan["visits"][0]["files"][0]["channel_indices"] = indices
                with self.assertRaisesRegex(ValueError, "channel_indices"):
                    runner.validate_manifest(plan, self.root)

    def test_reordered_source_channels_keep_the_declared_project_mapping(self):
        for visit in self.plan["visits"]:
            visit["files"][0].update(source_channel_names=["488", "561", "405"], channel_indices=[2, 1, 0])
        plan = runner.validate_manifest(self.plan, self.root)
        self.assertEqual(plan["visits"][0]["files"][0]["channel_indices"], [2, 1, 0])

    def test_unknown_acquisition_axes_cannot_be_squeezed_away(self):
        self.report["sizes"]["S"] = 3
        with self.assertRaisesRegex(ValueError, "non-RGB ND2 axes"):
            runner.validate_nd2_metadata(self.item, self.report, self.plan["geometry"])

    def test_pixel_calibration_conflict_is_blocked(self):
        self.report["voxel_size"]["x_um"] = 2
        with self.assertRaisesRegex(ValueError, "calibration"):
            runner.validate_nd2_metadata(self.item, self.report, self.plan["geometry"])

    def test_multiz_requires_explicit_selection_or_projection(self):
        self.item["z_index"] = None
        self.plan["visits"][0]["files"][0] = self.item
        with self.assertRaisesRegex(ValueError, "Z index"):
            runner.validate_manifest(self.plan, self.root)
        self.item.update(max_project_z=True)
        self.report["sizes"]["Z"] = 3
        runner.validate_nd2_metadata(self.item, self.report, self.plan["geometry"])

    def test_template_is_intentionally_blocked_until_real_inputs_and_geometry_supplied(self):
        output = self.root / "template_check"
        code = runner.main(["--manifest", str(ROOT / "configs/original_nd2_well.template.json"),
                            "--out", str(output), "--validate-only"])
        self.assertEqual(code, 2)
        status = json.loads((output / "RUN_STATUS.json").read_text())
        self.assertEqual(status["status"], "blocked_or_failed")
        self.assertFalse(status["original_nd2_used"])

    def test_validate_only_never_executes_or_claims_real_nd2_pipeline(self):
        manifest = self.root / "manifest.json"
        manifest.write_text(json.dumps(self.plan))
        output = self.root / "contract_check"
        with patch.object(runner, "execute", side_effect=AssertionError("Pixel execution forbidden")) as execution:
            result = runner.main(["--manifest", str(manifest), "--out", str(output), "--validate-only"])
        self.assertEqual(result, 0)
        execution.assert_not_called()
        status = json.loads((output / "RUN_STATUS.json").read_text())
        self.assertFalse(status["original_nd2_used"])
        self.assertEqual(status["nd2_metadata_reader_status"], "not_executed")

    def test_dependency_failure_is_blocked_and_does_not_become_scientific_success(self):
        manifest = self.root / "manifest.json"
        manifest.write_text(json.dumps(self.plan))
        output = self.root / "missing_dependency"
        with patch.object(runner, "execute", side_effect=ImportError("CONTROL missing ND2 reader")):
            result = runner.main(["--manifest", str(manifest), "--out", str(output)])
        self.assertEqual(result, 2)
        status = json.loads((output / "RUN_STATUS.json").read_text())
        self.assertFalse(status["scientific_inference_ready"])
        self.assertEqual(status["real_accepted_ids"], [])


if __name__ == "__main__":
    unittest.main()
