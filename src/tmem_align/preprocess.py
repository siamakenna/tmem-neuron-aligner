"""Illumination correction and flatfield preprocessing.

Adapted from BrieFlow's CellProfiler-based IC approach (Singh et al. 2014).
Runs BEFORE registration to normalize illumination artifacts across tiles/wells.

Correction model: ``corrected = (raw - darkfield) / flatfield``. The whole
numerical pipeline (IC + background subtraction) stays in float and quantizes to
uint16 exactly once, at the very end, using rounding (not truncation).
"""

from __future__ import annotations

import random
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from pathlib import Path

import numpy as np
from scipy.ndimage import gaussian_filter
from skimage.restoration import ball_kernel, rolling_ball
from skimage.transform import rescale, resize

from tmem_align.io import find_images, normalize_to_2d, read_image


# ---------------------------------------------------------------------------
# IC field calculation (per-well or per-plate)
# ---------------------------------------------------------------------------


def calculate_ic_field(
    images: list[np.ndarray] | list[str | Path],
    smooth: int | None = None,
    rescale_field: bool = True,
    sample_fraction: float = 1.0,
    channel: int | None = None,
    n_workers: int = 4,
    seed: int | None = 0,
    estimate_darkfield: bool = False,
) -> np.ndarray | tuple[np.ndarray, float]:
    """Calculate an illumination correction field from a collection of images.

    Computes the pixelwise MEDIAN across the (sampled) images per channel
    (robust to bright-cell outliers), applies Gaussian smoothing, then optionally
    rescales the field so it is centered on 1 (corrects in both directions).

    For multi-channel images (CYX), loads each image once and computes each
    channel's median independently. File-based images are loaded in parallel
    using threads.

    Args:
        images: List of 2D/3D image arrays or file paths.
        smooth: Gaussian sigma for smoothing the field. Defaults to ~1/40 of the
            image's short side.
        rescale_field: If True, normalize the field by its mean (centered on 1).
        sample_fraction: Fraction of images to use (randomly sampled). Default 1.0.
        channel: If set, extract this channel from multi-channel images before
            computing the IC field (returns 2D). If None and images are
            multi-channel, computes per-channel IC fields (returns CYX).
        n_workers: Thread pool size for parallel file loading. Default 4.
        seed: RNG seed for reproducible sampling. Default 0 (reproducible).
            None falls back to unseeded sampling.
        estimate_darkfield: If True, also estimate a scalar camera-offset
            darkfield and return ``(flatfield, darkfield)``. Default False
            returns only the flatfield array (backward compatible).

    Returns:
        IC field array — 2D (YX) or 3D (CYX) depending on input/channel arg.
        If ``estimate_darkfield`` is True, returns ``(field, darkfield_scalar)``.
    """
    if not images:
        raise ValueError("No images provided for IC field calculation")

    images = list(images)
    if sample_fraction < 1.0:
        k = max(1, int(len(images) * sample_fraction))
        rng = random.Random(seed) if seed is not None else random.Random()
        images = rng.sample(images, k)

    first = _load_image(images[0])
    # ponytail: median needs the sampled stack in RAM; sample_fraction (default
    # 0.25 at plate level) bounds this. For 2868x2868 uint16 frames the ceiling
    # is ~16 MB/image * n_sampled; process one channel at a time to cap the
    # float64 temporary. Switch to a streaming/quantile estimator if it blows up.
    loaded = [first] + list(_iter_images(images[1:], n_workers))

    multichannel = first.ndim == 3 and channel is None
    if multichannel:
        median_channels = [
            np.median(np.stack([img[c] for img in loaded], axis=0).astype(np.float64), axis=0)
            for c in range(first.shape[0])
        ]
        median_field = np.stack(median_channels, axis=0)
        field = _smooth_and_rescale_multichannel(median_field, smooth, rescale_field)
    else:
        stack = np.stack([_extract_channel(img, channel) for img in loaded], axis=0).astype(
            np.float64
        )
        median_field = np.median(stack, axis=0)
        field = _smooth_and_rescale_2d(median_field, smooth, rescale_field)

    if estimate_darkfield:
        return field, _estimate_darkfield(loaded)
    return field


def apply_ic_field(
    image: np.ndarray,
    ic_field: np.ndarray | None,
    darkfield: np.ndarray | float | None = None,
) -> np.ndarray:
    """Apply illumination correction: ``corrected = (image - darkfield) / ic_field``.

    Darkfield is subtracted first (negatives clamped to 0), then divides by the
    flatfield. Both ``ic_field`` and ``darkfield`` may be scalars, 2D, or 3D
    (per-channel CYX) and are broadcast against 2D/3D/4D images:
      - 2D field + 3D image (CYX): broadcasts field across channels
      - 3D field (CYX) + 3D image (CYX): per-channel division
      - 2D field + 4D image (TCYX): broadcasts across T and C
      - 3D field (CYX) + 4D image (TCYX): broadcasts across T

    Returns uint16 corrected image (rounded and clipped to [0, 65535]).
    """
    if ic_field is None and darkfield is None:
        return image
    return _quantize(_apply_ic_field_float(image, ic_field, darkfield))


# ---------------------------------------------------------------------------
# Rolling ball background subtraction
# ---------------------------------------------------------------------------


def subtract_background(
    image: np.ndarray,
    radius: int = 100,
    shrink_factor: int | None = None,
) -> np.ndarray:
    """Rolling ball background subtraction.

    Shrinks the image for speed, computes the rolling ball background, then
    resizes back and subtracts. Works on 2D images; for multi-channel, apply
    per-channel via preprocess_image().

    Returns uint16 background-subtracted image (rounded and clipped).
    """
    img_2d = normalize_to_2d(image) if image.ndim > 2 else image
    return _quantize(_subtract_background_float(img_2d, radius, shrink_factor))


# ---------------------------------------------------------------------------
# High-level preprocessing
# ---------------------------------------------------------------------------


def preprocess_image(
    image: np.ndarray,
    ic_field: np.ndarray | None = None,
    background_radius: int | None = None,
    darkfield: np.ndarray | float | None = None,
) -> np.ndarray:
    """Apply illumination correction and optional background subtraction.

    The numerical pipeline stays in float through IC + background subtraction and
    quantizes to uint16 exactly once at the end (rounding, not truncation), so
    chaining does not double-floor. Processes each channel independently for
    multi-channel images.

    Args:
        image: Input image (2D, 3D CYX, or 4D TCYX).
        ic_field: Illumination correction field (2D/CYX). None to skip IC.
        background_radius: Rolling ball radius. None to skip background subtraction.
        darkfield: Camera-offset darkfield (scalar or 2D/CYX). None to skip.

    Returns:
        Preprocessed uint16 image.
    """
    if ic_field is None and darkfield is None and background_radius is None:
        return image

    if ic_field is not None or darkfield is not None:
        result = _apply_ic_field_float(image, ic_field, darkfield)
    else:
        result = np.asarray(image, dtype=np.float64)

    if background_radius is not None:
        result = _background_float(result, background_radius)

    return _quantize(result)


def calculate_ic_field_for_well(
    image_folder: str | Path,
    sample_fraction: float = 1.0,
    smooth: int | None = None,
    seed: int | None = 0,
) -> np.ndarray:
    """Calculate IC field from all images in a well folder.

    Convenience wrapper: finds all TIFF/ND2 images in folder, loads them,
    calculates the IC field.
    """
    paths = find_images(image_folder)
    if not paths:
        raise FileNotFoundError(f"No images found in {image_folder}")
    return calculate_ic_field(paths, smooth=smooth, sample_fraction=sample_fraction, seed=seed)


def calculate_ic_field_for_plate(
    plate_folder: str | Path,
    well_pattern: str = "*",
    sample_fraction: float = 0.25,
    smooth: int | None = None,
    seed: int | None = 0,
) -> np.ndarray:
    """Calculate IC field from images across an entire plate.

    Collects images from all well subfolders matching well_pattern, samples
    a fraction, and computes a single plate-level IC field.
    """
    plate_path = Path(plate_folder)
    all_images = []
    for well_dir in sorted(plate_path.glob(well_pattern)):
        if well_dir.is_dir():
            all_images.extend(find_images(well_dir))

    if not all_images:
        raise FileNotFoundError(f"No images found in {plate_folder}/{well_pattern}")

    # ponytail: default 25% sampling for plate-level (many images)
    return calculate_ic_field(all_images, smooth=smooth, sample_fraction=sample_fraction, seed=seed)


# ---------------------------------------------------------------------------
# Timepoint-aware IC (one IC field per imaging session)
# ---------------------------------------------------------------------------


def _compute_one_timepoint(args):
    """Worker for parallel IC field computation (must be top-level for pickling)."""
    tp_dir, smooth, sample_fraction, seed = args
    images = find_images(tp_dir)
    if not images:
        return None
    return tp_dir.name, calculate_ic_field(
        images, smooth=smooth, sample_fraction=sample_fraction, seed=seed
    )


def calculate_ic_fields_by_timepoint(
    plate_dir: str | Path,
    sample_fraction: float = 0.25,
    smooth: int | None = None,
    n_workers: int | None = None,
    seed: int | None = 0,
) -> dict[str, np.ndarray]:
    """Calculate per-timepoint IC fields for a plate.

    Expects plate_dir to contain subdirectories, one per timepoint/imaging
    session. Each subdir should contain the raw images for that session.
    Returns a dict keyed by timepoint directory name.

    Args:
        plate_dir: Top-level plate directory containing timepoint subdirs.
        sample_fraction: Fraction of images to sample per timepoint.
        smooth: Gaussian sigma for smoothing. None for auto.
        n_workers: Parallel processes for timepoints. None = number of timepoints.
        seed: RNG seed for reproducible sampling. Default 0.

    Returns:
        Dict mapping timepoint dirname → IC field array (2D or CYX).
    """
    plate_path = Path(plate_dir)
    timepoint_dirs = sorted(
        d for d in plate_path.iterdir() if d.is_dir() and not d.name.startswith(".")
    )
    if not timepoint_dirs:
        raise FileNotFoundError(f"No timepoint subdirectories in {plate_dir}")

    if n_workers is None:
        n_workers = len(timepoint_dirs)

    work = [(d, smooth, sample_fraction, seed) for d in timepoint_dirs]

    if n_workers <= 1:
        results = [_compute_one_timepoint(w) for w in work]
    else:
        with ProcessPoolExecutor(max_workers=n_workers) as pool:
            results = list(pool.map(_compute_one_timepoint, work))

    ic_fields = {name: ic for name, ic in (r for r in results if r is not None)}

    if not ic_fields:
        raise FileNotFoundError(f"No images found in any subdirectory of {plate_dir}")

    return ic_fields


def preprocess_with_lookup(
    image_path: str | Path,
    ic_fields: dict[str, np.ndarray],
    background_radius: int | None = None,
    darkfield: np.ndarray | float | None = None,
) -> np.ndarray:
    """Load an image and preprocess with auto-selected IC field.

    Resolves the correct IC field by matching the image's parent directory
    name against the ic_fields dict keys (timepoint directory names).

    Args:
        image_path: Path to the image file.
        ic_fields: Dict from calculate_ic_fields_by_timepoint().
        background_radius: Rolling ball radius, or None to skip.
        darkfield: Camera-offset darkfield (scalar or 2D/CYX), or None to skip.

    Returns:
        Preprocessed uint16 image.

    Raises:
        KeyError: If no IC field found for the image's timepoint.
    """
    image_path = Path(image_path)
    image = read_image(str(image_path))

    # Walk up parents to find a matching timepoint key
    ic_field = _resolve_ic_field(image_path, ic_fields)

    return preprocess_image(
        image,
        ic_field=ic_field,
        background_radius=background_radius,
        darkfield=darkfield,
    )


def _resolve_ic_field(image_path: Path, ic_fields: dict[str, np.ndarray]) -> np.ndarray:
    """Find the IC field matching an image path's timepoint directory."""
    path = Path(image_path)
    for parent in [path.parent] + list(path.parents):
        if parent.name in ic_fields:
            return ic_fields[parent.name]
    raise KeyError(
        f"No IC field for image {image_path}. "
        f"Parent dirs checked against keys: {list(ic_fields.keys())}"
    )


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _quantize(arr: np.ndarray) -> np.ndarray:
    """Round to nearest integer and clip to uint16 range. The ONLY quantization step."""
    return np.clip(np.rint(arr), 0, 65535).astype(np.uint16)


def _broadcast_like(arr: np.ndarray, img: np.ndarray) -> np.ndarray:
    """Reshape a 2D/3D field/darkfield so it broadcasts against ``img``.

    Scalars (0-d) broadcast as-is; mismatched spatial dims are left for numpy to
    raise on the arithmetic.
    """
    if arr.ndim == 0 or arr.ndim == img.ndim:
        return arr
    if arr.ndim == 2:
        while arr.ndim < img.ndim:
            arr = arr[np.newaxis]
        return arr
    if arr.ndim == 3 and img.ndim == 4:
        return arr[np.newaxis]
    return arr


def _apply_ic_field_float(
    image: np.ndarray,
    ic_field: np.ndarray | None,
    darkfield: np.ndarray | float | None,
) -> np.ndarray:
    """Float IC core: ``(image - darkfield) / ic_field`` with no quantization."""
    img = np.asarray(image, dtype=np.float64)

    if darkfield is not None:
        dark = _broadcast_like(np.asarray(darkfield, dtype=np.float64), img)
        img = np.clip(img - dark, 0, None)

    if ic_field is None:
        return img

    field = np.array(ic_field, dtype=np.float64)  # copy so we don't mutate caller
    field[field == 0] = 1
    field = _broadcast_like(field, img)
    return img / field


def _subtract_background_float(
    image: np.ndarray, radius: int, shrink_factor: int | None
) -> np.ndarray:
    """Float rolling-ball background subtraction on a 2D image (no quantization)."""
    img_f = np.asarray(image, dtype=np.float64)

    if shrink_factor is None:
        if radius <= 10:
            shrink_factor = 1
        elif radius <= 30:
            shrink_factor = 2
        elif radius <= 100:
            shrink_factor = 4
        else:
            shrink_factor = 8

    if shrink_factor > 1:
        small = rescale(img_f, 1.0 / shrink_factor, preserve_range=True)
        kernel = ball_kernel(max(1, radius // shrink_factor), ndim=2)
        bg_small = rolling_ball(small, kernel=kernel)
        bg = resize(bg_small, img_f.shape, preserve_range=True)
    else:
        kernel = ball_kernel(radius, ndim=2)
        bg = rolling_ball(img_f, kernel=kernel)

    bg = np.minimum(bg, img_f)
    return img_f - bg  # >= 0 by construction


def _background_float(arr: np.ndarray, radius: int) -> np.ndarray:
    """Apply float background subtraction per-channel, preserving image ndim."""
    arr = np.asarray(arr, dtype=np.float64)
    if arr.ndim == 2:
        return _subtract_background_float(arr, radius, None)
    if arr.ndim == 3:
        return np.stack(
            [_subtract_background_float(arr[c], radius, None) for c in range(arr.shape[0])],
            axis=0,
        )
    if arr.ndim == 4:
        return np.stack(
            [
                np.stack(
                    [
                        _subtract_background_float(arr[t, c], radius, None)
                        for c in range(arr.shape[1])
                    ],
                    axis=0,
                )
                for t in range(arr.shape[0])
            ],
            axis=0,
        )
    return _subtract_background_float(arr, radius, None)


def _estimate_darkfield(loaded: list[np.ndarray]) -> float:
    """Estimate a scalar camera-offset darkfield.

    ponytail: robust scalar offset = 1st percentile of the per-image minima. This
    is deliberately NOT BaSiC's L1/low-rank darkfield — a constant camera bias
    (~100 ADU for the Prime BSI) is what we actually need. Upgrade to a spatial
    darkfield only if vignetted dark structure shows up in flats.
    """
    mins = [float(np.min(img)) for img in loaded]
    return float(np.percentile(mins, 1))


def _load_image(img) -> np.ndarray:
    """Load an image, whether it's an array or a path."""
    if isinstance(img, (str, Path)):
        return read_image(str(img))
    return np.asarray(img)


def _iter_images(images, n_workers: int):
    """Yield loaded images, using threaded I/O for file paths."""
    is_paths = images and isinstance(images[0], (str, Path))
    if is_paths and n_workers > 1:
        with ThreadPoolExecutor(max_workers=n_workers) as pool:
            yield from pool.map(_load_image, images)
    else:
        for img in images:
            yield _load_image(img)


def _extract_channel(img: np.ndarray, channel: int | None) -> np.ndarray:
    """Extract a single channel from an image, or normalize to 2D."""
    if channel is not None and img.ndim >= 3:
        return img[channel]
    return normalize_to_2d(img)


def _smooth_and_rescale_2d(
    field: np.ndarray, smooth: int | None, rescale_field: bool
) -> np.ndarray:
    """Apply gaussian smoothing and optional rescaling to a 2D IC field."""
    if smooth is None:
        # ponytail: the IC field is a low-frequency illumination profile. Scale
        # sigma to ~1/40 of the short side so it adapts from tiny test frames to
        # full 2868px images, instead of the old formula that was always clamped
        # to 50 (dead code).
        smooth = max(1, min(field.shape[-2], field.shape[-1]) // 40)
    smoothed = gaussian_filter(field.astype(np.float64), sigma=smooth)
    if rescale_field:
        smoothed = _rescale_field(smoothed)
    return smoothed


def _smooth_and_rescale_multichannel(
    field: np.ndarray, smooth: int | None, rescale_field: bool
) -> np.ndarray:
    """Apply smoothing/rescaling independently per channel."""
    return np.stack(
        [_smooth_and_rescale_2d(field[c], smooth, rescale_field) for c in range(field.shape[0])],
        axis=0,
    )


def _rescale_field(field: np.ndarray) -> np.ndarray:
    """Normalize an IC field by its mean so it is centered on 1.

    Dividing by a mean-centered field attenuates the bright center AND amplifies
    genuinely dim/vignetted corners, preserving overall intensity.
    """
    center = float(np.mean(field))
    if center <= 0:
        center = 1.0
    field = field / center
    # ponytail: floor the field at 0.1 so noise in near-zero regions isn't
    # amplified >10x when we divide by it.
    return np.clip(field, 0.1, None)
