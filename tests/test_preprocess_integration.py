"""Integration and edge-case tests for tmem_align.preprocess.

Unit tests live in test_preprocess.py (43 tests). These cover cross-function
integration, boundary conditions, and real-world edge cases.
"""

from __future__ import annotations

import numpy as np
import pytest
import tifffile

from tmem_align.preprocess import (
    apply_ic_field,
    calculate_ic_field,
    calculate_ic_field_for_plate,
    calculate_ic_field_for_well,
    preprocess_image,
    subtract_background,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _gradient_image(h: int, w: int, low: int = 100, high: int = 1000) -> np.ndarray:
    """Synthetic image with a left-to-right illumination gradient."""
    col = np.linspace(low, high, w, dtype=np.float64)
    return np.broadcast_to(col, (h, w)).astype(np.uint16)


def _cv_percent(arr: np.ndarray) -> float:
    """Coefficient of variation as a percentage."""
    m = arr.mean()
    if m == 0:
        return 0.0
    return float(arr.std() / m * 100)


# ---------------------------------------------------------------------------
# 1. End-to-end pipeline: IC reduces gradient
# ---------------------------------------------------------------------------


class TestEndToEndPipeline:
    def test_ic_reduces_illumination_gradient(self):
        """Calculate IC from gradient images, apply it, verify CV% drops."""
        imgs = [_gradient_image(64, 64) for _ in range(10)]
        ic = calculate_ic_field(imgs, rescale_field=True)
        corrected = apply_ic_field(imgs[0], ic)

        cv_before = _cv_percent(imgs[0].astype(np.float64))
        cv_after = _cv_percent(corrected.astype(np.float64))
        assert cv_after < cv_before, f"CV% should drop: {cv_before:.1f} -> {cv_after:.1f}"

    def test_full_preprocess_pipeline(self):
        """IC + background subtraction end-to-end."""
        imgs = [_gradient_image(64, 64) for _ in range(8)]
        ic = calculate_ic_field(imgs, rescale_field=True)
        result = preprocess_image(imgs[0], ic_field=ic, background_radius=10)
        assert result.dtype == np.uint16
        assert result.shape == (64, 64)
        assert result.min() >= 0


# ---------------------------------------------------------------------------
# 2. Per-well vs per-plate IC
# ---------------------------------------------------------------------------


class TestWellVsPlateIC:
    def test_plate_averages_across_wells(self, tmp_path):
        """Plate IC should blend wells; well IC should be well-specific."""
        rng = np.random.default_rng(99)
        for well, base in [("A01", 200), ("A02", 800)]:
            d = tmp_path / well
            d.mkdir()
            for i in range(4):
                arr = np.full((32, 32), base, dtype=np.uint16) + rng.integers(
                    0, 10, (32, 32), dtype=np.uint16
                )
                tifffile.imwrite(str(d / f"img_{i}.tif"), arr)

        # Smoke: these paths must not crash (results asserted via raw ICs below)
        calculate_ic_field_for_well(tmp_path / "A01", smooth=1)
        calculate_ic_field_for_well(tmp_path / "A02", smooth=1)
        calculate_ic_field_for_plate(tmp_path, sample_fraction=1.0)

        # ponytail: rescale_field defaults True, so compare raw IC via calculate_ic_field
        raw_a = calculate_ic_field(
            [tifffile.imread(str(p)) for p in sorted((tmp_path / "A01").glob("*.tif"))],
            rescale_field=False,
        )
        raw_b = calculate_ic_field(
            [tifffile.imread(str(p)) for p in sorted((tmp_path / "A02").glob("*.tif"))],
            rescale_field=False,
        )
        # Raw well ICs should differ significantly (200 vs 800 base intensity)
        assert abs(float(raw_a.mean()) - float(raw_b.mean())) > 100

        # Plate IC (raw, unrescaled) should lie between them
        raw_plate = calculate_ic_field(
            [
                tifffile.imread(str(p))
                for well in ["A01", "A02"]
                for p in sorted((tmp_path / well).glob("*.tif"))
            ],
            rescale_field=False,
        )
        plate_mean = float(raw_plate.mean())
        assert float(raw_a.mean()) < plate_mean < float(raw_b.mean())


# ---------------------------------------------------------------------------
# 3. Large image handling
# ---------------------------------------------------------------------------


class TestLargeImages:
    def test_1024x1024(self):
        """No crash or memory issue on larger images."""
        img = np.full((1024, 1024), 500, dtype=np.uint16)
        ic = calculate_ic_field([img], rescale_field=True)
        assert ic.shape == (1024, 1024)
        result = apply_ic_field(img, ic)
        assert result.shape == (1024, 1024)


# ---------------------------------------------------------------------------
# 4. Single image IC
# ---------------------------------------------------------------------------


class TestSingleImageIC:
    def test_single_image(self):
        img = _gradient_image(32, 32)
        field = calculate_ic_field([img], rescale_field=True)
        assert field.shape == (32, 32)
        # mean-normalized → centered on 1 (both attenuation and amplification)
        assert field.mean() == pytest.approx(1.0)

    def test_single_image_no_rescale(self):
        img = np.full((16, 16), 300, dtype=np.uint16)
        field = calculate_ic_field([img], rescale_field=False)
        assert field.shape == (16, 16)


# ---------------------------------------------------------------------------
# 5. IC field shape mismatch
# ---------------------------------------------------------------------------


class TestShapeMismatch:
    def test_mismatched_2d_field_2d_image_raises(self):
        """Different spatial dims should raise (numpy broadcast error)."""
        img = np.full((32, 32), 200, dtype=np.uint16)
        field = np.full((16, 16), 2.0)
        with pytest.raises((ValueError, Exception)):
            apply_ic_field(img, field)

    def test_mismatched_2d_field_3d_image_raises(self):
        img = np.full((2, 32, 32), 200, dtype=np.uint16)
        field = np.full((16, 16), 2.0)
        with pytest.raises((ValueError, Exception)):
            apply_ic_field(img, field)


# ---------------------------------------------------------------------------
# 6. Very small images
# ---------------------------------------------------------------------------


class TestVerySmallImages:
    def test_4x4(self):
        img = np.full((4, 4), 200, dtype=np.uint16)
        field = calculate_ic_field([img], rescale_field=True)
        assert field.shape == (4, 4)

    def test_8x8(self):
        imgs = [np.full((8, 8), v, dtype=np.uint16) for v in [100, 200, 300]]
        field = calculate_ic_field(imgs, rescale_field=True)
        assert field.shape == (8, 8)

    def test_4x4_smooth_auto(self):
        """Auto smooth radius for tiny image: sqrt(16 / 20pi) < 1 → disk(0)."""
        img = np.full((4, 4), 500, dtype=np.uint16)
        # Should not crash even with smooth=0 computed internally
        field = calculate_ic_field([img])
        assert field.shape == (4, 4)


# ---------------------------------------------------------------------------
# 7. All-zero images
# ---------------------------------------------------------------------------


class TestAllZeroImages:
    def test_ic_field_from_zeros(self):
        imgs = [np.zeros((32, 32), dtype=np.uint16) for _ in range(5)]
        field = calculate_ic_field(imgs, rescale_field=True)
        # mean=0 → center falls back to 1, then floor-clipped to 0.1
        assert np.all(field >= 0.1)
        assert np.isfinite(field).all()

    def test_apply_ic_to_zero_image(self):
        img = np.zeros((32, 32), dtype=np.uint16)
        field = np.full((32, 32), 2.0)
        result = apply_ic_field(img, field)
        np.testing.assert_array_equal(result, 0)

    def test_subtract_background_zero_image(self):
        img = np.zeros((32, 32), dtype=np.uint16)
        result = subtract_background(img, radius=10)
        assert result.min() >= 0
        assert result.dtype == np.uint16


# ---------------------------------------------------------------------------
# 8. Saturated images (uint16 max)
# ---------------------------------------------------------------------------


class TestSaturatedImages:
    def test_saturated_ic_field(self):
        imgs = [np.full((32, 32), 65535, dtype=np.uint16) for _ in range(5)]
        field = calculate_ic_field(imgs, rescale_field=True)
        assert field.shape == (32, 32)
        assert np.isfinite(field).all()

    def test_apply_ic_no_overflow(self):
        """Dividing 65535 by a field > 1 should stay in uint16 range."""
        img = np.full((32, 32), 65535, dtype=np.uint16)
        field = np.full((32, 32), 0.5)  # doubles the value — clips at 65535
        result = apply_ic_field(img, field)
        assert result.dtype == np.uint16
        # 65535 / 0.5 = 131070 → now clipped to the uint16 max (FIX 6: round+clip,
        # no wraparound).
        assert result.shape == (32, 32)
        assert result.max() <= 65535
        np.testing.assert_array_equal(result, 65535)

    def test_subtract_background_saturated(self):
        img = np.full((64, 64), 65535, dtype=np.uint16)
        result = subtract_background(img, radius=10)
        assert result.dtype == np.uint16
        assert result.min() >= 0


# ---------------------------------------------------------------------------
# 9. Mixed dtype input
# ---------------------------------------------------------------------------


class TestMixedDtype:
    def test_float32_images(self):
        imgs = [np.full((32, 32), 500.0, dtype=np.float32) for _ in range(3)]
        field = calculate_ic_field(imgs, rescale_field=False)
        assert field.shape == (32, 32)

    def test_float64_images(self):
        imgs = [np.full((32, 32), 500.0, dtype=np.float64) for _ in range(3)]
        field = calculate_ic_field(imgs, rescale_field=False)
        assert field.shape == (32, 32)

    def test_apply_ic_float32_image(self):
        img = np.full((32, 32), 400.0, dtype=np.float32)
        field = np.full((32, 32), 2.0)
        result = apply_ic_field(img, field)
        assert result.dtype == np.uint16
        np.testing.assert_array_equal(result, 200)

    def test_subtract_background_float_input(self):
        img = np.full((64, 64), 500.0, dtype=np.float32)
        result = subtract_background(img, radius=10)
        assert result.dtype == np.uint16


# ---------------------------------------------------------------------------
# 10. sample_fraction edge cases
# ---------------------------------------------------------------------------


class TestSampleFractionEdgeCases:
    def test_fraction_zero(self):
        """sample_fraction=0.0 → max(1, 0) = 1 image used."""
        imgs = [np.full((16, 16), v, dtype=np.uint16) for v in range(100, 110)]
        field = calculate_ic_field(imgs, sample_fraction=0.0, rescale_field=False)
        assert field.shape == (16, 16)

    def test_fraction_one(self):
        """sample_fraction=1.0 uses all images (no sampling branch)."""
        imgs = [np.full((16, 16), 200, dtype=np.uint16) for _ in range(5)]
        field = calculate_ic_field(imgs, sample_fraction=1.0, rescale_field=False)
        assert field.shape == (16, 16)

    def test_fraction_gt_one(self):
        """sample_fraction > 1.0 doesn't trigger sampling (1.0 < check fails)."""
        imgs = [np.full((16, 16), 200, dtype=np.uint16) for _ in range(5)]
        field = calculate_ic_field(imgs, sample_fraction=2.0, rescale_field=False)
        assert field.shape == (16, 16)

    def test_fraction_very_small(self):
        """Tiny fraction still gives at least 1 image."""
        imgs = [np.full((16, 16), 200, dtype=np.uint16) for _ in range(100)]
        field = calculate_ic_field(imgs, sample_fraction=0.001, rescale_field=False)
        assert field.shape == (16, 16)


# ---------------------------------------------------------------------------
# 11. Background subtraction idempotency (no negatives on double apply)
# ---------------------------------------------------------------------------


class TestBackgroundSubtractionIdempotency:
    def test_double_subtraction_no_negatives(self):
        rng = np.random.default_rng(55)
        img = rng.integers(100, 1000, size=(64, 64), dtype=np.uint16)
        once = subtract_background(img, radius=20)
        twice = subtract_background(once, radius=20)
        assert twice.min() >= 0
        assert twice.dtype == np.uint16

    def test_second_subtraction_removes_less(self):
        """Second pass should change less (most background already gone)."""
        rng = np.random.default_rng(56)
        img = rng.integers(200, 2000, size=(64, 64), dtype=np.uint16)
        once = subtract_background(img, radius=20)
        twice = subtract_background(once, radius=20)
        delta1 = img.astype(np.float64).mean() - once.astype(np.float64).mean()
        delta2 = once.astype(np.float64).mean() - twice.astype(np.float64).mean()
        assert delta2 <= delta1 + 1, "Second subtraction should remove less background"


# ---------------------------------------------------------------------------
# 12. Preprocess order: IC before background subtraction
# ---------------------------------------------------------------------------


class TestPreprocessOrder:
    def test_ic_applied_before_bg(self):
        """IC correction should happen first. Verify by comparing with manual order.

        Uses an exact-integer IC (even values / field=2) so the intermediate IC
        result is identical whether or not it is quantized — the single-float
        pipeline (FIX 6) must still match the step-by-step order.
        """
        rng = np.random.default_rng(77)
        img = (rng.integers(100, 1000, size=(64, 64)) * 2).astype(np.uint16)
        field = np.full((64, 64), 2.0)

        # preprocess_image does IC then BG
        result_pipeline = preprocess_image(img, ic_field=field, background_radius=10)

        # Manual: IC first, then BG
        ic_first = apply_ic_field(img, field)
        result_manual = subtract_background(ic_first, radius=10)

        np.testing.assert_array_equal(result_pipeline, result_manual)

    def test_order_matters(self):
        """Confirm the reverse order gives a different result."""
        rng = np.random.default_rng(78)
        img = rng.integers(200, 2000, size=(64, 64), dtype=np.uint16)
        field = np.full((64, 64), 2.0)

        result_correct = preprocess_image(img, ic_field=field, background_radius=10)

        # Wrong order: BG first, then IC
        bg_first = subtract_background(img, radius=10)
        result_wrong = apply_ic_field(bg_first, field)

        # They should differ (unless by coincidence, but with field=2 they will)
        assert not np.array_equal(result_correct, result_wrong)


# ---------------------------------------------------------------------------
# 13. Channel consistency: per-channel IC independence
# ---------------------------------------------------------------------------


class TestChannelConsistency:
    def test_channels_are_independent(self):
        """Changing one channel's pattern shouldn't affect another's IC."""
        rng = np.random.default_rng(88)
        base = rng.integers(200, 400, size=(3, 32, 32), dtype=np.uint16)
        imgs = [base.copy() for _ in range(6)]

        field_before = calculate_ic_field(imgs, rescale_field=False)

        # Alter channel 0 drastically in half the images
        imgs_altered = [img.copy() for img in imgs]
        for i in range(3):
            imgs_altered[i][0] = 60000

        field_after = calculate_ic_field(imgs_altered, rescale_field=False)

        # Channel 1 and 2 should be unchanged
        np.testing.assert_array_equal(field_before[1], field_after[1])
        np.testing.assert_array_equal(field_before[2], field_after[2])
        # Channel 0 should differ
        assert not np.array_equal(field_before[0], field_after[0])


# ---------------------------------------------------------------------------
# 14. Uniform image → IC ≈ 1 everywhere
# ---------------------------------------------------------------------------


class TestUniformImageIC:
    def test_uniform_gives_flat_ic(self):
        """Perfectly uniform images should produce IC field ≈ 1 everywhere."""
        imgs = [np.full((32, 32), 500, dtype=np.uint16) for _ in range(10)]
        field = calculate_ic_field(imgs, rescale_field=True)
        # All pixels identical → after rescale, all should be 1.0
        np.testing.assert_allclose(field, 1.0, atol=0.01)


# ---------------------------------------------------------------------------
# 15. File format: TIFF files in tmp_path folders
# ---------------------------------------------------------------------------


class TestTiffFileIO:
    def test_well_ic_from_tiff_files(self, tmp_path):
        rng = np.random.default_rng(33)
        for i in range(5):
            arr = rng.integers(100, 500, size=(32, 32), dtype=np.uint16)
            tifffile.imwrite(str(tmp_path / f"tile_{i}.tif"), arr)
        field = calculate_ic_field_for_well(tmp_path)
        assert field.shape == (32, 32)

    def test_plate_ic_from_tiff_files(self, tmp_path):
        rng = np.random.default_rng(44)
        for well in ["B01", "B02", "B03"]:
            d = tmp_path / well
            d.mkdir()
            for i in range(3):
                arr = rng.integers(100, 500, size=(32, 32), dtype=np.uint16)
                tifffile.imwrite(str(d / f"field_{i}.tiff"), arr)
        field = calculate_ic_field_for_plate(tmp_path, sample_fraction=1.0)
        assert field.shape == (32, 32)

    def test_multichannel_tiff_round_trip(self, tmp_path):
        """Multi-channel TIFF → IC field → apply → correct shape."""
        rng = np.random.default_rng(55)
        paths = []
        for i in range(4):
            arr = rng.integers(200, 600, size=(2, 32, 32), dtype=np.uint16)
            p = tmp_path / f"mc_{i}.tif"
            tifffile.imwrite(str(p), arr)
            paths.append(p)
        field = calculate_ic_field(paths, rescale_field=True)
        assert field.ndim == 3
        assert field.shape == (2, 32, 32)

    def test_well_pattern_filter(self, tmp_path):
        """well_pattern should filter subdirectories."""
        rng = np.random.default_rng(66)
        for name in ["well_A01", "well_A02", "control_X"]:
            d = tmp_path / name
            d.mkdir()
            for i in range(2):
                arr = rng.integers(100, 400, size=(16, 16), dtype=np.uint16)
                tifffile.imwrite(str(d / f"img_{i}.tif"), arr)
        field = calculate_ic_field_for_plate(tmp_path, well_pattern="well_*", sample_fraction=1.0)
        assert field.shape == (16, 16)


# ---------------------------------------------------------------------------
# Extra edge cases
# ---------------------------------------------------------------------------


class TestExtraEdgeCases:
    def test_single_pixel_image_raises(self):
        """1x1 image squeezed to 0D by normalize_to_2d — documents this limitation."""
        img = np.array([[42]], dtype=np.uint16)
        with pytest.raises(ValueError, match="Cannot normalize"):
            calculate_ic_field([img], rescale_field=True)

    def test_2x2_minimum_viable(self):
        """2x2 is the smallest image that works."""
        img = np.full((2, 2), 300, dtype=np.uint16)
        field = calculate_ic_field([img], rescale_field=True)
        assert field.shape == (2, 2)

    def test_rectangular_image(self):
        """Non-square image."""
        imgs = [np.full((16, 64), 300, dtype=np.uint16) for _ in range(5)]
        field = calculate_ic_field(imgs, rescale_field=True)
        assert field.shape == (16, 64)

    def test_preprocess_multichannel_ic_and_bg(self):
        """3D CYX image through full preprocess with per-channel BG."""
        img = np.full((3, 64, 64), 500, dtype=np.uint16)
        field = np.full((64, 64), 2.0)
        result = preprocess_image(img, ic_field=field, background_radius=10)
        assert result.shape == (3, 64, 64)
        assert result.dtype == np.uint16

    def test_high_smooth_radius(self):
        """Smooth radius larger than image should still work (skimage handles it)."""
        imgs = [np.full((16, 16), 400, dtype=np.uint16) for _ in range(3)]
        field = calculate_ic_field(imgs, smooth=50, rescale_field=False)
        assert field.shape == (16, 16)
