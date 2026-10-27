"""Production registration observability, transform direction and channel isolation."""
import tempfile
from pathlib import Path
import unittest

import numpy as np
from scipy.ndimage import shift as ndi_shift

from tmem_align.audit_v1.display import LUT
from tmem_align.audit_v1.stage_trace import StageTrace, verify_trace
from tmem_align.register import apply_shift, register_translation


class RegistrationTraceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        y, x = np.mgrid[:96, :96]
        soma = 1500 * np.exp(-((y - 42) ** 2 + (x - 45) ** 2) / 70)
        soma += 600 * np.exp(-((y - 68) ** 2 + (x - 24) ** 2) / 30)
        self.reference = np.stack([soma * .2, soma * .7, soma]).astype(np.float32)
        self.moving = np.stack([ndi_shift(plane, (4, -6), order=1, mode="constant")
                                for plane in self.reference])

    def trace(self):
        return StageTrace(self.root / "trace", metadata={"channels": ["405", "561", "488"]},
                          luts={"488": LUT(0, 2000, "488")})

    def test_trace_observes_exact_actual_output_and_known_direction(self):
        kwargs = dict(channel_index=2, robust_preprocess=False, mask_percentile=20,
                      max_shift_pixels=20)
        before = self.moving.copy()
        original, shift, error = register_translation(self.reference, self.moving, **kwargs)
        trace = self.trace()
        observed, actual_shift, actual_error = register_translation(
            self.reference, self.moving, trace=trace, **kwargs)
        np.testing.assert_array_equal(observed, original)
        np.testing.assert_array_equal(self.moving, before)
        np.testing.assert_allclose(actual_shift, (-4, 6), atol=1)
        self.assertEqual(shift, actual_shift)
        self.assertTrue(np.isnan(error) and np.isnan(actual_error))
        for channel in range(3):
            np.testing.assert_array_equal(observed[channel], apply_shift(self.moving[channel], *actual_shift))
        trace.finish({"transform_direction": "moving_to_reference", "accepted_ids": []})
        self.assertTrue(verify_trace(trace.root)["complete"])
        record = next(r for r in trace.records if r["stage"] == "registration_06_aligned")
        self.assertEqual(record["details"]["transform_applications_per_output_plane"], 1)
        numeric = trace.root / record["artifacts"]["numeric"]["path"]
        np.testing.assert_array_equal(np.load(numeric, allow_pickle=False), observed[2])

    def test_changed_561_cannot_change_identity_transform(self):
        changed_ref, changed_mov = self.reference.copy(), self.moving.copy()
        changed_ref[1] = np.random.default_rng(1).uniform(0, 60000, (96, 96))
        changed_mov[1] = np.random.default_rng(2).uniform(0, 60000, (96, 96))
        kwargs = dict(channel_index=2, robust_preprocess=False, mask_percentile=20)
        first, shift, _ = register_translation(self.reference, self.moving, **kwargs)
        second, other, _ = register_translation(changed_ref, changed_mov, **kwargs)
        self.assertEqual(shift, other)
        np.testing.assert_array_equal(first[2], second[2])

    def test_legacy_yx_result_equals_explicit_cyx_plane(self):
        one, shift, _ = register_translation(self.reference[2], self.moving[2], robust_preprocess=False)
        all_channels, other, _ = register_translation(self.reference, self.moving,
                                                      channel_index=2, robust_preprocess=False)
        self.assertEqual(shift, other)
        np.testing.assert_array_equal(one, all_channels[2])

    def test_rejected_displacement_preserves_failed_stage(self):
        trace = self.trace()
        with self.assertRaisesRegex(ValueError, "max_shift_pixels"):
            register_translation(self.reference, self.moving, channel_index=2,
                                 max_shift_pixels=1, trace=trace)
        self.assertEqual(trace.records[-1]["status"], "failed")
        trace.finish({"expected_diagnostic_rejection": True})
        verify_trace(trace.root)

    def test_invalid_inputs_and_parameters_are_rejected(self):
        invalid = [dict(channel_index=True), dict(channel_index=3), dict(mask_percentile=100),
                   dict(mask_percentile=float("nan")), dict(upsample_factor=False),
                   dict(upsample_factor=1.5), dict(max_shift_pixels=float("inf")),
                   dict(max_shift_pixels=-1)]
        for kwargs in invalid:
            with self.subTest(kwargs=kwargs), self.assertRaises((ValueError, TypeError)):
                register_translation(self.reference, self.moving, **kwargs)
        with self.assertRaises(ValueError):
            register_translation(self.reference, self.moving[:, :-1])
        bad = self.moving.copy()
        bad[2, 3, 4] = np.nan
        with self.assertRaises(ValueError):
            register_translation(self.reference, bad)


if __name__ == "__main__":
    unittest.main()
