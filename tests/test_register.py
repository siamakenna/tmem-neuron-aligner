from __future__ import annotations

import numpy as np
import pytest
from scipy.ndimage import shift as ndi_shift

from scripts.run_260213_longitudinal_pilot import _anchored_shifts, register_stack
from tmem_align.register import apply_shift, register_translation
from tmem_align.registration_qc import (
    classify_registration_qc,
    common_overlap_crop,
)


def test_register_translation_recovers_known_shift():
    image = np.zeros((96, 96), dtype=np.float32)
    image[30:42, 40:52] = 1.0
    image[60:68, 18:30] = 0.8
    known_shift = (5.0, -7.0)
    moving = ndi_shift(image, shift=known_shift, order=1, mode="constant", cval=0)

    _, recovered, error = register_translation(image, moving, upsample_factor=10)

    assert abs(recovered[0] + known_shift[0]) < 0.25
    assert abs(recovered[1] + known_shift[1]) < 0.25
    assert error >= 0


def test_register_translation_with_robust_preprocess():
    image = np.zeros((96, 96), dtype=np.float32)
    image[30:42, 40:52] = 1.0
    # Add outlier pixels that would confuse naive correlation
    image[10, 10] = 50.0
    image[80, 80] = 50.0
    known_shift = (3.0, -4.0)
    moving = ndi_shift(image, shift=known_shift, order=1, mode="constant", cval=0)
    moving[15, 15] = 50.0

    _, recovered, _ = register_translation(
        image,
        moving,
        upsample_factor=10,
        robust_preprocess=True,
    )

    assert abs(recovered[0] + known_shift[0]) < 0.5
    assert abs(recovered[1] + known_shift[1]) < 0.5


def test_register_translation_masked_recovers_shift():
    # sparse bright squares on dark background — the sparse-neuron regime
    image = np.zeros((96, 96), dtype=np.float32)
    image[30:38, 40:48] = 1.0
    image[60:66, 20:26] = 0.9
    known_shift = (4.0, -6.0)
    moving = ndi_shift(image, shift=known_shift, order=1, mode="constant", cval=0)

    _, recovered, error = register_translation(
        image, moving, robust_preprocess=False, mask_percentile=20.0
    )

    # masked correlation is integer-pixel; allow 1 px tolerance
    assert abs(recovered[0] + known_shift[0]) < 1.0
    assert abs(recovered[1] + known_shift[1]) < 1.0
    assert np.isnan(error)  # masked path has no phase error


def test_max_shift_pixels_guard():
    image = np.zeros((64, 64), dtype=np.float32)
    image[20:30, 20:30] = 1.0
    moving = ndi_shift(image, shift=(20.0, 0.0), order=1, mode="constant", cval=0)

    with pytest.raises(ValueError, match="max_shift_pixels"):
        register_translation(image, moving, max_shift_pixels=5.0)


def test_apply_shift_round_trip():
    image = np.zeros((64, 64), dtype=np.float32)
    image[20:30, 20:30] = 1.0
    shifted = apply_shift(image, 3.0, -5.0)
    restored = apply_shift(shifted, -3.0, 5.0)
    # Interior region should survive the round trip
    assert np.allclose(image[25:28, 25:28], restored[25:28, 25:28], atol=0.05)


# --- anchored / masked temporal registration -------------------------------------------------

_N = 128


def _blobs(centers, amp=1.0, sigma=7.0):
    yy, xx = np.mgrid[:_N, :_N]
    frame = np.zeros((_N, _N), np.float32)
    for cy, cx in centers:
        frame += amp * np.exp(-(((yy - cy) ** 2 + (xx - cx) ** 2) / (2.0 * sigma**2)))
    return frame


def _drift(n_t, step_y=3.0, step_x=-2.0):
    shifts = [(0.0, 0.0)]
    dy = dx = 0.0
    for _ in range(1, n_t):
        dy += step_y
        dx += step_x
        shifts.append((dy, dx))
    return shifts


_PAT_A = _blobs([(40, 50), (70, 80), (55, 95), (90, 40)])
_PAT_B = _blobs([(30, 90), (100, 60), (50, 30), (85, 100)])


def test_anchored_recovers_drift_with_decorrelation():
    """Gradual morphology change (t0 decorrelates from late frames, adjacent frames stay similar)
    plus a known rigid drift. Anchored should re-anchor once the field decorrelates and still
    recover the true drift on the recoverable frames."""
    n_t = 8
    shifts = _drift(n_t)
    frames = []
    for t, (dy, dx) in enumerate(shifts):
        a = t / (n_t - 1)
        frames.append(apply_shift((1 - a) * _PAT_A + a * _PAT_B, dy, dx).astype(np.float32))

    net, post, reanchored = _anchored_shifts(frames, thresh=0.4)

    # Net shift is stored as displacement-to-t0; it should cancel the applied drift everywhere.
    for t, (dy, dx) in enumerate(shifts):
        err = np.hypot(net[t][0] + dy, net[t][1] + dx)
        assert err < 2.0, f"t={t} drift not recovered (err={err:.2f}px)"
    # No re-anchoring while the field still correlates with t0 (early, high-corr frames)...
    assert not any(reanchored[:4])
    # ...and a re-anchor fires at the onset of decorrelation.
    assert reanchored[4] is True
    assert post[0] == 1.0


def test_anchored_never_anchors_on_failed_frame():
    """One garbage frame must not become an anchor: the frame after it recovers the true drift
    (proving it composed against the last GOOD frame, not the garbage one)."""
    n_t = 7
    shifts = _drift(n_t)
    frames = [apply_shift(_PAT_A, dy, dx).astype(np.float32) for dy, dx in shifts]
    frames[4] = (np.random.default_rng(1).random((_N, _N)) * _PAT_A.max()).astype(np.float32)

    net, post, reanchored = _anchored_shifts(frames, thresh=0.3)

    assert reanchored[4] is True  # garbage frame triggers a re-anchor attempt
    # Garbage frame itself is unrecoverable and not eligible as a future anchor.
    assert post[4] < 0.3
    assert np.hypot(net[4][0] + shifts[4][0], net[4][1] + shifts[4][1]) > 10.0
    # The frame AFTER the garbage recovers the true drift -> it anchored on the last good frame.
    for t in (5, 6):
        err = np.hypot(net[t][0] + shifts[t][0], net[t][1] + shifts[t][1])
        assert err < 2.0, f"t={t} anchored on garbage (err={err:.2f}px)"


def test_anchored_reanchor_trigger_brackets_threshold():
    """The re-anchor trigger fires iff post-corr to the anchor is below the threshold."""
    frames = [
        _PAT_A,
        apply_shift(_PAT_A, 3.0, -2.0).astype(np.float32),
        apply_shift(0.45 * _PAT_A + 0.55 * _PAT_B, 6.0, -4.0).astype(np.float32),
    ]
    # With thresh=0 nothing re-anchors, so post[2] is the true correlation to the anchor (t0).
    _, post, reanchored = _anchored_shifts(frames, thresh=0.0)
    p2 = post[2]
    assert 0.05 < p2 < 0.95  # a meaningful mid-range value to bracket
    assert reanchored[2] is False

    _, _, re_above = _anchored_shifts(frames, thresh=p2 + 0.02)
    _, _, re_below = _anchored_shifts(frames, thresh=p2 - 0.02)
    assert re_above[2] is True
    assert re_below[2] is False


def _tcyx_stack(n_t=5):
    """Fixed 2-channel TCYX stack with cumulative drift on both channels."""
    shifts = _drift(n_t)
    frames = []
    for dy, dx in shifts:
        cyx = np.stack([_PAT_A, _PAT_A * 0.3], axis=0)
        frames.append(apply_shift(cyx, dy, dx).astype(np.float32))
    return np.stack(frames, axis=0)


def test_to_first_default_is_unchanged_golden():
    """Regression: register_stack(ref_mode='to_first') must equal the plain masked-to-t0
    computation — adding the anchored params changed nothing on the default path."""
    stack = _tcyx_stack()
    rows = [{"day": d} for d in (8, 12, 16, 20, 24)]

    registered, qc_rows, crop = register_stack(
        stack,
        well="E05",
        rows=rows,
        alignment_channel_index=0,
        alignment_channel_label="488",
    )

    # Independent replica of the to_first path.
    exp_registered = [stack[0]]
    exp_shifts = [(0.0, 0.0)]
    for t in range(1, stack.shape[0]):
        _, (dy, dx), _ = register_translation(
            stack[0, 0], stack[t, 0], robust_preprocess=False, mask_percentile=20.0
        )
        exp_registered.append(apply_shift(stack[t], dy, dx))
        exp_shifts.append((dy, dx))
    exp_registered = np.stack(exp_registered, axis=0)
    exp_crop = common_overlap_crop(stack.shape[-2:], exp_shifts, robust=True)

    assert np.allclose(registered, exp_registered)
    assert crop == exp_crop
    got_shifts = [(r["estimated_y_shift"], r["estimated_x_shift"]) for r in qc_rows]
    assert got_shifts == exp_shifts
    assert qc_rows[1]["qc_note"] == "masked_phase_cross_correlation_on_raw_stable_channel"


def test_qc_gate_min_post_correlation():
    """A timepoint whose post-corr sits between 0.02 and 0.07 passes under the old lib default
    but fails under the calibrated Phase-1 gate of 0.07."""
    passed = classify_registration_qc(
        0.99, 1.0, 1.0, _N, _N, post_correlation=0.05, min_post_correlation=0.02
    )
    failed = classify_registration_qc(
        0.99, 1.0, 1.0, _N, _N, post_correlation=0.05, min_post_correlation=0.07
    )
    assert passed["qc_pass"] is True
    assert failed["qc_pass"] is False


def test_register_stack_anchored_qc_fields():
    """Anchored mode populates the auditable QC fields and the per-well churn verdict."""
    stack = _tcyx_stack()
    rows = [{"day": d} for d in (8, 12, 16, 20, 24)]
    _, qc_rows, _ = register_stack(
        stack,
        well="E05",
        rows=rows,
        alignment_channel_index=0,
        alignment_channel_label="488",
        ref_mode="anchored",
    )
    assert qc_rows[0]["qc_note"] == "anchored_masked_phase_cross_correlation"
    for row in qc_rows:
        assert "reanchored" in row
        assert "anchor_ref_day" in row
        assert "well_registration_qc_pass" in row
        assert "anchor_churn" in row
    # Clean stack (pure drift, no decorrelation): no re-anchoring, well passes.
    assert qc_rows[0]["n_reanchors"] == 0
    assert qc_rows[0]["well_registration_qc_pass"] is True
