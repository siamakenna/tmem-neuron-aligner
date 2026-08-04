"""Plate-wise remount correction.

At a plate remount, one rigid transform (rotation + translation about the plate centre) is
applied to *every* well at once. This module fits that single global transform from many wells'
per-well shifts — hugely over-determined (3 params from ~100+ wells) — and predicts the
correction for any well, including weak wells that cannot self-register. See
PLATE_REMOUNT_CORRECTION_PLAN.md.

The rigid math (``RigidTransformTurbo``, ``rigid_from_points_ls`` Kabsch fit, ``rms_error``) is
**vendored** (copied, not imported) from
``/Users/pmihack/claire/tmem_2026/align-channels-petrucelli/msrigid/__init__.py`` (lines 41, 271,
320) to keep this package self-contained (numpy + scipy only, no cross-repo dependency).
Convention: ``fixed = R*moving + t``, points are ``(x, y)`` with x→right, y→down (ImageJ).
Pipeline shifts are ``(dy, dx)``; we convert to/from ``(x, y)`` at the boundary.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np

# --- vendored rigid math (msrigid) ------------------------------------------------------------


@dataclass
class RigidTransformTurbo:
    """Rigid transform mapping moving→fixed (``fixed = R*moving + t``).

    Vendored from align-channels-petrucelli/msrigid/__init__.py:41 (minimal subset).
    """

    m00: float
    m01: float
    m02: float
    m10: float
    m11: float
    m12: float

    def as_matrix3x3(self) -> np.ndarray:
        return np.array(
            [[self.m00, self.m01, self.m02], [self.m10, self.m11, self.m12], [0.0, 0.0, 1.0]],
            dtype=np.float64,
        )

    @property
    def theta_rad(self) -> float:
        return math.atan2(self.m10, self.m00)

    @property
    def theta_deg(self) -> float:
        return math.degrees(self.theta_rad)

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "matrix": [[self.m00, self.m01, self.m02], [self.m10, self.m11, self.m12]],
            "theta_deg": self.theta_deg,
            "convention": "fixed = R*moving + t",
        }


def rigid_from_points_ls(moving_pts, fixed_pts) -> RigidTransformTurbo:
    """Least-squares (Kabsch/SVD) rigid transform, no scaling; maps moving→fixed. Needs ≥3 points.

    Vendored from msrigid/__init__.py:271 (reflection-guarded).
    """
    A = np.asarray(moving_pts, dtype=np.float64)
    B = np.asarray(fixed_pts, dtype=np.float64)
    if A.shape[0] < 3 or B.shape[0] < 3:
        raise ValueError("rigid fit requires >=3 shared points")
    ca = A.mean(axis=0)
    cb = B.mean(axis=0)
    H = (A - ca).T @ (B - cb)
    U, _, Vt = np.linalg.svd(H)
    R = Vt.T @ U.T
    if np.linalg.det(R) < 0:
        Vt[-1, :] *= -1.0
        R = Vt.T @ U.T
    t = cb - (R @ ca)
    return RigidTransformTurbo(
        float(R[0, 0]), float(R[0, 1]), float(t[0]), float(R[1, 0]), float(R[1, 1]), float(t[1])
    )


def rms_error(rt: RigidTransformTurbo, moving_pts, fixed_pts) -> float:
    """RMS residual of ``rt`` on correspondences. Vendored from msrigid/__init__.py:320."""
    M = np.asarray(moving_pts, dtype=np.float64)
    F = np.asarray(fixed_pts, dtype=np.float64)
    R = np.array([[rt.m00, rt.m01], [rt.m10, rt.m11]], dtype=np.float64)
    t = np.array([rt.m02, rt.m12], dtype=np.float64)
    resid = F - (M @ R.T + t)
    return float(np.sqrt(np.mean(np.sum(resid * resid, axis=1))))


# --- plate transform --------------------------------------------------------------------------


@dataclass
class PlateEvent:
    """A fitted plate-remount transform for one event day."""

    day: Any
    transform: RigidTransformTurbo
    center: tuple[float, float]
    theta_deg: float
    tx: float
    ty: float
    n_confident: int
    n_inliers: int
    rms_px: float

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "day": self.day,
            "center": list(self.center),
            "theta_deg": self.theta_deg,
            "tx": self.tx,
            "ty": self.ty,
            "n_confident": self.n_confident,
            "n_inliers": self.n_inliers,
            "rms_px": self.rms_px,
            "transform": self.transform.to_jsonable(),
        }


def _dydx_to_xy(shifts_dydx: np.ndarray) -> np.ndarray:
    """(dy, dx) → (x, y)."""
    s = np.asarray(shifts_dydx, dtype=np.float64)
    return s[:, ::-1].copy()


def _apply_rigid(rt: RigidTransformTurbo, q: np.ndarray) -> np.ndarray:
    R = np.array([[rt.m00, rt.m01], [rt.m10, rt.m11]], dtype=np.float64)
    t = np.array([rt.m02, rt.m12], dtype=np.float64)
    return q @ R.T + t


def _displacement(rt: RigidTransformTurbo, q: np.ndarray) -> np.ndarray:
    """Per-point shift the transform implies: ``G(q) - q`` (xy), where q = position - centre."""
    return _apply_rigid(rt, q) - q


def fit_plate_transform(
    positions,
    shifts,
    day: Any = None,
    *,
    post_corr=None,
    qc_gate: float = 0.07,
    plate_jump_max: float | None = None,
    mad_k: float = 3.0,
    min_inliers: int = 10,
) -> PlateEvent | None:
    """Fit one global rigid transform from per-well (position, shift) samples.

    ``positions``: (n, 2) well plate XY in **pixels** ``(x, y)``. ``shifts``: (n, 2) per-well
    ``(dy, dx)`` correction shifts in pixels. Confident wells (``post_corr >= qc_gate`` and
    ``|shift| < plate_jump_max``) drive the fit; one-step robust MAD outlier rejection then a
    refit on inliers. Returns ``None`` if too few confident/inlier wells.

    The per-well shift is a point sample of the global field ``displacement(p) = (R-I)(p-c) + t``,
    so we fit correspondences ``moving = q``, ``fixed = q + s_xy`` (q = p - c) → ``fixed = R*q + t``.
    """
    p = np.asarray(positions, dtype=np.float64)
    shifts_a = np.asarray(shifts, dtype=np.float64)
    s_xy = _dydx_to_xy(shifts_a)
    n = p.shape[0]

    conf = np.ones(n, dtype=bool)
    if post_corr is not None:
        conf &= np.asarray(post_corr, dtype=np.float64) >= qc_gate
    if plate_jump_max is not None:
        conf &= np.hypot(shifts_a[:, 0], shifts_a[:, 1]) < plate_jump_max
    if conf.sum() < 3:
        return None

    c = p.mean(axis=0)  # centre from all wells (stable)
    q = p - c
    q_conf = q[conf]
    fixed = q_conf + s_xy[conf]

    rt = rigid_from_points_ls(q_conf, fixed)
    resid = np.linalg.norm(_displacement(rt, q_conf) - s_xy[conf], axis=1)
    med = float(np.median(resid))
    mad = float(np.median(np.abs(resid - med)))
    thresh = med + mad_k * (mad if mad > 1e-9 else 1.0)
    inl = resid <= thresh
    if 3 <= inl.sum() < len(q_conf):
        rt = rigid_from_points_ls(q_conf[inl], fixed[inl])
    else:
        inl = np.ones(len(q_conf), dtype=bool)
    if inl.sum() < min_inliers:
        return None

    rms = rms_error(rt, q_conf[inl], fixed[inl])
    return PlateEvent(
        day=day,
        transform=rt,
        center=(float(c[0]), float(c[1])),
        theta_deg=rt.theta_deg,
        tx=float(rt.m02),
        ty=float(rt.m12),
        n_confident=int(conf.sum()),
        n_inliers=int(inl.sum()),
        rms_px=rms,
    )


def plate_offset_for_well(event: PlateEvent, position) -> tuple[float, float]:
    """Correction shift ``(dy, dx)`` the plate transform implies for a well at ``position`` (xy px).

    For a confident well this reproduces its measured shift; for a weak well it *predicts* the
    shift it could not compute itself (the rescue). Directly usable with ``register.apply_shift``.
    """
    q = np.asarray(position, dtype=np.float64) - np.asarray(event.center, dtype=np.float64)
    disp = _displacement(event.transform, q.reshape(1, 2))[0]  # (x, y)
    return (float(disp[1]), float(disp[0]))  # (dy, dx)


def _linear_r2(q: np.ndarray, ds: np.ndarray) -> float:
    """R² of regressing per-well increment ``ds`` (n,2) on position ``q`` (n,2) — the
    rotation-about-centre / column-structure signature of a plate event."""
    X = np.column_stack([q, np.ones(len(q))])
    coef, *_ = np.linalg.lstsq(X, ds, rcond=None)
    pred = X @ coef
    ss_res = float(np.sum((ds - pred) ** 2))
    ss_tot = float(np.sum((ds - ds.mean(axis=0)) ** 2))
    return 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0


def detect_plate_events(
    days,
    shift_stack,
    positions,
    *,
    jump_thresh: float = 150.0,
    min_fraction: float = 0.5,
    min_r2: float = 0.7,
    min_wells: int = 20,
) -> list:
    """Find day(s) where wells jump coherently with position structure (a plate remount).

    ``days``: length-T sequence. ``shift_stack``: (T, n, 2) per-day per-well net ``(dy, dx)``.
    ``positions``: (n, 2) well XY. Tests the day-to-day increment so accumulated drift doesn't
    mask the jump. A day qualifies iff the coherent fraction ≥ ``min_fraction`` **and** the linear
    fit of the increment on position has R² ≥ ``min_r2``. Returns the list of event days (possibly
    empty = no-op, safe default).

    The column-structure R² is only meaningful over many wells — a 3-parameter linear fit
    saturates (R²→1) on a handful of points, so fewer than ``min_wells`` returns no events.
    """
    S = np.asarray(shift_stack, dtype=np.float64)
    p = np.asarray(positions, dtype=np.float64)
    if len(p) < min_wells:
        return []
    q = p - p.mean(axis=0)
    events = []
    for t in range(1, len(days)):
        ds = S[t] - S[t - 1]  # (n, 2) increment
        frac = float(np.mean(np.hypot(ds[:, 0], ds[:, 1]) > jump_thresh))
        if frac >= min_fraction and _linear_r2(q, ds) >= min_r2:
            events.append(days[t])
    return events
