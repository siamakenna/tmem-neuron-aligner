"""Synthetic tests for plate-wise remount correction (no ND2). See PLATE_REMOUNT_CORRECTION_PLAN.py §6."""
from __future__ import annotations

import numpy as np

from tmem_align.plate_align import (
    detect_plate_events,
    fit_plate_transform,
    plate_offset_for_well,
)
from tmem_align.register import apply_shift
from tmem_align.registration_qc import correlation


def _grid(nx: int = 12, ny: int = 10, pitch: float = 6948.0) -> np.ndarray:
    """(n, 2) well XY positions in pixels on a plate grid."""
    xs, ys = np.meshgrid(np.arange(nx) * pitch, np.arange(ny) * pitch)
    return np.column_stack([xs.ravel(), ys.ravel()]).astype(float)


def _rot(deg: float) -> np.ndarray:
    r = np.deg2rad(deg)
    c, s = np.cos(r), np.sin(r)
    return np.array([[c, -s], [s, c]])


def _shifts_from_field(positions, theta_deg, t_xy, rng=None, noise=0.0):
    """Per-well (dy, dx) sampling displacement(p) = (R-I)(p-c) + t."""
    c = positions.mean(axis=0)
    q = positions - c
    disp = q @ _rot(theta_deg).T - q + np.asarray(t_xy, float)  # (R-I)q + t, in xy
    if noise and rng is not None:
        disp = disp + rng.normal(scale=noise, size=disp.shape)
    return disp[:, ::-1].copy()  # xy -> (dy, dx)


def test_fit_recovers_known_transform():
    rng = np.random.default_rng(0)
    pos = _grid()
    shifts = _shifts_from_field(pos, theta_deg=0.4, t_xy=(30.0, -20.0), rng=rng, noise=2.0)
    ev = fit_plate_transform(pos, shifts)
    assert ev is not None
    assert abs(ev.theta_deg - 0.4) < 0.05
    assert abs(ev.tx - 30.0) < 1.5 and abs(ev.ty - (-20.0)) < 1.5
    assert ev.rms_px < 4.0  # ~ noise sigma
    # offset reproduces each confident well's shift
    pred = np.array([plate_offset_for_well(ev, p) for p in pos])
    assert np.median(np.linalg.norm(pred - shifts, axis=1)) < 3.0


def test_outlier_rejection():
    rng = np.random.default_rng(1)
    pos = _grid()
    shifts = _shifts_from_field(pos, theta_deg=0.4, t_xy=(30.0, -20.0), rng=rng, noise=2.0)
    # inject 15 garbage wells
    bad = rng.choice(len(pos), size=15, replace=False)
    shifts[bad] = rng.uniform(-800, 800, size=(15, 2))
    ev = fit_plate_transform(pos, shifts)
    assert ev is not None
    assert abs(ev.theta_deg - 0.4) < 0.05  # garbage excluded, clean recovery
    assert abs(ev.tx - 30.0) < 2.0 and abs(ev.ty - (-20.0)) < 2.0
    assert ev.n_inliers >= len(pos) - 20  # the 15 garbage dropped


def test_weak_well_rescue():
    rng = np.random.default_rng(2)
    pos = _grid()
    shifts = _shifts_from_field(pos, theta_deg=0.4, t_xy=(30.0, -20.0), rng=rng, noise=2.0)
    post = np.full(len(pos), 0.15)
    weak = rng.choice(len(pos), size=20, replace=False)
    post[weak] = 0.0  # below the 0.07 gate -> excluded from the fit
    ev = fit_plate_transform(pos, shifts, post_corr=post, qc_gate=0.07)
    assert ev is not None and ev.n_confident == len(pos) - 20
    # predict the withheld wells' true shift from the fit alone
    truth = _shifts_from_field(pos, theta_deg=0.4, t_xy=(30.0, -20.0))  # noiseless ground truth
    pred = np.array([plate_offset_for_well(ev, pos[i]) for i in weak])
    assert np.max(np.linalg.norm(pred - truth[weak], axis=1)) < 3.0


def test_event_detection_finds_coherent_structured_day():
    rng = np.random.default_rng(3)
    pos = _grid()
    n = len(pos)
    days = [8, 12, 16, 20, 25]
    S = np.zeros((len(days), n, 2))
    plate = _shifts_from_field(pos, theta_deg=2.0, t_xy=(400.0, 300.0))  # large + structured
    for t in range(1, len(days)):
        if days[t] == 20:  # the remount
            S[t] = S[t - 1] + plate
        else:
            S[t] = S[t - 1] + rng.uniform(-40, 40, size=(n, 2))  # scattered drift
    assert detect_plate_events(days, S, pos) == [20]
    # add a second event
    S2 = S.copy()
    S2[4] = S2[3] + plate
    assert detect_plate_events(days, S2, pos) == [20, 25]


def test_no_event_is_noop():
    rng = np.random.default_rng(4)
    pos = _grid()
    days = [8, 12, 16, 20, 25]
    S = np.zeros((len(days), len(pos), 2))
    for t in range(1, len(days)):
        S[t] = S[t - 1] + rng.uniform(-40, 40, size=(len(pos), 2))  # only per-well drift
    assert detect_plate_events(days, S, pos) == []


def test_sign_convention_reduces_shift():
    rng = np.random.default_rng(5)
    # reference image with structure
    y, x = np.mgrid[:160, :160]
    ref = np.zeros((160, 160), np.float32)
    for cy, cx in [(50, 60), (100, 110), (120, 40)]:
        ref += np.exp(-(((y - cy) ** 2 + (x - cx) ** 2) / (2 * 9.0**2)))
    ref += 0.02 * rng.normal(size=ref.shape)
    ddy, ddx = 12.0, -9.0
    remounted = apply_shift(ref, ddy, ddx)  # the plate physically shifted content
    corr_shift = (-ddy, -ddx)  # what registration would recover to realign
    pos = _grid()
    shifts = np.tile(corr_shift, (len(pos), 1))  # uniform plate translation
    ev = fit_plate_transform(pos, shifts)
    assert ev is not None
    off = plate_offset_for_well(ev, pos[0])
    corrected = apply_shift(remounted, *off)
    assert correlation(ref, corrected) > correlation(ref, remounted)
