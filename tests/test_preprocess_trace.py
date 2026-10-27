"""Actual preprocessing contracts: known truth, trace parity, and invalid I/O.

These tests call production numerical functions. No replacement science backend
or import stub is used; missing microscopy dependencies are a test failure.
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

import numpy as np

from tmem_align import preprocess as p


class Recorder:
    def __init__(self):
        self.records = {}

    def capture(self, name, array=None, **metadata):
        if name in self.records:
            raise AssertionError("Duplicate stage name")
        self.records[name] = dict(array=None if array is None else array.copy(), **metadata)
        return self.records[name]


class PreprocessTraceTests(unittest.TestCase):
    def record(self, recorder, step, suffix="", prefix="preprocess"):
        return recorder.records[f"{prefix}_{step}{suffix}"]

    def test_known_flatfield_and_offset_recover_truth_without_mutating_inputs(self):
        field = np.tile(np.array([0.5, 1, 2, 4.]), (6, 1))
        raw = (1000 * field + 40).astype(np.uint16)
        raw_before, field_before = raw.copy(), field.copy()
        recorder = Recorder()
        expected = p.preprocess_image(raw, field, darkfield=40)
        actual = p.preprocess_image(raw, field, darkfield=40, trace=recorder)
        np.testing.assert_array_equal(actual, 1000)
        np.testing.assert_array_equal(actual, expected)
        np.testing.assert_array_equal(raw, raw_before)
        np.testing.assert_array_equal(field, field_before)
        np.testing.assert_array_equal(self.record(recorder, "00_before_ic")["array"], raw)
        np.testing.assert_array_equal(self.record(recorder, "01_dark_subtracted_float")["array"], raw.astype(float) - 40)
        np.testing.assert_array_equal(self.record(recorder, "02_ic_field")["array"], field)
        np.testing.assert_array_equal(self.record(recorder, "03_after_ic_float")["array"], 1000.)
        self.assertEqual(self.record(recorder, "03_after_ic_float")["array"].dtype, np.float64)

    def test_dark_subtraction_clamps_before_dividing(self):
        raw = np.array([[10, 110, 210]], dtype=np.uint16)
        recorder = Recorder()
        actual = p.preprocess_image(raw, np.full_like(raw, 2.), darkfield=20, trace=recorder)
        np.testing.assert_array_equal(actual, [[0, 45, 95]])
        np.testing.assert_array_equal(self.record(recorder, "01_dark_subtracted_float")["array"], [[0, 90, 190]])

    def test_round_clip_only_once_and_preserve_prequantized_pixels(self):
        raw = np.array([[1, 3, 65535]], dtype=np.uint16)
        recorder = Recorder()
        with patch.object(p, "_quantize", wraps=p._quantize) as quantize:
            actual = p.preprocess_image(raw, np.array([[2., 2., .5]]), trace=recorder)
        self.assertEqual(quantize.call_count, 1)
        np.testing.assert_array_equal(actual, [[0, 2, 65535]])
        np.testing.assert_array_equal(self.record(recorder, "03_after_ic_float")["array"], [[.5, 1.5, 131070.]])
        np.testing.assert_array_equal(self.record(recorder, "06_downstream_input")["array"], actual)

    def test_complete_noop_preserves_object_dtype_and_marks_missing_stages(self):
        raw = np.full((6, 7), .75, dtype=np.float32)
        recorder = Recorder()
        actual = p.preprocess_image(raw, trace=recorder)
        self.assertIs(actual, raw)
        self.assertEqual(actual.dtype, np.float32)
        for step in ["01_dark_subtracted_float", "02_ic_field", "03_after_ic_float",
                     "04_background_estimate", "05_after_background_float"]:
            record = self.record(recorder, step)
            self.assertEqual(record["status"], "skipped")
            self.assertIsNone(record["array"], "A missing operation cannot gain an invented intermediate")
        self.assertEqual(self.record(recorder, "06_downstream_input")["parameters"]["quantization"], "none (complete no-op)")

    def test_noop_without_trace_keeps_original_array_object(self):
        raw = np.arange(12, dtype=np.float32).reshape(3, 4)
        self.assertIs(p.preprocess_image(raw), raw)

    def test_background_executes_once_and_saved_removed_background_is_exact(self):
        yy, xx = np.mgrid[:16, :18]
        raw = (300 + 2 * yy + xx + 1200 * np.exp(-((yy-7)**2 + (xx-8)**2)/5)).astype(np.uint16)
        expected = p.preprocess_image(raw, np.full(raw.shape, 1.3), background_radius=3, darkfield=50)
        recorder = Recorder()
        with patch.object(p, "_background_float", wraps=p._background_float) as background:
            actual = p.preprocess_image(raw, np.full(raw.shape, 1.3), background_radius=3,
                                        darkfield=50, trace=recorder)
        self.assertEqual(background.call_count, 1)
        np.testing.assert_array_equal(actual, expected)
        before = self.record(recorder, "03_after_ic_float")["array"]
        after = self.record(recorder, "05_after_background_float")["array"]
        removed = self.record(recorder, "04_background_estimate")["array"]
        np.testing.assert_array_equal(removed, before - after)
        self.assertTrue(np.all(removed >= 0))

    def test_cyx_fields_do_not_mix_channels(self):
        raw = np.stack([np.full((5, 7), v, np.uint16) for v in [100, 600, 900]])
        field = np.stack([np.full((5, 7), v) for v in [2., 3., 1.5]])
        recorder = Recorder()
        actual = p.preprocess_image(raw, field, trace=recorder, trace_prefix="visit8")
        np.testing.assert_array_equal(actual[:, 0, 0], [50, 200, 600])
        for ci, channel in enumerate(["405", "561", "488"]):
            row = self.record(recorder, "06_downstream_input", f"_c{ci:02d}", "visit8")
            self.assertEqual(row["channel"], channel)
            self.assertEqual(row["axes"], "YX")
            self.assertEqual(row["details"]["channel_index"], ci)
            np.testing.assert_array_equal(row["array"], actual[ci])

    def test_tcyx_broadcasts_cyx_field_without_time_or_channel_mixing(self):
        raw = np.empty((2, 3, 5, 7), dtype=np.uint16)
        for ti in range(2):
            for ci in range(3):
                raw[ti, ci] = (ti + 1) * (ci + 1) * 100
        field = np.stack([np.full((5, 7), v) for v in [1., 2., 4.]])
        recorder = Recorder()
        actual = p.preprocess_image(raw, field, trace=recorder)
        np.testing.assert_array_equal(actual, p.preprocess_image(raw, field))
        self.assertEqual(len(recorder.records), 7 * 2 * 3)
        for ti in range(2):
            for ci in range(3):
                row = self.record(recorder, "06_downstream_input", f"_t{ti:03d}_c{ci:02d}")
                np.testing.assert_array_equal(row["array"], actual[ti, ci])
                self.assertEqual(row["details"]["time_index"], ti)
                self.assertEqual(row["details"]["source_axes"], "TCYX")

    def test_scalar_flatfield_is_an_explicit_constant_divisor(self):
        recorder = Recorder()
        raw = np.full((4, 5), 200, dtype=np.uint16)
        np.testing.assert_array_equal(p.preprocess_image(raw, 2., trace=recorder), 100)
        np.testing.assert_array_equal(self.record(recorder, "02_ic_field")["array"], 2.)

    def test_2d_input_does_not_invent_a_wavelength(self):
        recorder = Recorder()
        p.preprocess_image(np.ones((3, 5)), trace=recorder)
        self.assertEqual(self.record(recorder, "00_before_ic")["channel"], "unspecified")

    def test_generic_channel_count_retains_indices_instead_of_wavelength_guess(self):
        recorder = Recorder()
        p.preprocess_image(np.ones((2, 4, 5)), trace=recorder)
        self.assertEqual(self.record(recorder, "00_before_ic", "_c01")["channel"], "C1")

    def test_observer_cannot_mutate_quantitative_inputs_or_result(self):
        class MutatingObserver:
            def capture(self, name, array=None, **metadata):
                if array is not None:
                    array[...] = 0
        raw = np.full((4, 5), 200, dtype=np.uint16)
        field = np.full(raw.shape, 2.)
        actual = p.preprocess_image(raw, field, trace=MutatingObserver())
        np.testing.assert_array_equal(actual, 100)
        np.testing.assert_array_equal(raw, 200)
        np.testing.assert_array_equal(field, 2.)

    def test_nonpositive_or_nonfinite_flatfield_rejected_before_tracing(self):
        raw = np.ones((4, 5), dtype=np.uint16)
        for field in [0., -1., np.inf, np.nan, np.zeros(raw.shape), np.full(raw.shape, np.nan)]:
            with self.subTest(field=str(field)[:20]):
                recorder = Recorder()
                with self.assertRaisesRegex(ValueError, "flatfield"):
                    p.preprocess_image(raw, field, trace=recorder)
                self.assertEqual(recorder.records, {})

    def test_mismatched_or_ambiguous_field_axes_rejected(self):
        image = np.ones((3, 4, 5), dtype=np.uint16)
        for field in [np.ones((1, 5)), np.ones(5), np.ones((1, 4, 5)), np.ones((1, 3, 4, 5))]:
            with self.subTest(shape=field.shape), self.assertRaisesRegex(ValueError, "matching"):
                p.preprocess_image(image, field)
        with self.assertRaisesRegex(ValueError, "matching"):
            p.preprocess_image(image[0], np.ones_like(image))

    def test_nonfinite_or_mismatched_darkfield_rejected(self):
        raw = np.ones((3, 4, 5), dtype=np.uint16)
        for dark in [np.nan, np.inf, np.ones((1, 4, 5)), np.ones((4, 6))]:
            with self.subTest(dark=str(dark)[:20]), self.assertRaisesRegex(ValueError, "darkfield"):
                p.preprocess_image(raw, darkfield=dark)

    def test_invalid_image_axes_empty_or_nonfinite_pixels_rejected(self):
        for image in [np.ones(5), np.ones((1, 1, 1, 4, 5)), np.empty((0, 4)),
                      np.full((4, 5), np.nan), np.full((4, 5), 1j)]:
            with self.subTest(shape=image.shape), self.assertRaisesRegex(ValueError, "finite nonempty"):
                p.preprocess_image(image)

    def test_background_radius_requires_positive_integer_pixels(self):
        raw = np.ones((4, 5))
        for radius in [0, -2, True, 2.5, np.nan, "3"]:
            with self.subTest(radius=radius), self.assertRaisesRegex(ValueError, "positive integer"):
                p.preprocess_image(raw, background_radius=radius)

    def test_extreme_correction_overflow_is_rejected_before_quantization(self):
        with patch.object(p, "_quantize", wraps=p._quantize) as quantize:
            with self.assertRaisesRegex(ValueError, "overflow"):
                p.preprocess_image(np.full((3, 4), 1.e308), .1)
        quantize.assert_not_called()

    def test_trace_prefix_rejected_before_any_record_is_written(self):
        for prefix in ["../bad", "a/b", "", None]:
            recorder = Recorder()
            with self.subTest(prefix=prefix), self.assertRaisesRegex(ValueError, "trace_prefix"):
                p.preprocess_image(np.ones((3, 4)), trace=recorder, trace_prefix=prefix)
            self.assertEqual(recorder.records, {})


if __name__ == "__main__":
    unittest.main()
