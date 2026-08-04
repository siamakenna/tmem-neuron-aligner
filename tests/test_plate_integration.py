"""End-to-end synthetic integration tests for plate-remount correction (no ND2, fast).

Covers Phase 4 wiring: register_stack's ``plate_offsets`` kwarg composing plate-first then
per-well residual, the default-off byte-identical guarantee, and the weak-well rescue driven by a
transform fitted from the confident wells. See PLATE_REMOUNT_CORRECTION_PLAN.md §3-4, §6.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from scipy.ndimage import shift as ndi_shift

from scripts.run_260213_longitudinal_pilot import register_stack
from tmem_align.plate_align import (
    detect_plate_events,
    fit_plate_transform,
    plate_offset_for_well,
)
from tmem_align.register import apply_shift, register_translation

FOV = 420
DAYS = (8, 12, 16)  # day16 (index 2) is the injected remount


def _base_img(seed: int) -> np.ndarray:
    r = np.random.default_rng(seed)
    img = np.zeros((FOV, FOV), np.float32)
    ys, xs = np.mgrid[:FOV, :FOV]
    for _ in range(55):
        cy, cx = r.uniform(15, FOV - 15, 2)
        img += 3.0 * np.exp(-(((ys - cy) ** 2 + (xs - cx) ** 2) / (2 * 3.5**2)))
    return img


def _rot(deg: float) -> np.ndarray:
    a = np.deg2rad(deg)
    c, s = np.cos(a), np.sin(a)
    return np.array([[c, -s], [s, c]])


BASE = _base_img(99)
# Plate grid (>= 20 wells so detect_plate_events fires) with large stage-like pixel coords.
_POS = np.array([[c * 1400.0, r * 1400.0] for r in range(6) for c in range(8)], float)
_CENTER = _POS.mean(axis=0)
THETA_DEG, T_XY = 1.0, np.array([150.0, -130.0])
# Clean rigid field (fixed = R*q + t) so the fit is exact; (x,y) then flipped to (dy,dx).
_DISP_XY = (_POS - _CENTER) @ _rot(THETA_DEG).T - (_POS - _CENTER) + T_XY
FIELD = _DISP_XY[:, ::-1].copy()  # per-well correction shift (dy, dx) = what registration recovers
MAG = np.hypot(FIELD[:, 0], FIELD[:, 1])

ROWS = [{"well": "W", "day": d, "path": Path(f"W_{d}.nd2")} for d in DAYS]
REMOUNT = 2  # timepoint index of the event day


def _make_stack(shift_dydx, noise: float, seed: int) -> np.ndarray:
    """(T=3, C=2, Y, X). Content at the remount is moved by -shift so masked registration recovers
    +shift (the correction). A second channel rides along to check the shift applies to all C."""
    rng = np.random.default_rng(seed)
    f0 = BASE + rng.normal(0, 0.2, BASE.shape).astype(np.float32)
    f1 = ndi_shift(BASE, (3, -2), order=1).astype(np.float32)
    f1 = f1 + rng.normal(0, 0.2, BASE.shape).astype(np.float32)
    f2 = apply_shift(BASE, -shift_dydx[0], -shift_dydx[1])
    f2 = f2 + rng.normal(0, noise, BASE.shape).astype(np.float32)
    align = np.stack([f0, f1, f2])
    return np.stack([align, align * 0.5], axis=1).astype(np.float32)  # (T, C=2, Y, X)


def _reg(stack, plate_offsets=None, ref_mode="to_first"):
    return register_stack(
        stack,
        well="W",
        rows=ROWS,
        alignment_channel_index=0,
        alignment_channel_label="488",
        ref_mode=ref_mode,
        plate_offsets=plate_offsets,
    )


def _net(qc, index=REMOUNT):
    return np.array([qc[index]["estimated_y_shift"], qc[index]["estimated_x_shift"]])


def _fit_event(exclude_index):
    """Fit the plate transform from the confident wells (one weak well withheld via post=0)."""
    post = np.full(len(_POS), 0.15)
    post[exclude_index] = 0.0
    return fit_plate_transform(_POS, FIELD, day=16, post_corr=post, qc_gate=0.07)


# --- default-off / regression --------------------------------------------------------------


def test_none_registers_and_matches_empty_dict():
    """Golden: plate_offsets=None recovers the injected shift, and {} is treated identically."""
    stack = _make_stack((30.0, -20.0), noise=0.3, seed=1)
    reg_none, qc_none, crop_none = _reg(stack, plate_offsets=None)
    assert np.allclose(_net(qc_none), (30.0, -20.0), atol=2.0)
    assert qc_none[REMOUNT]["post_registration_correlation"] > 0.3

    reg_empty, qc_empty, crop_empty = _reg(stack, plate_offsets={})
    assert np.array_equal(reg_none, reg_empty)  # empty dict == off, byte-identical
    assert crop_none == crop_empty
    assert np.array_equal(_net(qc_none), _net(qc_empty))


def test_missing_day_gets_zero_prior():
    """A day absent from plate_offsets gets a (0,0) prior — only the event day is corrected."""
    stack = _make_stack((30.0, -20.0), noise=0.3, seed=1)
    _, qc_none, _ = _reg(stack, plate_offsets=None)
    _, qc_off, _ = _reg(stack, plate_offsets={16: (7.0, -5.0)})  # day12 (index 1) omitted
    assert np.array_equal(_net(qc_none, 1), _net(qc_off, 1))  # non-event day unchanged


def test_net_equals_prior_plus_residual():
    """Composition: reported net = plate prior + per-well residual on the pre-shifted frame."""
    stack = _make_stack((30.0, -20.0), noise=0.3, seed=1)
    prior = (12.0, -8.0)
    _, qc, _ = _reg(stack, plate_offsets={16: prior})
    ref = stack[0, 0]
    moving = stack[REMOUNT, 0]
    pre = apply_shift(moving, prior[0], prior[1])
    _, (rdy, rdx), _ = register_translation(
        ref, pre, robust_preprocess=False, mask_percentile=20.0
    )
    expected = np.array([prior[0] + rdy, prior[1] + rdx])
    assert np.allclose(_net(qc), expected, atol=1e-6)  # plate-first, residual-second, not doubled
    assert qc[REMOUNT]["post_registration_correlation"] > 0.3  # still well aligned


# --- rescue (the headline claim) -----------------------------------------------------------


def test_event_is_detected_from_the_field():
    S = np.zeros((3, len(_POS), 2))
    S[1] = np.tile((3.0, -2.0), (len(_POS), 1))
    S[2] = FIELD
    assert detect_plate_events(list(DAYS), S, _POS) == [16]


def test_weak_well_rescued_by_fitted_transform():
    """A weak well that fails self-registration at the remount is recovered by the plate prior
    fitted from the *other* (confident) wells; net matches the known transform, post-corr improves."""
    weak = int(np.argmax(MAG))  # far corner: largest jump
    want = FIELD[weak]
    wstack = _make_stack(want, noise=1.3, seed=2)

    _, qc_none, _ = _reg(wstack, plate_offsets=None)
    none_err = np.linalg.norm(_net(qc_none) - want)
    assert none_err > 15.0  # per-well registration fails at the remount jump

    event = _fit_event(weak)
    assert event is not None and event.rms_px < 1.0
    off = plate_offset_for_well(event, _POS[weak])  # predicted for the withheld well
    _, qc_plate, _ = _reg(wstack, plate_offsets={16: off})

    assert np.linalg.norm(_net(qc_plate) - want) < 3.0  # rescued to the known transform
    assert (
        qc_plate[REMOUNT]["post_registration_correlation"]
        > qc_none[REMOUNT]["post_registration_correlation"]
    )


def test_no_harm_to_good_well():
    """Applying the correct fitted prior to a well that already registers must not degrade it."""
    good = int(np.argmin(MAG))  # near centre: small jump, self-registers fine
    gstack = _make_stack(FIELD[good], noise=0.3, seed=3)
    _, qc_none, _ = _reg(gstack, plate_offsets=None)
    off = plate_offset_for_well(_fit_event(int(np.argmax(MAG))), _POS[good])
    _, qc_plate, _ = _reg(gstack, plate_offsets={16: off})
    assert np.linalg.norm(_net(qc_plate) - _net(qc_none)) < 2.0
    assert (
        qc_plate[REMOUNT]["post_registration_correlation"]
        >= qc_none[REMOUNT]["post_registration_correlation"] - 0.01
    )


# --- anchored path -------------------------------------------------------------------------


def test_anchored_path_composes_and_rescues():
    weak = int(np.argmax(MAG))
    want = FIELD[weak]
    wstack = _make_stack(want, noise=1.3, seed=2)

    reg_none, _, _ = _reg(wstack, plate_offsets=None, ref_mode="anchored")
    reg_empty, _, _ = _reg(wstack, plate_offsets={}, ref_mode="anchored")
    assert np.array_equal(reg_none, reg_empty)  # default-off byte-identical in anchored mode too

    off = plate_offset_for_well(_fit_event(weak), _POS[weak])
    _, qc_plate, _ = _reg(wstack, plate_offsets={16: off}, ref_mode="anchored")
    assert np.linalg.norm(_net(qc_plate) - want) < 3.0
