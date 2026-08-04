from __future__ import annotations

import numpy as np
from scipy.ndimage import gaussian_filter

DEFAULT_OVERLAP_THRESHOLD = 0.5
DEFAULT_SHIFT_FRACTION = 0.5
DEFAULT_LARGE_SHIFT_PX = 500.0
# ponytail: whole-frame Pearson on sparse fluorescence is low even when aligned
# (~0.09 good vs ~0.004 garbage). 0.02 separates them with margin; recalibrate per
# assay/channel if legitimate low-texture days get flagged.
DEFAULT_MIN_POST_CORRELATION = 0.02


def robust_registration_image(frame: np.ndarray) -> np.ndarray:
    """Percentile-clip and Gaussian-blur a frame for registration."""
    image = np.asarray(frame, dtype=np.float32)
    lo, hi = np.percentile(image, [5, 99])
    if hi <= lo:
        return image
    image = np.clip((image - lo) / (hi - lo), 0, 1)
    return gaussian_filter(image, sigma=1.0)


def overlap_fraction(shape: tuple[int, int], shift: tuple[float, float]) -> float:
    """Fraction of image area retained after a (dy, dx) shift."""
    height, width = shape
    dy, dx = shift
    overlap_h = max(0.0, height - abs(dy))
    overlap_w = max(0.0, width - abs(dx))
    return float((overlap_h * overlap_w) / (height * width))


def correlation(a: np.ndarray, b: np.ndarray) -> float:
    """Pearson correlation between two arrays (flattened)."""
    av = np.asarray(a, dtype=np.float32).ravel()
    bv = np.asarray(b, dtype=np.float32).ravel()
    if av.std() == 0 or bv.std() == 0:
        return 0.0
    return float(np.corrcoef(av, bv)[0, 1])


def common_overlap_crop(
    shape: tuple[int, int],
    shifts: list[tuple[float, float]],
    *,
    robust: bool = False,
    clip_percentile: float = 90.0,
) -> dict[str, int]:
    """Bounding box of the common overlap region across all shifts.

    If robust=True, clips each shift component at clip_percentile of the
    absolute shift distribution before computing the intersection.  This
    prevents a single large stage jump from shrinking the crop for all other
    timepoints.  Frames with shifts beyond the clip are still in the registered
    stack; their out-of-bound pixels are zero-filled by apply_shift.
    """
    height, width = shape
    dys = [dy for dy, _ in shifts]
    dxs = [dx for _, dx in shifts]

    if robust and len(shifts) > 2:
        dy_cap = float(np.percentile(np.abs(dys), clip_percentile))
        dx_cap = float(np.percentile(np.abs(dxs), clip_percentile))
        dys = [float(np.clip(dy, -dy_cap, dy_cap)) for dy in dys]
        dxs = [float(np.clip(dx, -dx_cap, dx_cap)) for dx in dxs]

    top = max(int(np.ceil(max(dy, 0))) for dy in dys)
    bottom = min(height + int(np.floor(min(dy, 0))) for dy in dys)
    left = max(int(np.ceil(max(dx, 0))) for dx in dxs)
    right = min(width + int(np.floor(min(dx, 0))) for dx in dxs)
    if top >= bottom or left >= right:
        return {"y_start": 0, "y_stop": height, "x_start": 0, "x_stop": width}
    return {"y_start": top, "y_stop": bottom, "x_start": left, "x_stop": right}


def crop_tcyx(stack: np.ndarray, crop: dict[str, int]) -> np.ndarray:
    """Apply a common-overlap crop dict to a TCYX stack."""
    return stack[:, :, crop["y_start"] : crop["y_stop"], crop["x_start"] : crop["x_stop"]]


def classify_registration_qc(
    overlap: float,
    dy: float,
    dx: float,
    height: int,
    width: int,
    *,
    overlap_threshold: float = DEFAULT_OVERLAP_THRESHOLD,
    shift_fraction: float = DEFAULT_SHIFT_FRACTION,
    large_shift_px: float = DEFAULT_LARGE_SHIFT_PX,
    post_correlation: float | None = None,
    min_post_correlation: float = DEFAULT_MIN_POST_CORRELATION,
) -> dict[str, bool]:
    """Classify a registration result as pass/fail and flag large shifts.

    If ``post_correlation`` is provided, the result also fails when the post-registration
    correlation is below ``min_post_correlation`` — this catches spurious shifts that keep a
    high overlap but have no real alignment peak (the failure mode that let ~all rows pass
    before). Pass ``None`` (default) to skip the correlation gate.
    """
    qc_pass = bool(
        overlap > overlap_threshold
        and abs(dy) < height * shift_fraction
        and abs(dx) < width * shift_fraction
    )
    if post_correlation is not None and not (post_correlation >= min_post_correlation):
        qc_pass = False
    large_shift = bool(abs(dy) > large_shift_px or abs(dx) > large_shift_px)
    return {"qc_pass": qc_pass, "large_shift": large_shift}
