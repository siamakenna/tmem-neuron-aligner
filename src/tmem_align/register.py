from __future__ import annotations

from pathlib import Path

import numpy as np
from scipy.ndimage import shift as ndi_shift
from skimage.registration import phase_cross_correlation

from .io import normalize_to_2d, read_image, write_ome_tiff
from .registration_qc import robust_registration_image


def register_translation(
    reference: np.ndarray,
    moving: np.ndarray,
    upsample_factor: int = 10,
    max_shift_pixels: float | None = None,
    robust_preprocess: bool = True,
    mask_percentile: float | None = None,
) -> tuple[np.ndarray, tuple[float, float], float]:
    """Estimate the (dy, dx) translation aligning ``moving`` onto ``reference``.

    mask_percentile: if set, run *masked* phase cross-correlation that ignores background
    below that intensity percentile so the sparse fluorescent foreground drives the peak.
    This is the recommended path for sparse-neuron frames; do NOT combine it with
    robust_preprocess — the clip+blur smears the point-like signal and makes the peak lock
    onto image edges/illumination (see docs). Masked correlation is integer-pixel
    (upsample_factor is ignored) and returns error=nan.
    """
    ref2d = normalize_to_2d(reference)
    mov2d = normalize_to_2d(moving)
    if robust_preprocess:
        ref2d = robust_registration_image(ref2d)
        mov2d = robust_registration_image(mov2d)
    if mask_percentile is not None:
        ref2d = np.asarray(ref2d, dtype=np.float32)
        mov2d = np.asarray(mov2d, dtype=np.float32)
        ref_mask = ref2d > np.percentile(ref2d, mask_percentile)
        mov_mask = mov2d > np.percentile(mov2d, mask_percentile)
        result = phase_cross_correlation(
            ref2d, mov2d, reference_mask=ref_mask, moving_mask=mov_mask
        )
        # masked variant returns just the shift (older skimage) or a 3-tuple (newer)
        shift = np.asarray(result[0] if isinstance(result, tuple) else result).ravel()
        error = float("nan")
    else:
        shift, error, _ = phase_cross_correlation(ref2d, mov2d, upsample_factor=upsample_factor)
    dy, dx = float(shift[0]), float(shift[1])
    if max_shift_pixels is not None and (abs(dy) > max_shift_pixels or abs(dx) > max_shift_pixels):
        raise ValueError(f"Estimated shift {(dy, dx)} exceeds max_shift_pixels={max_shift_pixels}")
    registered = apply_shift(moving, dy, dx)
    return registered, (dy, dx), float(error)


def apply_shift(image: np.ndarray, dy: float, dx: float) -> np.ndarray:
    arr = np.asarray(image)
    if arr.ndim == 2:
        shift_vec = (dy, dx)
    else:
        shift_vec = (0,) * (arr.ndim - 2) + (dy, dx)
    return ndi_shift(arr, shift=shift_vec, order=3, mode="constant", cval=0).astype(arr.dtype)


def register_file_to_reference(
    reference_path: str | Path,
    moving_path: str | Path,
    output_path: str | Path,
    upsample_factor: int = 10,
    max_shift_pixels: float | None = None,
    robust_preprocess: bool = True,
) -> tuple[Path, tuple[float, float], float]:
    reference = read_image(reference_path)
    moving = read_image(moving_path)
    registered, shift, error = register_translation(
        reference, moving, upsample_factor, max_shift_pixels, robust_preprocess
    )
    write_ome_tiff(output_path, registered, axes=_guess_axes(registered.ndim))
    return Path(output_path), shift, error


def _guess_axes(ndim: int) -> str:
    return {2: "YX", 3: "CYX", 4: "TCYX", 5: "TCZYX"}.get(ndim, "YX")
