"""Display proposals never modify scientific pixels, masks or geometry."""
import json
import unittest

import numpy as np

from tmem_align.audit_v1.contracts import Bounds
from tmem_align.audit_v1.display import LUT, apply_lut_for_display
from tmem_align.audit_v1.visualization import propose_lut_bbox, render_preview


class PreviewTests(unittest.TestCase):
    def setUp(self):
        self.image = np.arange(48, dtype=np.uint16).reshape(6, 8)
        self.lut = LUT(5, 30, "488")

    def test_preview_uses_existing_lut_and_spatial_crop(self):
        bounds = Bounds(1, 5, 2, 7)
        output = render_preview(self.image, self.lut, bounds=bounds)
        np.testing.assert_array_equal(output,
            apply_lut_for_display(bounds.crop(self.image), self.lut))
        self.assertFalse(output.flags.writeable)
        self.assertFalse(np.shares_memory(output, self.image))

    def test_overlay_is_registered_to_full_image_without_mutating_sources(self):
        mask = np.zeros(self.image.shape, bool)
        mask[2:4, 3:6] = True
        original, original_mask = self.image.copy(), mask.copy()
        output = render_preview(self.image, self.lut, bounds=Bounds(1, 5, 2, 7),
            overlays=[dict(mask=mask, color=(255, 0, 0), outline=False)])
        np.testing.assert_array_equal(output[1:3, 1:4],
            np.broadcast_to([255, 0, 0], (2, 3, 3)))
        np.testing.assert_array_equal(self.image, original)
        np.testing.assert_array_equal(mask, original_mask)

    def test_outline_does_not_create_an_edge_at_crop_boundary(self):
        mask = np.ones(self.image.shape, bool)
        output = render_preview(self.image, self.lut, bounds=Bounds(2, 4, 2, 6),
            overlays=[dict(mask=mask, color=(255, 0, 0))])
        np.testing.assert_array_equal(output,
            apply_lut_for_display(self.image[2:4, 2:6], self.lut))

    def test_invalid_display_pixels_keep_visible_marker(self):
        image = self.image.astype(float)
        image[2, 3] = np.nan
        output = render_preview(image, self.lut)
        np.testing.assert_array_equal(output[2, 3], [255, 96, 0])
        self.assertTrue(np.isnan(image[2, 3]))

    def test_bad_overlay_and_bounds_are_rejected(self):
        for overlay in [dict(mask=np.ones((2, 2), bool)),
                        dict(mask=np.ones(self.image.shape)),
                        dict(mask=np.ones(self.image.shape, bool), alpha=np.nan),
                        dict(mask=np.ones(self.image.shape, bool), alpha=True),
                        dict(mask=np.ones(self.image.shape, bool), color=(256, 0, 0)),
                        dict(mask=np.ones(self.image.shape, bool), color=(1., 2., 3.)),
                        dict(mask=np.ones(self.image.shape, bool), outline="yes"),
                        dict(mask=np.ones(self.image.shape, bool), typo=1)]:
            with self.subTest(overlay=overlay), self.assertRaises(ValueError):
                render_preview(self.image, self.lut, overlays=[overlay])
        for bounds in [Bounds(-1, 3, 0, 3), Bounds(True, 3, 0, 3), (0, 3, 0, 3)]:
            with self.subTest(bounds=bounds), self.assertRaises(ValueError):
                render_preview(self.image, self.lut, bounds=bounds)


class LutBoxProposalTests(unittest.TestCase):
    def setUp(self):
        self.image = np.zeros((12, 16), dtype=np.uint16)
        self.image[2:5, 3:7] = 100
        self.image[7:9, 10:13] = 200
        self.lut = LUT(50, 150, "488")

    def test_default_preserves_clipped_high_signal_and_never_adopts_box(self):
        result = propose_lut_bbox(self.image, self.lut, anchor_yx=(7.5, 11.5))
        self.assertEqual(result["bounds"], dict(y0=7, y1=9, x0=10, x1=13))
        self.assertEqual(result["mask_count"], 6)
        self.assertEqual(result["above_high_pixels_in_search"], 6)
        self.assertEqual(result["above_high_pixels_excluded_from_support"], 0)
        self.assertTrue(result["display_only"])
        self.assertFalse(result["adopted"])
        self.assertFalse(result["measurement_geometry_changed"])
        self.assertFalse(result["review_approval_granted"])
        json.dumps(result, allow_nan=False)

    def test_upper_display_limit_changes_rgb_without_changing_visible_box(self):
        first = propose_lut_bbox(self.image, self.lut, anchor_yx=(7, 11))
        second = propose_lut_bbox(self.image, LUT(50, 500, "488"), anchor_yx=(7, 11))
        self.assertEqual(first["bounds"], second["bounds"])
        self.assertEqual(first["mask_count"], second["mask_count"])
        self.assertFalse(np.array_equal(render_preview(self.image, self.lut),
                                       render_preview(self.image, LUT(50, 500, "488"))))

    def test_explicit_range_exclusion_is_reported_and_does_not_jump_anchor(self):
        result = propose_lut_bbox(self.image, self.lut, anchor_yx=(7, 11),
                                  range_policy="within_range")
        self.assertEqual(result["status"], "anchor_not_in_lut_support")
        self.assertIsNone(result["bounds"])
        self.assertEqual(result["above_high_pixels_excluded_from_support"], 6)
        self.assertEqual(result["support_rule"], "low < pixel <= high")

    def test_largest_selection_ties_and_eight_connected_support_are_deterministic(self):
        image = np.zeros((8, 8), np.uint16)
        image[1, 1] = image[2, 2] = image[5, 5] = image[5, 6] = 100
        result = propose_lut_bbox(image, self.lut)
        self.assertEqual(result["component_count"], 2)
        self.assertEqual(result["bounds"], dict(y0=1, y1=3, x0=1, x1=3))
        self.assertEqual(result["mask_count"], 2)

    def test_search_box_constrains_padding_and_global_coordinates(self):
        result = propose_lut_bbox(self.image, self.lut,
            search_bounds=Bounds(1, 6, 2, 8), padding=20)
        self.assertEqual(result["bounds"], dict(y0=1, y1=6, x0=2, x1=8))
        self.assertEqual(result["mask_count"], 12)

    def test_numpy_integer_search_coordinates_remain_json_serializable(self):
        result = propose_lut_bbox(self.image, self.lut,
            search_bounds=Bounds(*(np.int64(v) for v in (1, 6, 2, 8))),
            padding=np.int64(1), min_area=np.int64(2))
        self.assertEqual(result["bounds"], dict(y0=1, y1=6, x0=2, x1=8))
        json.dumps(result, allow_nan=False)

    def test_anchor_is_not_rescued_to_different_component(self):
        result = propose_lut_bbox(self.image, self.lut, anchor_yx=(6, 8))
        self.assertEqual(result["status"], "anchor_not_in_lut_support")
        self.assertIsNone(result["bounds"])
        result = propose_lut_bbox(self.image, self.lut, anchor_yx=(7, 11),
                                  search_bounds=Bounds(1, 6, 2, 8))
        self.assertEqual(result["status"], "anchor_outside_search")
        self.assertIsNone(result["bounds"])

    def test_no_signal_or_too_small_component_has_no_fabricated_box(self):
        for kwargs, status in [({}, "no_signal"), ({"min_area": 2}, "no_signal")]:
            result = propose_lut_bbox(np.zeros_like(self.image), self.lut, **kwargs)
            self.assertEqual(result["status"], status)
            self.assertIsNone(result["bounds"])
        result = propose_lut_bbox(self.image, self.lut, min_area=100)
        self.assertEqual(result["status"], "no_eligible_component")
        result = propose_lut_bbox(self.image, self.lut, min_area=7, anchor_yx=(7, 11))
        self.assertEqual(result["status"], "anchor_component_below_min_area")
        self.assertIsNone(result["bounds"])

    def test_proposal_and_preview_lut_changes_cannot_mutate_original_arrays(self):
        original = self.image.copy()
        scientific_mask = self.image > 0
        mask_before = scientific_mask.copy()
        original_box = Bounds(0, 12, 0, 16)
        for lut in [self.lut, LUT(150, 500, "488")]:
            propose_lut_bbox(self.image, lut, search_bounds=original_box)
            render_preview(self.image, lut, overlays=[dict(mask=scientific_mask)])
        np.testing.assert_array_equal(self.image, original)
        np.testing.assert_array_equal(scientific_mask, mask_before)
        self.assertEqual(original_box, Bounds(0, 12, 0, 16))

    def test_wrong_channel_and_invalid_proposal_inputs_fail(self):
        bad = [dict(channel="561"), dict(padding=-1), dict(padding=True),
               dict(min_area=0), dict(min_area=1.5), dict(range_policy="guess"),
               dict(anchor_yx=(np.nan, 3)), dict(anchor_yx=(3,)),
               dict(anchor_yx=(True, False)), dict(anchor_yx=(-1, 2)),
               dict(anchor_yx=(12, 2)), dict(search_bounds=Bounds(0, 14, 0, 16))]
        for kwargs in bad:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                propose_lut_bbox(self.image, self.lut, **kwargs)
        for image in [np.full((4, 4), np.nan), np.zeros((3, 4, 4)),
                      np.zeros((0, 4)), np.array([["bad"]])]:
            with self.subTest(shape=image.shape), self.assertRaises(ValueError):
                propose_lut_bbox(image, self.lut)


if __name__ == "__main__":
    unittest.main()
