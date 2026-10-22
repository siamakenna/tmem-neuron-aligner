import json
from pathlib import Path
import tempfile
import shutil
import unittest

from tmem_align.audit_v1.parameters import build_resolved_parameters


ROOT = Path(__file__).resolve().parents[2]
PARAMETERS = dict(bbox_size=128, identity_consensus_fraction=.6, phenotype_dilation=2,
                  segmentation_min_area=180, min_core_area=80, max_core_area=2500,
                  background_exclusion=8, puncta_min_size=6)


class ResolvedParametersTests(unittest.TestCase):
    def test_documents_actual_used_values_and_source_constants_without_importing_renderer(self):
        result = build_resolved_parameters(ROOT, PARAMETERS)
        json.dumps(result, allow_nan=False)
        self.assertEqual(result['geometry']['phenotype_dilation_radius_px'], 2)
        self.assertEqual(result['phenotype']['dog_sigmas_px'], [1., 3.])
        self.assertEqual(result['phenotype']['mad_to_sigma_factor'], 1.4826)
        self.assertEqual(result['phenotype']['robust_sigma_multiplier'], 4.)
        self.assertEqual(result['phenotype']['roi_percentile_threshold'], 97.5)
        self.assertEqual(result['phenotype']['background_fallback_min_pixels'], 50)
        self.assertEqual(result['phenotype']['remove_small_objects_max_size_px'], 5)
        self.assertIsNone(result['phenotype']['upper_puncta_size_filter'])
        self.assertEqual(result['secondary_soma_screen']['search_radius'], 52.)
        self.assertEqual(result['secondary_soma_screen']['score_threshold'], .4)
        self.assertEqual(result['geometry']['minimum_valid_488_masks'], 3)

    def test_rejects_incomplete_fixture_parameters(self):
        with self.assertRaises(ValueError):
            build_resolved_parameters(ROOT, {'bbox_size': 128})

    def test_source_change_updates_recorded_constants_and_fingerprint(self):
        original = build_resolved_parameters(ROOT, PARAMETERS)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in original['source_files']:
                target = root/name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT/name, target)
            renderer = root/'scripts/render_curated_neuron_phenotypes.py'
            renderer.write_text(renderer.read_text().replace('robust_sigma = 1.4826 * mad',
                                                             'robust_sigma = 1.5 * mad'))
            changed = build_resolved_parameters(root, PARAMETERS)
            self.assertEqual(changed['phenotype']['mad_to_sigma_factor'], 1.5)
            self.assertNotEqual(original['source_files'], changed['source_files'])


if __name__ == '__main__':
    unittest.main()
