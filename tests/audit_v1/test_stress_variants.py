"""Regression checks for declared synthetic challenges, not human identity approval."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from tmem_align.audit_v1.contracts import identity_channel
from tmem_align.audit_v1.stress_fixtures import CASE_IDS, stress_fixture


class StressVariantTests(unittest.TestCase):
    def test_seed_repeatability_and_noise_seed_change(self):
        a = stress_fixture("low_488_nonblank", seed=7)
        b = stress_fixture("low_488_nonblank", seed=7)
        c = stress_fixture("low_488_nonblank", seed=8)
        np.testing.assert_array_equal(a["cyx"], b["cyx"])
        self.assertFalse(np.array_equal(a["cyx"][2], c["cyx"][2]))
        np.testing.assert_array_equal(a["cyx"][1], c["cyx"][1])
        self.assertEqual(a["parameters"]["nominal_peak_signal_to_noise"], 3.0)
        self.assertGreater(float(np.std(a["cyx"][2])), 0)

    def test_561_cannot_change488_or_geometry(self):
        fixture = stress_fixture("two_somata_one_crop")
        changed = fixture["cyx"].copy()
        changed[1] = np.random.default_rng(3).uniform(0, 65535, changed[1].shape)
        np.testing.assert_array_equal(identity_channel(changed), identity_channel(fixture["cyx"]))
        for name in ["target_mask", "labels", "phenotype_roi"]:
            before = fixture[name].copy()
            identity_channel(changed)
            np.testing.assert_array_equal(fixture[name], before)

    def test_neighbor_and_two_soma_roi_truth(self):
        for case in ["neighboring_somata", "two_somata_one_crop"]:
            fixture = stress_fixture(case)
            contributors = set(np.unique(fixture["labels"][fixture["phenotype_roi"]])) - {0}
            self.assertEqual(contributors, {1, 2})
            self.assertTrue(fixture["expected_result"]["roi_has_multiple_contributors"])
            self.assertEqual(fixture["expected_result"]["expected_human_approval"], "NOT_ASSIGNED")

    def test_crowded_field_has_multiple_contributors(self):
        fixture = stress_fixture("crowded_field")
        self.assertEqual(set(np.unique(fixture["labels"])), {0, 1, 2, 3, 4, 5})
        self.assertGreaterEqual(len(fixture["expected_result"]["roi_contributor_labels"]), 3)

    def test_edge_support_fraction_uses_visible_pixels(self):
        fixture = stress_fixture("edge_of_FOV")
        expected = fixture["expected_result"]
        self.assertEqual(expected["target_full_support_area_px"], 441)
        self.assertEqual(expected["target_visible_support_area_px"], int(fixture["target_mask"].sum()))
        self.assertGreater(expected["target_visible_support_fraction"], 0.5)
        self.assertLess(expected["target_visible_support_fraction"], 1)
        self.assertTrue(np.any(fixture["target_mask"][0]))

    def test_punctate_and_diffuse_ground_truth(self):
        punctate = stress_fixture("puncta_rich")
        diffuse = stress_fixture("diffuse_cell")
        np.testing.assert_array_equal(punctate["cyx"][2], diffuse["cyx"][2])
        np.testing.assert_array_equal(punctate["phenotype_roi"], diffuse["phenotype_roi"])
        self.assertEqual(punctate["expected_result"]["puncta_truth_count"], 4)
        self.assertEqual(int(punctate["puncta_truth_mask"].sum()), 52)
        self.assertEqual(diffuse["expected_result"]["puncta_truth_count"], 0)
        self.assertEqual(int(diffuse["puncta_truth_mask"].sum()), 0)
        self.assertGreater(float(punctate["cyx"][1].max()), 5 * float(diffuse["cyx"][1].max()))

    def test_exposure_changes_measurement_not_geometry(self):
        fixture = stress_fixture("exposure_change")
        roi = fixture["phenotype_roi"]
        np.testing.assert_array_equal(fixture["cyx"][2], fixture["reference_cyx"][2])
        np.testing.assert_array_equal(fixture["cyx"][1], 2 * fixture["reference_cyx"][1])
        self.assertAlmostEqual(float(fixture["cyx"][1][roi].sum(dtype=np.float64)),
                               2 * float(fixture["reference_cyx"][1][roi].sum(dtype=np.float64)))
        self.assertIn("not exposure correction", fixture["expected_result"]["review_instruction"])

    def test_known_illumination_can_be_reversed_without_exposure_claim(self):
        fixture = stress_fixture("illumination_gradient")
        np.testing.assert_allclose(fixture["cyx"] / fixture["flatfield_cyx"],
                                   fixture["reference_cyx"], rtol=1e-6, atol=1e-5)
        self.assertFalse(fixture["parameters"]["independent_physical_calibration"])
        self.assertEqual(fixture["expected_result"]["production_detector_result"],
                         "NOT_COMPUTED_BY_FIXTURE_GENERATOR")

    def test_generator_is_small_explicit_and_no_overwrite(self):
        script = Path(__file__).resolve().parents[2] / "scripts" / "make_stress_examples.py"
        spec = importlib.util.spec_from_file_location("make_stress_examples_test", script)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "new"
            result = module.generate(output)
            self.assertEqual(len(result["cases"]), len(CASE_IDS))
            self.assertEqual(result["evidence_type"], "SYNTHETIC_NOT_EXPERIMENTAL")
            self.assertLess(sum(p.stat().st_size for p in output.rglob("*") if p.is_file()), 2 * 1024**2)
            for row in result["cases"]:
                for key in ["fixture", "preview", "parameters", "expected_result"]:
                    self.assertTrue((output / row[key]).is_file())
                expected = json.loads((output / row["expected_result"]).read_text())
                self.assertEqual(expected["expected_human_approval"], "NOT_ASSIGNED")
            with self.assertRaises(FileExistsError):
                module.generate(output)


if __name__ == "__main__":
    unittest.main()
