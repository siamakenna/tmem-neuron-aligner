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
    *,
    channel_index: int | None = None,
    trace=None,
    trace_prefix: str = "registration",
) -> tuple[np.ndarray, tuple[float, float], float]:
    """Estimate the (dy, dx) translation aligning ``moving`` onto ``reference``.

    mask_percentile: if set, run *masked* phase cross-correlation that ignores background
    below that intensity percentile so the sparse fluorescent foreground drives the peak.
    This is the recommended path for sparse-neuron frames; do NOT combine it with
    robust_preprocess — the clip+blur smears the point-like signal and makes the peak lock
    onto image edges/illumination (see docs). Masked correlation is integer-pixel
    (upsample_factor is ignored) and returns error=nan.
    ``channel_index`` explicitly chooses a CYX alignment plane. The resulting
    transform is applied once to every moving YX plane. None preserves the
    historical normalize_to_2d selection. Optional tracing observes the actual
    algorithm arrays and never supplies transformed pixels back to it.
    """
    from .audit_v1.stage_trace import capture

    ref_array, mov_array = np.asarray(reference), np.asarray(moving)
    if ref_array.shape != mov_array.shape or ref_array.ndim < 2:
        raise ValueError("Registration inputs must have the same nonempty spatial shape")
    if (not ref_array.size or ref_array.dtype.kind not in "buif" or mov_array.dtype.kind not in "buif"
            or not np.isfinite(ref_array).all() or not np.isfinite(mov_array).all()):
        raise ValueError("Registration inputs must contain finite real pixels")
    if (isinstance(upsample_factor, (bool, np.bool_))
            or not isinstance(upsample_factor, (int, np.integer)) or upsample_factor < 1):
        raise ValueError("upsample_factor must be a positive integer")
    if max_shift_pixels is not None and (isinstance(max_shift_pixels, (bool, np.bool_))
            or not np.isfinite(max_shift_pixels) or max_shift_pixels <= 0):
        raise ValueError("max_shift_pixels must be finite and positive")
    if mask_percentile is not None and (isinstance(mask_percentile, (bool, np.bool_))
            or not np.isfinite(mask_percentile) or not 0 <= mask_percentile < 100):
        raise ValueError("mask_percentile must be finite in [0,100)")
    if channel_index is not None:
        if (isinstance(channel_index, (bool, np.bool_))
                or not isinstance(channel_index, (int, np.integer))
                or ref_array.ndim != 3 or not 0 <= channel_index < ref_array.shape[0]):
            raise ValueError("channel_index requires an explicit valid CYX channel")
        ref2d, mov2d = ref_array[channel_index], mov_array[channel_index]
    else:
        ref2d, mov2d = normalize_to_2d(ref_array), normalize_to_2d(mov_array)
    label = "488" if channel_index == 2 else ("unassigned" if channel_index is None else f"C{channel_index}")
    params = dict(upsample_factor=int(upsample_factor), max_shift_pixels=max_shift_pixels,
        robust_preprocess=bool(robust_preprocess), mask_percentile=mask_percentile,
        channel_index=None if channel_index is None else int(channel_index),
        transform_direction="moving_to_reference", shift_order="dy,dx",
        interpolation_order=3, border_mode="constant", fill_value=0)
    def emit(step, array=None, *, parents=(), why, status="executed", details=None):
        return capture(trace, f"{trace_prefix}_{step}", array, channel=label,
            parents=tuple(f"{trace_prefix}_{parent}" for parent in parents), why=why,
            parameters=params, status=status, details=details)
    emit("00_reference", ref2d, why="The explicitly selected plane defines the reference coordinate system.")
    emit("01_moving", mov2d, why="This unshifted plane is the input to transform estimation.")
    if robust_preprocess:
        ref2d = robust_registration_image(ref2d)
        mov2d = robust_registration_image(mov2d)
    emit("02_reference_estimation_input", ref2d, parents=("00_reference",),
         why="Record the exact reference pixels passed to correlation, including optional robust preprocessing.",
         details={"array_role": "normalized_intensity" if robust_preprocess else "intensity"})
    emit("03_moving_estimation_input", mov2d, parents=("01_moving",),
         why="Record the exact moving pixels passed to correlation, including optional robust preprocessing.",
         details={"array_role": "normalized_intensity" if robust_preprocess else "intensity"})
    if mask_percentile is not None:
        ref2d = np.asarray(ref2d, dtype=np.float32)
        mov2d = np.asarray(mov2d, dtype=np.float32)
        ref_mask = ref2d > np.percentile(ref2d, mask_percentile)
        mov_mask = mov2d > np.percentile(mov2d, mask_percentile)
        emit("04_reference_mask", ref_mask, parents=("02_reference_estimation_input",),
             why="Foreground support limits masked correlation to the selected identity plane.")
        emit("05_moving_mask", mov_mask, parents=("03_moving_estimation_input",),
             why="Record which moving pixels contribute to masked correlation.")
        result = phase_cross_correlation(
            ref2d, mov2d, reference_mask=ref_mask, moving_mask=mov_mask
        )
        # masked variant returns just the shift (older skimage) or a 3-tuple (newer)
        shift = np.asarray(result[0] if isinstance(result, tuple) else result).ravel()
        error = float("nan")
    else:
        emit("04_reference_mask", status="skipped", parents=("02_reference_estimation_input",),
             why="Unmasked correlation was explicitly requested; no reference mask was applied.")
        emit("05_moving_mask", status="skipped", parents=("03_moving_estimation_input",),
             why="Unmasked correlation was explicitly requested; no moving mask was applied.")
        shift, error, _ = phase_cross_correlation(ref2d, mov2d, upsample_factor=upsample_factor)
    dy, dx = float(shift[0]), float(shift[1])
    if not np.isfinite([dy, dx]).all():
        emit("06_shift_guard", status="failed", why="An undefined transform cannot align quantitative pixels.")
        raise ValueError("Registration returned a nonfinite shift")
    if max_shift_pixels is not None and (abs(dy) > max_shift_pixels or abs(dx) > max_shift_pixels):
        emit("06_shift_guard", status="failed", why="The estimated transform exceeds the declared maximum displacement.",
             details={"dy": dy, "dx": dx, "max_shift_pixels": max_shift_pixels})
        raise ValueError(f"Estimated shift {(dy, dx)} exceeds max_shift_pixels={max_shift_pixels}")
    registered = apply_shift(moving, dy, dx)
    selected = registered[channel_index] if channel_index is not None else normalize_to_2d(registered)
    emit("06_aligned", selected, parents=("00_reference", "01_moving", "04_reference_mask", "05_moving_mask"),
         why="Apply the single moving-to-reference transform independently to every moving YX plane.",
         details={"dy": dy, "dx": dx, "phase_error": float(error),
                  "masked_phase_error_is_undefined": mask_percentile is not None,
                  "transform_applications_per_output_plane": 1,
                  "nonspatial_axes_interpolated": False})
    if trace is not None:
        support = apply_shift(np.ones(mov2d.shape, dtype=np.uint8), dy, dx).astype(bool)
        emit("07_transformed_support", support, parents=("06_aligned",),
             why="Show transformed image support separately from genuine dark pixels; spline edge accuracy remains limited.",
             details={"dy": dy, "dx": dx, "support_is_not_interpolation_accuracy_validation": True})
    return registered, (dy, dx), float(error)


def apply_shift(image: np.ndarray, dy: float, dx: float) -> np.ndarray:
    """Shift YX planes independently, preserving channel/time independence.

    Cubic spline prefiltering over a full stack can couple rounding across
    nonspatial axes even when those axes have zero displacement.
    """
    arr = np.asarray(image)
    if arr.ndim < 2:
        raise ValueError("apply_shift requires at least two spatial dimensions")
    if arr.ndim == 2:
        return ndi_shift(arr, shift=(dy, dx), order=3, mode="constant", cval=0).astype(arr.dtype)
    shifted = np.empty_like(arr)
    for index in np.ndindex(arr.shape[:-2]):
        shifted[index] = ndi_shift(
            arr[index], shift=(dy, dx), order=3, mode="constant", cval=0
        )
    return shifted


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
