"""Run without pytest: python -m unittest discover -s tests/audit_v1 -p test_core.py."""
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from tmem_align.audit_v1.contracts import Bounds, identity_channel, require_cyx, strict_overlap
from tmem_align.audit_v1.display import LUT, apply_lut_for_display, bbox_display, longitudinal_lut
from tmem_align.audit_v1.evidence import Evidence
from tmem_align.audit_v1.stitching import Tile, assemble_well, grid_offsets, stage_to_pixel


class ChannelTests(unittest.TestCase):
    def test_selects_c2(self):
        a = np.arange(3 * 4 * 5).reshape(3, 4, 5)
        np.testing.assert_array_equal(identity_channel(a), a[2])

    def test_mcherry_never_changes_identity(self):
        a = np.ones((3, 4, 5))
        before = identity_channel(a).copy()
        a[1] *= 100000
        np.testing.assert_array_equal(identity_channel(a), before)

    def test_rejects_ambiguous_axes(self):
        for shape in [(4, 5), (4, 5, 3), (1, 3, 4, 5)]:
            with self.subTest(shape=shape), self.assertRaises(ValueError):
                require_cyx(np.zeros(shape))

    def test_rejects_wrong_channel_order(self):
        with self.assertRaises(ValueError):
            require_cyx(np.zeros((3, 4, 5)), ["405", "488", "561"])

    def test_rejects_nonfinite(self):
        a = np.zeros((3, 4, 5)); a[2, 0, 0] = np.nan
        with self.assertRaises(ValueError):
            require_cyx(a)


class GeometryTests(unittest.TestCase):
    def test_exact_crop_coordinates(self):
        a = np.arange(30).reshape(5, 6)
        np.testing.assert_array_equal(Bounds(1, 3, 2, 5).crop(a), [[8, 9, 10], [14, 15, 16]])

    def test_crop_does_not_alias_input(self):
        a = np.ones((6, 6)); Bounds(1, 4, 1, 4).crop(a)[:] = 0
        self.assertTrue(np.all(a == 1))

    def test_invalid_bounds_fail(self):
        for b in [Bounds(-1, 3, 0, 3), Bounds(2, 2, 0, 3), Bounds(0, 7, 0, 3),
                  Bounds(0, 3, 0.5, 3)]:
            with self.subTest(b=b), self.assertRaises(ValueError):
                b.crop(np.ones((6, 6)))

    def test_strict_overlap_signs(self):
        self.assertEqual(strict_overlap((20, 30), [(0, 0), (3, -5), (-2, 4)]),
                         Bounds(3, 18, 4, 25))

    def test_empty_overlap_raises(self):
        with self.assertRaises(ValueError):
            strict_overlap((20, 20), [(0, 0), (20, 0)])


class DisplayTests(unittest.TestCase):
    def test_lut_known_gradient(self):
        a = np.array([[-5, 0, 5, 10, 15]], float)
        np.testing.assert_array_equal(apply_lut_for_display(a, LUT(0, 10))[0, :, 0],
                                      [0, 0, 128, 255, 255])

    def test_no_mutation(self):
        a = np.array([[-1., 0., 65535.]])
        before = a.copy(); apply_lut_for_display(a, LUT(0, 1))
        np.testing.assert_array_equal(a, before)

    def test_same_value_same_longitudinal_brightness(self):
        stack = np.stack([np.arange(9).reshape(3, 3), np.arange(9).reshape(3, 3) * 5])
        lut = longitudinal_lut(stack)
        self.assertEqual(apply_lut_for_display(stack[0], lut)[1, 2, 0],
                         apply_lut_for_display(stack[1], lut)[0, 1, 0])

    def test_extreme_lut_does_not_change_bbox_or_sum(self):
        a = np.arange(100).reshape(10, 10); b = Bounds(2, 6, 3, 8)
        total = b.crop(a).sum()
        x = bbox_display(a, b, LUT(0, 1)); y = bbox_display(a, b, LUT(0, 10000))
        self.assertEqual(x.shape, y.shape)
        self.assertFalse(np.array_equal(x, y))
        self.assertEqual(b.crop(a).sum(), total)

    def test_invalid_lut_rejected(self):
        for low, high in [(1, 1), (2, 1), (0, np.inf), (np.nan, 1)]:
            with self.subTest(limits=(low, high)), self.assertRaises(ValueError):
                LUT(low, high)

    def test_flat_image_lut_is_valid(self):
        lut = longitudinal_lut(np.ones((3, 8, 8)))
        self.assertGreater(lut.high, lut.low)

    def test_nonfinite_is_visibly_marked(self):
        rgb = apply_lut_for_display(np.array([[np.nan]]), LUT(0, 1))
        np.testing.assert_array_equal(rgb[0, 0], [255, 96, 0])


class StitchTests(unittest.TestCase):
    def test_coordinate_reconstruction_and_channel_isolation(self):
        truth = np.arange(3 * 6 * 10).reshape(3, 6, 10).astype(float)
        out, coverage, seams = assemble_well([
            Tile("left", truth[:, :, :6], 0, 0), Tile("right", truth[:, :, 4:], 0, 4)], (6, 10))
        np.testing.assert_array_equal(out, truth)
        np.testing.assert_array_equal(coverage[:, 4:6], 2)
        self.assertEqual(seams[1]["mean_abs_difference_by_channel"], [0., 0., 0.])

    def test_mean_overlap_preserves_fractional_values(self):
        a = np.ones((3, 4, 4)); b = a * 2
        out, _, _ = assemble_well([Tile("a", a, 0, 0), Tile("b", b, 0, 2)], (4, 6))
        np.testing.assert_array_equal(out[:, :, 2:4], 1.5)

    def test_missing_tiles_are_nan_and_zero_coverage(self):
        out, coverage, _ = assemble_well([Tile("a", np.ones((3, 2, 2)), 1, 1)], (4, 4))
        self.assertTrue(np.isnan(out[:, 0, :]).all())
        self.assertTrue((coverage[0] == 0).all())

    def test_no_filename_sorting_dependency(self):
        a = np.ones((3, 2, 2)); b = a * 5
        tiles = [Tile("FOV10", b, 0, 2), Tile("FOV2", a, 0, 0)]
        out, _, _ = assemble_well(tiles, (2, 4))
        np.testing.assert_array_equal(out[:, :, :2], 1)
        np.testing.assert_array_equal(out[:, :, 2:], 5)

    def test_duplicates_rejected(self):
        a = np.ones((3, 2, 2))
        for tiles in [[Tile("a", a, 0, 0), Tile("a", a, 0, 2)],
                      [Tile("a", a, 0, 0), Tile("b", a, 0, 0)]]:
            with self.assertRaises(ValueError):
                assemble_well(tiles, (2, 4))

    def test_edges_and_memory_guard(self):
        tile = Tile("a", np.ones((3, 2, 2)), -1, 0)
        with self.assertRaises(ValueError): assemble_well([tile], (4, 4))
        with self.assertRaises(ValueError): assemble_well([tile], (100, 100), max_pixels=100)

    def test_snake_order(self):
        self.assertEqual(grid_offsets(2, 3, (10, 10), 0.2, True),
                         [(0, 0), (0, 8), (0, 16), (8, 16), (8, 8), (8, 0)])

    def test_bad_overlap_rejected(self):
        for fraction in [-0.1, 1, 2, np.nan]:
            with self.assertRaises(ValueError): grid_offsets(2, 2, (10, 10), fraction)

    def test_stage_orientation_and_units(self):
        yx, residual = stage_to_pixel((12, 17), (10, 20), 0.5, [[0, -1], [1, 0]])
        self.assertEqual(yx, (6, 4)); self.assertEqual(residual, (0., 0.))

    def test_stage_axis_duplication_rejected(self):
        with self.assertRaises(ValueError):
            stage_to_pixel((0, 0), (0, 0), 1, [[1, 0], [1, 0]])


class ArtifactIntegrationTests(unittest.TestCase):
    def test_array_to_png_json_and_slides(self):
        with tempfile.TemporaryDirectory() as tmp:
            evidence = Evidence(Path(tmp) / "run", {"evidence_type": "synthetic"})
            a = np.array([[-1., 2.], [70000., np.nan]])
            record = evidence.stage("before_ic", a, LUT(0, 1000), channel="488")
            evidence.finish({"phase_error": np.nan})
            self.assertEqual(record["statistics"]["quantitative_uint16_overflow"], 1)
            self.assertEqual(record["statistics"]["nonfinite"], 1)
            self.assertTrue((evidence.root / "before_ic.png").exists())
            self.assertTrue((evidence.root / "slides.html").exists())
            self.assertIsNone(json.loads((evidence.root / "diagnostics.json").read_text())["phase_error"])

    def test_artifacts_cannot_overwrite_existing_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileExistsError): Evidence(tmp, {})

    def test_artifact_name_is_local(self):
        with tempfile.TemporaryDirectory() as tmp:
            evidence = Evidence(Path(tmp) / "run", {})
            with self.assertRaises(ValueError):
                evidence.stage("../escape", np.zeros((2, 2)), LUT(0, 1), channel="488")


if __name__ == "__main__":
    unittest.main()
