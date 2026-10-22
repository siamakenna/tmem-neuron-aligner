import unittest
import warnings

import numpy as np

from tmem_align.audit_v1.display import LUT, apply_lut_for_display, normalize_for_display
from tmem_align.audit_v1.display_policy import choose_lut, clipping_stats


class ExtremeDisplayLimits(unittest.TestCase):
    def test_extreme_finite_symmetric_limits_keep_midpoint(self):
        image = np.array([[-1e308, 0., 1e308]])
        with warnings.catch_warnings():
            warnings.simplefilter('error', RuntimeWarning)
            actual = normalize_for_display(image, LUT(-1e308, 1e308))
        np.testing.assert_array_equal(actual, [[0., .5, 1.]])

    def test_largest_finite_limits_and_out_of_range_values_are_safe(self):
        largest = np.finfo(np.float64).max
        image = np.array([[-largest, -1e308, 0., 1e308, largest]])
        before = image.copy()
        with warnings.catch_warnings():
            warnings.simplefilter('error', RuntimeWarning)
            actual = normalize_for_display(image, LUT(-1e308, 1e308))
        np.testing.assert_array_equal(actual, [[0., 0., .5, 1., 1.]])
        np.testing.assert_array_equal(image, before)

    def test_finite_span_with_extreme_outlier_does_not_overflow(self):
        image = np.array([[-1.7e308, -1e308, -.95e308, -.9e308, 1.7e308]])
        with warnings.catch_warnings():
            warnings.simplefilter('error', RuntimeWarning)
            actual = normalize_for_display(image, LUT(-1e308, -.9e308))
        np.testing.assert_allclose(actual, [[0, 0, .5, 1, 1]], atol=1e-15, rtol=0)

    def test_asymmetric_overflow_range_preserves_ratio(self):
        actual = normalize_for_display(np.array([[-1.6e308, 0., .8e308]]), LUT(-1.6e308, .8e308))
        np.testing.assert_allclose(actual, [[0, 2/3, 1]], atol=1e-15, rtol=0)

    def test_normal_microscopy_rgb_is_byte_identical_to_previous_formula(self):
        image = np.random.default_rng(8).integers(0, 65536, (31, 29), dtype=np.uint16)
        lut = LUT(81., 182., color='561')
        old = np.clip((image.astype(np.float64) - lut.low) / (lut.high - lut.low), 0, 1)
        expected = np.rint(old[..., None] * [1, 0, 1] * 255).astype(np.uint8)
        np.testing.assert_array_equal(apply_lut_for_display(image, lut), expected)

    def test_nonfinite_pixels_are_marked_and_negative_finite_pixel_clips(self):
        image = np.array([[-1., np.nan, np.inf, -np.inf, 5.]])
        before = image.copy()
        result = apply_lut_for_display(image, LUT(0, 10))
        np.testing.assert_array_equal(result[0, 0], [0, 0, 0])
        np.testing.assert_array_equal(result[0, 1:4], [[255,96,0]] * 3)
        np.testing.assert_array_equal(image, before)


class LongitudinalPolicy(unittest.TestCase):
    def test_reference_bbox_reproduces_nonflat_float32_reference_percentiles(self):
        stack = np.arange(3 * 7 * 9, dtype=np.uint16).reshape(3, 7, 9)
        lut = choose_lut(stack, color='488')
        old = stack.astype(np.float32)
        self.assertEqual(lut.low, float(np.percentile(old, 1)))
        self.assertEqual(lut.high, float(np.percentile(old, 99.6)))
        self.assertEqual(lut.scope, 'fixed-longitudinal-per-neuron')

    def test_roi_percentiles_pool_all_visits(self):
        stack = np.arange(3 * 2 * 3, dtype=np.uint16).reshape(3, 2, 3)
        roi = np.array([[True, False, False], [False, False, True]])
        lut = choose_lut(stack, roi, color='561', source='roi_fixed',
                         low_percentile=0, high_percentile=100)
        self.assertEqual((lut.low, lut.high), (0, 17))
        expected = np.percentile(stack[:, roi].astype(np.float64), [1, 99.6])
        default = choose_lut(stack, roi, color='561', source='roi_fixed')
        self.assertEqual((default.low, default.high), tuple(expected))

    def test_same_raw_value_has_same_display_across_visits(self):
        stack = np.array([[[100, 0], [0, 0]], [[0, 100], [1000, 1000]]], np.uint16)
        lut = choose_lut(stack, np.ones((2,2), bool), color='561', source='roi_fixed')
        a = apply_lut_for_display(stack[0], lut)
        b = apply_lut_for_display(stack[1], lut)
        np.testing.assert_array_equal(a[0,0], b[0,1])

    def test_roi_policy_does_not_change_stack_mask_crop_shape_or_sum(self):
        stack = np.arange(9 * 8 * 8, dtype=np.uint16).reshape(9, 8, 8)
        roi = np.zeros((8,8), bool); roi[2:6, 2:6] = True
        original, original_roi = stack.copy(), roi.copy()
        reference = choose_lut(stack, roi, color='561', source='reference_bbox')
        candidate = choose_lut(stack, roi, color='561', source='roi_fixed')
        self.assertNotEqual((reference.low, reference.high), (candidate.low, candidate.high))
        for frame in stack:
            a,b=clipping_stats(frame,roi,reference),clipping_stats(frame,roi,candidate)
            self.assertEqual(a['quantitative_sum'], b['quantitative_sum'])
            self.assertEqual(apply_lut_for_display(frame,reference).shape, (8,8,3))
            self.assertEqual(apply_lut_for_display(frame,candidate).shape, (8,8,3))
        np.testing.assert_array_equal(stack,original)
        np.testing.assert_array_equal(roi,original_roi)

    def test_other_channel_changes_cannot_change488_limits_or_pixels(self):
        boxes = np.arange(3*3*4*4, dtype=np.uint16).reshape(3,3,4,4)
        before = choose_lut(boxes[:,2], color='488')
        display = apply_lut_for_display(boxes[0,2],before)
        boxes[:,1] = 65535
        after = choose_lut(boxes[:,2], color='488')
        self.assertEqual(before,after)
        np.testing.assert_array_equal(display,apply_lut_for_display(boxes[0,2],after))

    def test_invalid_or_missing_roi_is_rejected(self):
        stack=np.ones((3,4,4),np.uint16)
        bad=[None,np.zeros((4,4),bool),np.ones((4,3),bool),np.ones((4,4),np.uint8)]
        for roi in bad:
            with self.subTest(roi=roi),self.assertRaises(ValueError):
                choose_lut(stack,roi,color='561',source='roi_fixed')

    def test_invalid_policy_percentiles_or_shape_is_rejected(self):
        stack=np.ones((3,4,4),np.uint16)
        for low,high in [(50,50),(99,1),(-1,99),(0,101),(0,np.inf)]:
            with self.subTest(low=low,high=high),self.assertRaises(ValueError):
                choose_lut(stack,color='488',low_percentile=low,high_percentile=high)
        with self.assertRaises(ValueError):choose_lut(stack,color='488',source='per_frame')
        with self.assertRaises(ValueError):choose_lut(stack[0],color='488')

    def test_flat_fallback_is_nonzero_and_all_nonfinite_is_rejected(self):
        for source in ['reference_bbox','roi_fixed']:
            lut=choose_lut(np.ones((3,4,4)),np.ones((4,4),bool),color='488',source=source)
            self.assertEqual((lut.low,lut.high),(1,2))
        with self.assertRaises(ValueError):choose_lut(np.full((3,4,4),np.nan),color='488')

    def test_float32_reference_overflow_is_explicit(self):
        with self.assertRaises(ValueError):choose_lut(np.full((3,4,4),1e100),color='488')


class ClippingStatistics(unittest.TestCase):
    def test_strict_counts_percentages_and_quantitative_sum(self):
        image=np.array([[0,10],[20,30]],np.uint16)
        roi=np.ones((2,2),bool)
        result=clipping_stats(image,roi,LUT(10,20))
        self.assertEqual(result['roi_pixels'],4)
        self.assertEqual((result['below_low'],result['above_high']),(1,1))
        self.assertEqual((result['below_low_percent'],result['above_high_percent']),(25,25))
        self.assertEqual(result['quantitative_sum'],60)

    def test_clipping_does_not_mutate_inputs_and_ignores_outside_roi(self):
        image=np.array([[np.nan,10],[20,30]])
        roi=np.array([[False,True],[True,True]])
        a,b=image.copy(),roi.copy()
        result=clipping_stats(image,roi,LUT(10,20))
        self.assertEqual(result['quantitative_sum'],60)
        self.assertEqual(result['above_high_fraction'],1/3)
        np.testing.assert_array_equal(image,a);np.testing.assert_array_equal(roi,b)

    def test_invalid_quantitative_roi_is_rejected(self):
        image=np.ones((4,4));roi=np.ones((4,4),bool)
        with self.assertRaises(ValueError):clipping_stats(image,np.zeros_like(roi),LUT(0,1))
        image[0,0]=np.nan
        with self.assertRaises(ValueError):clipping_stats(image,roi,LUT(0,1))


if __name__=='__main__':unittest.main()
