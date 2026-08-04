from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy import ndimage as ndi
from skimage import filters, measure, morphology


@dataclass(frozen=True)
class MCherryMetricConfig:
    background_percentile: float = 20.0
    foreground_percentile: float = 65.0
    puncta_sigma_small: float = 1.0
    puncta_sigma_large: float = 3.0
    puncta_mad_multiplier: float = 4.0
    min_puncta_area: int = 6
    max_puncta_area_fraction: float = 0.05
    foreground_min_area: int = 128
    foreground_dilation: int = 2
    epsilon: float = 1e-6


def quantify_mcherry_timeseries(
    mcherry_stack: np.ndarray,
    *,
    mask_stack: np.ndarray | None = None,
    metadata_rows: list[dict[str, Any]] | None = None,
    config: MCherryMetricConfig | None = None,
    mask_source: str = "stable_channel",
) -> pd.DataFrame:
    """Quantify punctate and diffuse mCherry signal in a TYX stack.

    The metric is a screening readout for punctate-to-diffuse reporter redistribution. It is not
    proof of lysosomal rupture without orthogonal rupture markers.
    """
    cfg = config or MCherryMetricConfig()
    mcherry = _as_tyx(mcherry_stack)
    masks = None if mask_stack is None else _as_tyx(mask_stack)
    if masks is not None and masks.shape != mcherry.shape:
        raise ValueError(f"mask_stack shape {masks.shape} does not match mCherry shape {mcherry.shape}")

    rows: list[dict[str, Any]] = []
    for time_index, frame in enumerate(mcherry):
        mask_frame = None if masks is None else masks[time_index]
        row = quantify_mcherry_frame(
            frame,
            stable_frame=mask_frame,
            time_index=time_index,
            config=cfg,
            mask_source=mask_source if mask_frame is not None else "mcherry_fallback",
        )
        if metadata_rows:
            row = {**metadata_rows[time_index], **row}
        rows.append(row)
    return pd.DataFrame(rows)


def quantify_mcherry_frame(
    mcherry_frame: np.ndarray,
    *,
    stable_frame: np.ndarray | None = None,
    time_index: int = 0,
    config: MCherryMetricConfig | None = None,
    mask_source: str = "stable_channel",
) -> dict[str, Any]:
    cfg = config or MCherryMetricConfig()
    corrected = background_subtract(mcherry_frame, percentile=cfg.background_percentile)

    if stable_frame is not None:
        foreground = foreground_mask(
            stable_frame,
            percentile=cfg.foreground_percentile,
            min_area=cfg.foreground_min_area,
            dilation=cfg.foreground_dilation,
        )
    else:
        foreground = foreground_mask(
            corrected,
            percentile=cfg.foreground_percentile,
            min_area=cfg.foreground_min_area,
            dilation=cfg.foreground_dilation,
        )

    if not foreground.any():
        foreground = corrected > 0
        mask_source = f"{mask_source}_positive_pixels"

    puncta_mask = detect_puncta(corrected, foreground, config=cfg)
    labels = measure.label(puncta_mask)
    props = measure.regionprops(labels, intensity_image=corrected)

    diffuse_mask = foreground & ~puncta_mask
    punctate_integrated = float(corrected[puncta_mask].sum()) if puncta_mask.any() else 0.0
    diffuse_integrated = float(corrected[diffuse_mask].sum()) if diffuse_mask.any() else 0.0
    total_integrated = float(corrected[foreground].sum()) if foreground.any() else 0.0
    foreground_area = int(foreground.sum())

    puncta_areas = [float(prop.area) for prop in props]
    puncta_means = [
        float(prop.intensity_mean if hasattr(prop, "intensity_mean") else prop.mean_intensity)
        for prop in props
    ]
    mean_puncta_intensity = float(np.mean(puncta_means)) if puncta_means else 0.0
    median_puncta_area = float(np.median(puncta_areas)) if puncta_areas else 0.0
    diffuse_mean = float(corrected[diffuse_mask].mean()) if diffuse_mask.any() else 0.0

    diffuse_to_punctate = diffuse_integrated / (punctate_integrated + cfg.epsilon)

    return {
        "time_index": int(time_index),
        "cell_roi_id": "whole_field_foreground",
        "mask_source": mask_source,
        "cell_roi_area": foreground_area,
        "total_mcherry_intensity": total_integrated,
        "diffuse_mcherry_integrated_intensity": diffuse_integrated,
        "diffuse_mcherry_mean_intensity": diffuse_mean,
        "punctate_mcherry_integrated_intensity": punctate_integrated,
        "puncta_count": int(len(props)),
        "puncta_density_per_area": float(len(props) / (foreground_area + cfg.epsilon)),
        "mean_puncta_intensity": mean_puncta_intensity,
        "median_puncta_area": median_puncta_area,
        "diffuse_to_punctate_ratio": float(diffuse_to_punctate),
        "rupture_like_score": float(diffuse_to_punctate),
        "mcherry_metric_interpretation": (
            "screening metric for punctate-to-diffuse reporter redistribution; not rupture proof"
        ),
    }


def background_subtract(frame: np.ndarray, *, percentile: float = 20.0) -> np.ndarray:
    arr = np.asarray(frame, dtype=np.float32)
    background = float(np.percentile(arr, percentile))
    return np.clip(arr - background, 0, None)


def foreground_mask(
    frame: np.ndarray,
    *,
    percentile: float = 65.0,
    min_area: int = 128,
    dilation: int = 2,
) -> np.ndarray:
    corrected = background_subtract(frame, percentile=20.0)
    positive = corrected[corrected > 0]
    if positive.size == 0:
        return np.zeros(corrected.shape, dtype=bool)
    smooth = filters.gaussian(corrected, sigma=2.0, preserve_range=True)
    threshold = float(np.percentile(positive, percentile))
    mask = smooth > threshold
    mask = _remove_small_objects(mask, min_area)
    mask = ndi.binary_fill_holes(mask)
    if dilation > 0:
        mask = morphology.dilation(mask, morphology.disk(dilation))
    return mask.astype(bool)


def detect_puncta(
    corrected_mcherry: np.ndarray,
    foreground: np.ndarray,
    *,
    config: MCherryMetricConfig | None = None,
) -> np.ndarray:
    cfg = config or MCherryMetricConfig()
    if not foreground.any():
        return np.zeros(corrected_mcherry.shape, dtype=bool)

    small = filters.gaussian(corrected_mcherry, sigma=cfg.puncta_sigma_small, preserve_range=True)
    large = filters.gaussian(corrected_mcherry, sigma=cfg.puncta_sigma_large, preserve_range=True)
    dog = np.clip(small - large, 0, None)
    values = dog[foreground]
    median = float(np.median(values))
    mad = float(np.median(np.abs(values - median)))
    robust_sigma = 1.4826 * mad
    high_percentile = float(np.percentile(values, 97.5))
    threshold = max(median + cfg.puncta_mad_multiplier * robust_sigma, high_percentile)
    puncta = (dog > threshold) & foreground
    puncta = _remove_small_objects(puncta, cfg.min_puncta_area)

    max_area = max(cfg.min_puncta_area, int(foreground.sum() * cfg.max_puncta_area_fraction))
    labels = measure.label(puncta)
    keep_ids = [p.label for p in measure.regionprops(labels)
                if cfg.min_puncta_area <= p.area <= max_area]
    return np.isin(labels, keep_ids) if keep_ids else np.zeros_like(puncta, dtype=bool)


def _remove_small_objects(mask: np.ndarray, min_size: int) -> np.ndarray:
    return morphology.remove_small_objects(mask, max_size=min_size - 1)


def quantify_mcherry_from_file(
    timeseries_path: str | Path,
    phenotype_channel_index: int | None = None,
    config: MCherryMetricConfig | None = None,
) -> pd.DataFrame:
    """Convenience wrapper: read a TYX/TCYX file and quantify mCherry."""
    from ..io import read_image

    arr = np.squeeze(np.asarray(read_image(timeseries_path)))
    if arr.ndim == 2:
        mcherry = arr[np.newaxis, :, :]
    elif arr.ndim == 3:
        mcherry = arr
    elif arr.ndim == 4:
        ch = phenotype_channel_index if phenotype_channel_index is not None else 0
        mcherry = arr[:, ch, :, :]
    elif arr.ndim == 5:
        ch = phenotype_channel_index if phenotype_channel_index is not None else 0
        mcherry = arr[:, ch].max(axis=1)
    else:
        raise ValueError(f"Unsupported timeseries shape: {arr.shape}")
    return quantify_mcherry_timeseries(mcherry, config=config)


def _as_tyx(arr: np.ndarray) -> np.ndarray:
    squeezed = np.squeeze(np.asarray(arr))
    if squeezed.ndim == 2:
        return squeezed[np.newaxis, :, :]
    if squeezed.ndim == 3:
        return squeezed
    raise ValueError(f"Expected YX or TYX input, got shape {np.asarray(arr).shape}")
