import importlib.util
from pathlib import Path
import tempfile
import unittest

import numpy as np


SCRIPT = Path(__file__).resolve().parents[2]/'scripts/verify_historical_ic_fixtures.py'
spec = importlib.util.spec_from_file_location('historical_ic_fixture_checker', SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class HistoricalICFixtureTests(unittest.TestCase):
    def write_fixture(self, path, *, bad_field=False, changed_output=False):
        raw = np.full((128, 128), 100, dtype=np.uint16)
        field = np.full(raw.shape, 1.25, dtype=np.float64)
        corrected = np.full(raw.shape, 80, dtype=np.uint16)
        if bad_field:
            field[0, 0] = 0
        if changed_output:
            corrected[2, 3] += 1
        np.savez_compressed(path, raw=raw, field_float64=field, corrected=corrected,
                            bounds_yxyx=np.array([100, 228, 300, 428]))

    def test_known_division_matches_without_fitting_crop(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'fixture.npz'
            self.write_fixture(path)
            result = module.verify_fixture(path)
            self.assertTrue(result['exact_match'])
            self.assertEqual(result['corrected_sum'], 80*128*128)

    def test_changed_stored_output_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'fixture.npz'
            self.write_fixture(path, changed_output=True)
            with self.assertRaises(AssertionError):
                module.verify_fixture(path)

    def test_nonpositive_field_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'fixture.npz'
            self.write_fixture(path, bad_field=True)
            with self.assertRaises(ValueError):
                module.verify_fixture(path)


if __name__ == '__main__':
    unittest.main()
