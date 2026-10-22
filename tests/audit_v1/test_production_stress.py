"""Measured responses on constructed scenes, without requiring detector perfection."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import sys
from unittest.mock import patch


SOURCE = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("production_stress_tested", SOURCE / "scripts/exercise_stress_pipeline.py")
exercise = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(exercise)


class ProductionStressIntegration(unittest.TestCase):
    def test_multi_soma_scene_has_measured_production_response_without_automatic_acceptance(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "response"
            result = exercise.exercise_case("two_somata_one_crop", root)
            self.assertEqual(result["execution_status"], "executed_with_recorded_observations")
            self.assertEqual(result["production_detector_result"], "COMPUTED")
            self.assertTrue(result["secondary_soma_screen"]["known_prescribed_roi_multiple_contributors"])
            self.assertIn("single_soma_pass", result["secondary_soma_screen"])
            self.assertIn(result["adaptive_segmentation"]["execution"], ["computed", "handled_qc_rejection"])
            self.assertTrue(result["phenotype"]["intensity_partition_conserved"])
            self.assertTrue(result["alignment"]["changing561_preserves488_transform_and_pixels"])
            self.assertFalse(result["accepted_for_biological_analysis"])
            self.assertEqual(result["manual_review"], "NOT_PERFORMED")
            for filename in ["observations.json", "input_and_truth.npz", "segmentation_stages.npz",
                             "phenotype_stages.npz", "alignment.png", "segmentation.png", "phenotype.png"]:
                self.assertTrue((root / filename).is_file(), filename)

    def test_exposure_challenge_runs_real_measurement_and_preserves_identity_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = exercise.exercise_case("exposure_change", Path(tmp) / "response")
            self.assertAlmostEqual(result["phenotype"]["reference_to_challenged_total_ratio"], 2.0, places=6)
            self.assertTrue(result["quantitative_inputs_unchanged"])
            self.assertTrue(result["alignment"]["changing561_preserves488_transform_and_pixels"])
            self.assertEqual(result["phenotype"]["roi_source"],
                             "Prescribed 488-truth benchmark mask, independent of561 and adaptive output")


class ProductionStressOrchestration(unittest.TestCase):
    def test_cli_selects_the_named_case_for_independent_reruns(self):
        with patch.object(sys,'argv',['exercise_stress_pipeline.py','--out','new-output',
                '--case','low_488_nonblank']), patch.object(exercise,'generate',
                return_value={'cases_executed':1,'unexpected_software_errors':0}) as generate:
            self.assertEqual(exercise.main(),0)
        self.assertEqual(generate.call_args.kwargs['case_ids'],('low_488_nonblank',))

    def test_unexpected_exception_is_preserved_and_other_cases_are_still_exercised(self):
        def fake(case_id, out, **kwargs):
            if case_id == "low_488_nonblank":
                raise TypeError("unexpected API failure")
            out.mkdir()
            record = {"execution_status": "executed_with_recorded_observations", "findings": []}
            (out / "observations.json").write_text(json.dumps(record))
            return record
        with tempfile.TemporaryDirectory() as tmp, patch.object(exercise, "exercise_case", side_effect=fake) as mocked:
            out = Path(tmp) / "responses"
            report = exercise.generate(out, case_ids=["low_488_nonblank", "diffuse_cell"], backend=object())
            self.assertEqual(mocked.call_count, 2)
            self.assertEqual(report["unexpected_software_errors"], 1)
            self.assertFalse(report["execution_complete"])
            self.assertFalse(report["accepted_for_biological_analysis"])
            failed = json.loads((out / "low_488_nonblank/observations.json").read_text())
            self.assertEqual(failed["execution_status"], "unexpected_software_error")
            self.assertIn("TypeError", failed["error"])
            self.assertTrue((out / "low_488_nonblank/traceback.txt").is_file())
            self.assertTrue((out / "diffuse_cell/observations.json").is_file())
            self.assertTrue((out / "index.html").is_file())


if __name__ == "__main__":
    unittest.main()
