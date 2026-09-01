#!/usr/bin/env python3
"""Create soma-anchored single-neuron bounding-box MP4s with guarded quantification.

Input
-----
Existing locally registered ROI stacks named
    <WELL>_single_neuron_registered_tcyx.ome.tif
with shape (T,C,Y,X).

Key changes versus centroid-following bbox scripts
--------------------------------------------------
1. Neuron tracking uses ONLY the stable 488 channel.
2. Day 8 establishes a soma-centered 488 template.
3. Later visits locate that same template only within a limited search radius around
   the Day-8 anchor. The bounding box follows this soma anchor, never a whole-mask centroid.
4. Neuron segmentation is performed only inside the tight bounding box, preventing
   watershed/connected-component masks from exploding into the surrounding 512x512 field.
5. Hard QC gates mask area continuity, centroid-to-anchor distance, border contact,
   and 488 template-match score. Standard quantitative columns are set to NaN when QC fails.
   Raw values are retained in raw_* columns for troubleshooting.
6. Puncta use DoG (sigma 1 - sigma 3) with threshold max(median + 4*MAD-sigma, 97.5th percentile).
7. MP4s show original unmasked pixels inside the tight box. No temporal interpolation.

Segmentation v2
---------------
Later-day neuron masks use a translated 488 mask from the most recent QC-valid visit as a spatial prior, with a Day-8 translated-mask fallback. Multiple locally adaptive 488 thresholds are evaluated and the candidate closest in area/position/overlap to the tracked soma is selected. Tracking itself remains Day-8-template anchored and never uses mCherry.

Optional manual seed CSV
------------------------
Columns: well,seed_x,seed_y
Coordinates are in the existing 512x512 local registered ROI stack and apply to Day 8 only.
"""
from __future__ import annotations

import argparse
import math
import shutil
from pathlib import Path

import imageio.v2 as imageio
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import tifffile as tif
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.patches import Rectangle
from scipy.ndimage import binary_fill_holes, gaussian_filter, shift as ndi_shift
from skimage import feature, filters, measure, morphology, segmentation

DAYS_DEFAULT = [8, 12, 16, 20, 25, 29, 32, 36, 39]
WELLS_DEFAULT = ["E05", "F05", "I05", "J05", "M05", "N05"]
CONDITION = {
    "E05": "PLD3 + mCherry reporter control",
    "F05": "PLD3 + TMEM106B + mCherry",
    "I05": "PLD3 + mCherry reporter control",
    "J05": "PLD3 + TMEM106B + mCherry",
    "M05": "PLD3 + mCherry reporter control",
    "N05": "PLD3 + TMEM106B + mCherry",
}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--processed-root", type=Path, required=True)
    p.add_argument("--output-root", type=Path, required=True)
    p.add_argument("--wells", nargs="+", default=WELLS_DEFAULT)
    p.add_argument("--days", nargs="+", type=int, default=DAYS_DEFAULT)
    p.add_argument("--alignment-channel", type=int, default=2)
    p.add_argument("--mcherry-channel", type=int, default=1)
    p.add_argument("--seed-csv", type=Path, default=None,
                   help="Optional CSV with columns well,seed_x,seed_y for Day-8 soma anchor.")
    p.add_argument("--center-csv", type=Path, default=None,
                   help="Optional per-day manual overrides: well,day,center_x,center_y.")
    p.add_argument("--bbox-size", type=int, default=128)
    p.add_argument("--template-size", type=int, default=64)
    p.add_argument("--search-radius", type=int, default=48,
                   help="Maximum template search radius around Day-8 anchor in pixels.")
    p.add_argument("--auto-seed-radius", type=int, default=45,
                   help="When no manual seed is supplied, search for a 488 soma peak this far from ROI center.")
    p.add_argument("--min-template-score", type=float, default=0.08)
    p.add_argument("--min-neuron-area", type=int, default=180)
    p.add_argument("--min-area-ratio", type=float, default=0.35)
    p.add_argument("--max-area-ratio", type=float, default=2.5)
    p.add_argument("--max-mask-centroid-offset", type=float, default=24.0)
    p.add_argument("--puncta-min-size", type=int, default=6)
    p.add_argument("--fps", type=int, default=10)
    p.add_argument("--hold-seconds", type=float, default=1.0)
    return p.parse_args()


def robust01(frame: np.ndarray) -> np.ndarray:
    x = frame.astype(np.float32)
    lo, hi = np.percentile(x, [2, 99.7])
    if hi <= lo:
        return np.zeros_like(x, dtype=np.float32)
    return np.clip((x - lo) / (hi - lo), 0, 1)


def square_bounds(cy: float, cx: float, size: int, height: int, width: int):
    size = int(min(size, height, width))
    y0 = int(round(cy - size / 2))
    x0 = int(round(cx - size / 2))
    y0 = max(0, min(y0, height - size))
    x0 = max(0, min(x0, width - size))
    return y0, y0 + size, x0, x0 + size


def load_seed_map(path: Path | None):
    out = {}
    if path is None:
        return out
    df = pd.read_csv(path)
    needed = {"well", "seed_x", "seed_y"}
    missing = needed - set(df.columns)
    if missing:
        raise ValueError(f"Seed CSV missing columns: {sorted(missing)}")
    for _, row in df.iterrows():
        out[str(row["well"])] = (float(row["seed_y"]), float(row["seed_x"]))
    return out



def load_center_overrides(path: Path | None):
    out = {}
    if path is None:
        return out
    df = pd.read_csv(path)
    needed = {"well", "day", "center_x", "center_y"}
    missing = needed - set(df.columns)
    if missing:
        raise ValueError(f"Center CSV missing columns: {sorted(missing)}")
    for _, row in df.iterrows():
        out[(str(row["well"]), int(row["day"]))] = (float(row["center_y"]), float(row["center_x"]))
    return out

def find_stack(root: Path, well: str) -> Path:
    matches = sorted(root.rglob(f"{well}_single_neuron_registered_tcyx.ome.tif"))
    if len(matches) != 1:
        raise RuntimeError(f"Expected exactly one registered ROI stack for {well}; found {len(matches)}: {matches}")
    return matches[0]


def refine_peak_center(smooth: np.ndarray, py: int, px: int, radius: int = 12):
    h, w = smooth.shape
    y0, y1 = max(0, py - radius), min(h, py + radius + 1)
    x0, x1 = max(0, px - radius), min(w, px + radius + 1)
    sub = smooth[y0:y1, x0:x1].astype(np.float64)
    # emphasize the bright soma/core while retaining subpixel center-of-mass stability
    floor = np.percentile(sub, 65)
    weights = np.clip(sub - floor, 0, None)
    if weights.sum() <= 0:
        return float(py), float(px)
    yy, xx = np.mgrid[y0:y1, x0:x1]
    cy = float((yy * weights).sum() / weights.sum())
    cx = float((xx * weights).sum() / weights.sum())
    return cy, cx


def auto_day8_anchor(frame488: np.ndarray, radius: int):
    norm = robust01(frame488)
    smooth = gaussian_filter(norm, sigma=1.25)
    h, w = smooth.shape
    cy0, cx0 = (h - 1) / 2.0, (w - 1) / 2.0
    y0 = max(0, int(round(cy0)) - radius)
    y1 = min(h, int(round(cy0)) + radius + 1)
    x0 = max(0, int(round(cx0)) - radius)
    x1 = min(w, int(round(cx0)) + radius + 1)
    sub = smooth[y0:y1, x0:x1]
    py, px = np.unravel_index(np.argmax(sub), sub.shape)
    py += y0
    px += x0
    return refine_peak_center(smooth, int(py), int(px))


def make_template(frame488: np.ndarray, anchor_y: float, anchor_x: float, size: int):
    norm = gaussian_filter(robust01(frame488), sigma=1.0)
    y0, y1, x0, x1 = square_bounds(anchor_y, anchor_x, size, *norm.shape)
    template = norm[y0:y1, x0:x1].copy()
    # zero-center reduces sensitivity to day-to-day global intensity offsets
    template -= float(template.mean())
    sd = float(template.std())
    if sd > 1e-6:
        template /= sd
    return template.astype(np.float32)


def track_anchor(frame488: np.ndarray, template: np.ndarray, ref_y: float, ref_x: float,
                 search_radius: int):
    norm = gaussian_filter(robust01(frame488), sigma=1.0)
    th, tw = template.shape
    hy, hx = th // 2, tw // 2
    h, w = norm.shape
    y0 = max(0, int(round(ref_y)) - search_radius - hy)
    y1 = min(h, int(round(ref_y)) + search_radius + hy + 1)
    x0 = max(0, int(round(ref_x)) - search_radius - hx)
    x1 = min(w, int(round(ref_x)) + search_radius + hx + 1)
    search = norm[y0:y1, x0:x1]
    if search.shape[0] < th or search.shape[1] < tw:
        return float(ref_y), float(ref_x), math.nan
    corr = feature.match_template(search, template, pad_input=False)
    iy, ix = np.unravel_index(np.nanargmax(corr), corr.shape)
    score = float(corr[iy, ix])
    cy = float(y0 + iy + (th - 1) / 2.0)
    cx = float(x0 + ix + (tw - 1) / 2.0)
    return cy, cx, score


def nearest_true(mask: np.ndarray, y: float, x: float, max_radius: float = 30.0):
    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        return None
    d2 = (ys - y) ** 2 + (xs - x) ** 2
    i = int(np.argmin(d2))
    if float(np.sqrt(d2[i])) > max_radius:
        return None
    return int(ys[i]), int(xs[i])


def translate_mask(mask: np.ndarray, dy: float, dx: float) -> np.ndarray:
    """Translate a binary mask without interpolation artifacts."""
    return ndi_shift(mask.astype(np.uint8), shift=(dy, dx), order=0,
                     mode="constant", cval=0, prefilter=False).astype(bool)


def _candidate_from_binary(binary: np.ndarray, smooth: np.ndarray, sy: float, sx: float,
                           ref_area: int | None, prior_core: np.ndarray | None):
    """Return the best connected component near the soma anchor for one threshold."""
    binary = morphology.remove_small_objects(binary.astype(bool), max_size=39)
    binary = morphology.closing(binary, morphology.disk(1))
    binary = binary_fill_holes(binary)
    labels = measure.label(binary)
    if labels.max() == 0:
        return None

    candidates = []
    for prop in measure.regionprops(labels, intensity_image=smooth):
        component = labels == prop.label
        area = int(prop.area)
        cy, cx = map(float, prop.centroid)
        centroid_offset = float(np.hypot(cy - sy, cx - sx))

        ys, xs = np.nonzero(component)
        if len(xs) == 0:
            continue
        nearest = float(np.sqrt(np.min((ys - sy) ** 2 + (xs - sx) ** 2)))
        # A valid soma component must be close to the tracked 488 anchor.
        if nearest > 18.0 and centroid_offset > 30.0:
            continue

        border_touch = bool(component[0].any() or component[-1].any() or
                            component[:, 0].any() or component[:, -1].any())
        if prior_core is not None and prior_core.any():
            overlap = float((component & prior_core).sum() / max(component.sum(), 1))
        else:
            overlap = math.nan

        if ref_area and ref_area > 0:
            ratio = area / ref_area
            area_score = math.exp(-abs(math.log(max(ratio, 1e-6))))
        else:
            ratio = math.nan
            area_score = min(1.0, area / 500.0)
        proximity_score = math.exp(-centroid_offset / 14.0)
        overlap_score = 0.0 if not np.isfinite(overlap) else overlap
        score = 2.0 * area_score + 1.5 * proximity_score + 2.5 * overlap_score
        if border_touch:
            score -= 1.5
        candidates.append((score, component, area, cy, cx, centroid_offset,
                           border_touch, overlap, ratio))

    if not candidates:
        return None
    return max(candidates, key=lambda x: x[0])


def segment_neuron_in_box(frame488: np.ndarray, anchor_y: float, anchor_x: float,
                          bbox_size: int, min_area: int, *, ref_area: int | None = None,
                          prior_mask: np.ndarray | None = None,
                          prior_source: str = "none"):
    """Locally adaptive 488 segmentation with a soma-centered spatial prior.

    Unlike v1, failure of a single Otsu/hysteresis threshold does not imply an empty
    mask. Multiple thresholds tied to the local soma intensity are evaluated. When a
    prior is supplied, segmentation is constrained to a modest dilation of the
    translated previous/Day-8 neuron mask, which prevents grabbing neighboring cells.
    """
    h, w = frame488.shape
    y0, y1, x0, x1 = square_bounds(anchor_y, anchor_x, bbox_size, h, w)
    crop = frame488[y0:y1, x0:x1]
    norm = robust01(crop)
    smooth = gaussian_filter(norm, sigma=1.1)

    sy = float(anchor_y - y0)
    sx = float(anchor_x - x0)
    syi = int(round(np.clip(sy, 0, bbox_size - 1)))
    sxi = int(round(np.clip(sx, 0, bbox_size - 1)))

    # Refine only the segmentation seed to the strongest local 488 peak. The display
    # box and identity anchor remain the Day-8-template tracked soma position.
    yy0, yy1 = max(0, syi - 18), min(bbox_size, syi + 19)
    xx0, xx1 = max(0, sxi - 18), min(bbox_size, sxi + 19)
    local = smooth[yy0:yy1, xx0:xx1]
    if local.size == 0:
        raise RuntimeError("Empty 488 search region around soma anchor")
    py, px = np.unravel_index(np.argmax(local), local.shape)
    seed_y, seed_x = yy0 + int(py), xx0 + int(px)
    seed_value = float(smooth[seed_y, seed_x])
    if not np.isfinite(seed_value) or seed_value <= 0.005:
        raise RuntimeError("Insufficient local 488 signal at tracked soma anchor")

    prior_core = None
    allowed = np.ones(crop.shape, dtype=bool)
    if prior_mask is not None and np.any(prior_mask):
        prior_core = prior_mask[y0:y1, x0:x1].astype(bool)
        # Permit modest morphology change, but not expansion into the whole crop.
        allowed = morphology.dilation(prior_core, morphology.disk(12))
        # Always retain a small circle around the tracked soma, even if fractional
        # translations create a tiny gap in the prior.
        yy, xx = np.ogrid[:bbox_size, :bbox_size]
        allowed |= (yy - sy) ** 2 + (xx - sx) ** 2 <= 22 ** 2

    positive = smooth[(smooth > 0.005) & allowed]
    if positive.size < 20:
        raise RuntimeError("Insufficient 488 foreground in soma prior")

    thresholds = []
    try:
        thresholds.append(float(filters.threshold_otsu(positive)))
    except ValueError:
        pass
    for q in (80, 72, 65, 58, 50, 42, 35, 28):
        thresholds.append(float(np.percentile(positive, q)))
    for frac in (0.80, 0.70, 0.60, 0.50, 0.42, 0.35, 0.28, 0.22):
        thresholds.append(seed_value * frac)
    thresholds = sorted({max(0.008, min(float(t), seed_value * 0.98))
                         for t in thresholds if np.isfinite(t)}, reverse=True)

    best = None
    best_thr = math.nan
    for thr in thresholds:
        binary = (smooth >= thr) & allowed
        cand = _candidate_from_binary(binary, smooth, sy, sx, ref_area, prior_core)
        if cand is None:
            continue
        score = cand[0]
        # Prefer candidates that are at least large enough to be cell-like, without
        # making min_area a hard requirement during candidate discovery.
        if cand[2] >= min_area:
            score += 0.4
        if best is None or score > best[0]:
            best = (score,) + cand[1:]
            best_thr = thr

    if best is None:
        raise RuntimeError("No plausible 488 component near tracked soma anchor after adaptive fallback")

    _, target, area, cy_local, cx_local, centroid_offset_local, border_touch, overlap, ratio = best
    cy = float(y0 + cy_local)
    cx = float(x0 + cx_local)
    centroid_offset = float(np.hypot(cy - anchor_y, cx - anchor_x))

    full = np.zeros(frame488.shape, dtype=bool)
    full[y0:y1, x0:x1] = target
    return full, {
        "segmentation_area": int(area),
        "segmentation_centroid_y": cy,
        "segmentation_centroid_x": cx,
        "segmentation_centroid_offset_from_anchor": centroid_offset,
        "segmentation_border_touch": bool(border_touch),
        "foreground_low_threshold": float(best_thr),
        "foreground_high_threshold": float(best_thr),
        "segmentation_method": "adaptive_multithreshold_488_with_spatial_prior",
        "segmentation_prior_source": prior_source,
        "segmentation_overlap_with_prior": overlap,
        "segmentation_seed_488": seed_value,
    }

def dog_puncta(mcherry: np.ndarray, mask: np.ndarray, min_size: int):
    x = mcherry.astype(np.float32)
    if not np.any(mask):
        return np.zeros_like(mask, dtype=bool), [], math.nan
    dog = gaussian_filter(x, 1.0) - gaussian_filter(x, 3.0)
    vals = dog[mask]
    med = float(np.median(vals))
    mad = float(np.median(np.abs(vals - med)))
    robust_sigma = 1.4826 * mad
    threshold = max(med + 4.0 * robust_sigma, float(np.percentile(vals, 97.5)))
    puncta = (dog > threshold) & mask
    puncta = morphology.remove_small_objects(puncta, max_size=max(0, min_size - 1))
    labels = measure.label(puncta)
    props = measure.regionprops(labels, intensity_image=x)
    return puncta, props, threshold


def raw_metrics(mcherry: np.ndarray, mask: np.ndarray, puncta: np.ndarray, props):
    area = int(mask.sum())
    if area == 0:
        return {k: math.nan for k in [
            "total_mcherry_intensity", "diffuse_mcherry_integrated_intensity",
            "diffuse_mcherry_mean_intensity", "punctate_mcherry_integrated_intensity",
            "puncta_count", "puncta_density_per_area", "mean_puncta_intensity",
            "median_puncta_area", "diffuse_to_punctate_ratio", "rupture_like_score"]}
    diffuse_mask = mask & ~puncta
    total = float(mcherry[mask].sum(dtype=np.float64))
    punctate = float(mcherry[puncta].sum(dtype=np.float64))
    diffuse = float(mcherry[diffuse_mask].sum(dtype=np.float64))
    count = int(len(props))
    means = [float(p.intensity_mean) for p in props]
    areas = [float(p.area) for p in props]
    ratio = diffuse / punctate if punctate > 0 else math.nan
    return {
        "total_mcherry_intensity": total,
        "diffuse_mcherry_integrated_intensity": diffuse,
        "diffuse_mcherry_mean_intensity": float(mcherry[diffuse_mask].mean()) if diffuse_mask.any() else math.nan,
        "punctate_mcherry_integrated_intensity": punctate,
        "puncta_count": count,
        "puncta_density_per_area": count / area if area else math.nan,
        "mean_puncta_intensity": float(np.mean(means)) if means else math.nan,
        "median_puncta_area": float(np.median(areas)) if areas else math.nan,
        "diffuse_to_punctate_ratio": ratio,
        "rupture_like_score": ratio,
    }


def display_limits(stack: np.ndarray, channel: int, bounds):
    vals = []
    for i, b in enumerate(bounds):
        y0, y1, x0, x1 = b
        vals.append(stack[i, channel, y0:y1, x0:x1].astype(np.float32).ravel())
    vals = np.concatenate(vals)
    return float(np.percentile(vals, 1)), float(np.percentile(vals, 99.6))


def norm_crop(image: np.ndarray, bounds, limits):
    y0, y1, x0, x1 = bounds
    lo, hi = limits
    x = image[y0:y1, x0:x1].astype(np.float32)
    return np.clip((x - lo) / max(hi - lo, 1e-6), 0, 1)


def render_frame(well, day, frame488, mcherry, puncta, row, bounds, lim488, lim561):
    y0, y1, x0, x1 = bounds
    green = norm_crop(frame488, bounds, lim488)
    red = norm_crop(mcherry, bounds, lim561)
    merge = np.zeros((*green.shape, 3), dtype=np.float32)
    merge[..., 0] = red
    merge[..., 1] = green
    p = puncta[y0:y1, x0:x1]

    fig = plt.figure(figsize=(12.8, 7.2), dpi=100)
    gs = fig.add_gridspec(2, 3, height_ratios=[5, 1.35], hspace=0.08, wspace=0.04)
    axes = [fig.add_subplot(gs[0, i]) for i in range(3)]
    axes[0].imshow(green, cmap="gray", vmin=0, vmax=1, interpolation="nearest")
    axes[1].imshow(red, cmap="magma", vmin=0, vmax=1, interpolation="nearest")
    axes[2].imshow(merge, vmin=0, vmax=1, interpolation="nearest")
    for ax, title in zip(axes, ("488 (soma-anchored)", "561 / mCherry", "488 + mCherry")):
        ax.set_title(title, fontsize=12)
        ax.set_axis_off()
        # crosshair is visual QC only: exact box center == tracked soma anchor
        mid = (green.shape[0] - 1) / 2.0
        ax.plot([mid - 4, mid + 4], [mid, mid], lw=0.7, alpha=0.7)
        ax.plot([mid, mid], [mid - 4, mid + 4], lw=0.7, alpha=0.7)
    if p.any():
        axes[2].contour(p.astype(float), levels=[0.5], linewidths=0.6)

    txt = fig.add_subplot(gs[1, :]); txt.axis("off")
    valid = bool(row["metrics_valid"])
    ratio = row["diffuse_to_punctate_ratio"]
    ratio_txt = "NA" if pd.isna(ratio) else f"{ratio:.3f}"
    count = row["puncta_count"]
    count_txt = "NA" if pd.isna(count) else f"{int(count)}"
    header = f"{well} | {CONDITION.get(well,'')} | Day {day} | {y1-y0}x{x1-x0}px soma-anchored box"
    metrics = (
        f"Puncta: {count_txt}    Diffuse/Punctate: {ratio_txt}    "
        f"488 template score: {row['template_match_score']:.3f}    "
        f"Mask area ratio vs Day 8: {row['mask_area_ratio_vs_day8']:.2f}    "
        f"QC: {'PASS' if valid else 'REVIEW - metrics withheld'}"
    )
    note = "Display center = 488 soma template anchor. Quantification = 488 mask confined to this box; failed-QC metrics are NaN."
    txt.text(0.01, 0.78, header, fontsize=15, weight="bold", va="top")
    txt.text(0.01, 0.43, metrics, fontsize=11, va="top")
    txt.text(0.01, 0.10, note, fontsize=9, va="top")
    canvas = FigureCanvasAgg(fig); canvas.draw()
    rgb = np.asarray(canvas.buffer_rgba())[..., :3].copy()
    plt.close(fig)
    return rgb


def write_qc(well, days, stack, bounds, rows, out_path, alignment_channel, mcherry_channel):
    fig, axes = plt.subplots(2, len(days), figsize=(3 * len(days), 6), constrained_layout=True)
    full_lo, full_hi = np.percentile(stack[:, alignment_channel], [1, 99.6])
    lim561 = display_limits(stack, mcherry_channel, bounds)
    for i, day in enumerate(days):
        full = np.clip((stack[i, alignment_channel].astype(np.float32) - full_lo) / max(full_hi - full_lo, 1e-6), 0, 1)
        axes[0, i].imshow(full, cmap="gray", vmin=0, vmax=1, interpolation="nearest")
        y0, y1, x0, x1 = bounds[i]
        axes[0, i].add_patch(Rectangle((x0, y0), x1-x0, y1-y0, fill=False, linewidth=1.2))
        axes[0, i].plot(rows[i]["anchor_x"], rows[i]["anchor_y"], "+", ms=8)
        axes[0, i].set_title(f"D{day} score={rows[i]['template_match_score']:.2f}")
        red = norm_crop(stack[i, mcherry_channel], bounds[i], lim561)
        axes[1, i].imshow(red, cmap="magma", vmin=0, vmax=1, interpolation="nearest")
        axes[1, i].set_title("PASS" if rows[i]["metrics_valid"] else "REVIEW")
    for ax in axes.ravel():
        ax.set_axis_off()
    fig.suptitle(f"{well}: soma-anchored 128px bbox QC", fontsize=16)
    fig.savefig(out_path, dpi=160)
    plt.close(fig)


def main():
    args = parse_args()
    out_root = args.output_root
    out_root.mkdir(parents=True, exist_ok=True)
    seeds = load_seed_map(args.seed_csv)
    center_overrides = load_center_overrides(args.center_csv)

    if shutil.which("ffmpeg") is None:
        try:
            import imageio_ffmpeg  # noqa: F401
        except Exception as exc:
            raise RuntimeError("MP4 export needs ffmpeg or imageio-ffmpeg") from exc

    all_rows = []
    for well in args.wells:
        stack_path = find_stack(args.processed_root, well)
        stack = tif.imread(stack_path)
        if stack.ndim != 4 or stack.shape[0] != len(args.days):
            raise RuntimeError(f"{well}: expected ({len(args.days)},C,Y,X), got {stack.shape}")
        h, w = stack.shape[-2:]

        if well in seeds:
            sy0, sx0 = seeds[well]
            smooth0 = gaussian_filter(robust01(stack[0, args.alignment_channel]), sigma=1.25)
            syi, sxi = int(round(sy0)), int(round(sx0))
            rr = 24
            yy0, yy1 = max(0, syi-rr), min(h, syi+rr+1)
            xx0, xx1 = max(0, sxi-rr), min(w, sxi+rr+1)
            sub = smooth0[yy0:yy1, xx0:xx1]
            py, px = np.unravel_index(np.argmax(sub), sub.shape)
            ref_y, ref_x = refine_peak_center(smooth0, yy0+int(py), xx0+int(px))
            seed_source = "day8_seed_csv_refined_to_488_soma_peak"
        else:
            ref_y, ref_x = auto_day8_anchor(stack[0, args.alignment_channel], args.auto_seed_radius)
            seed_source = "auto_488_soma_peak_near_roi_center"
        template = make_template(stack[0, args.alignment_channel], ref_y, ref_x, args.template_size)

        anchors = []
        scores = []
        anchor_sources = []
        for i, day in enumerate(args.days):
            if (well, int(day)) in center_overrides:
                ay, ax = center_overrides[(well, int(day))]
                score = 1.0
                anchor_source = "manual_per_day_center_override"
            elif i == 0:
                ay, ax, score = ref_y, ref_x, 1.0
                anchor_source = seed_source
            else:
                ay, ax, score = track_anchor(
                    stack[i, args.alignment_channel], template, ref_y, ref_x, args.search_radius
                )
                anchor_source = "488_day8_soma_template_match"
            anchors.append((ay, ax))
            scores.append(score)
            anchor_sources.append(anchor_source)

        masks = []
        puncta_masks = []
        rows = []
        ref_area = None
        ref_mask = None
        last_valid_mask = None
        last_valid_anchor = None
        bounds = []
        bbox_crops = []

        for i, day in enumerate(args.days):
            ay, ax = anchors[i]
            b = square_bounds(ay, ax, args.bbox_size, h, w)
            bounds.append(b)
            y0, y1, x0, x1 = b
            bbox_crops.append(stack[i, :, y0:y1, x0:x1])

            # Segmentation prior: follow the most recent QC-valid 488 mask using only
            # the soma-anchor displacement. Fall back to translated Day-8 morphology.
            prior_mask = None
            prior_source = "none_day8"
            if i > 0 and last_valid_mask is not None and last_valid_anchor is not None:
                pdy = ay - last_valid_anchor[0]
                pdx = ax - last_valid_anchor[1]
                prior_mask = translate_mask(last_valid_mask, pdy, pdx)
                prior_source = "translated_previous_valid_488_mask"
            elif i > 0 and ref_mask is not None:
                prior_mask = translate_mask(ref_mask, ay - ref_y, ax - ref_x)
                prior_source = "translated_day8_488_mask"

            seg_error = ""
            try:
                mask, seg = segment_neuron_in_box(
                    stack[i, args.alignment_channel], ay, ax, args.bbox_size,
                    args.min_neuron_area, ref_area=ref_area, prior_mask=prior_mask,
                    prior_source=prior_source,
                )
            except Exception as exc:
                # A second, broader Day-8 prior is safer than dropping the spatial prior
                # entirely, because it preserves neuron identity while allowing recovery
                # after an isolated bad previous mask.
                if i > 0 and ref_mask is not None and prior_source != "translated_day8_488_mask":
                    try:
                        backup_prior = translate_mask(ref_mask, ay - ref_y, ax - ref_x)
                        mask, seg = segment_neuron_in_box(
                            stack[i, args.alignment_channel], ay, ax, args.bbox_size,
                            args.min_neuron_area, ref_area=ref_area, prior_mask=backup_prior,
                            prior_source="translated_day8_488_mask_fallback",
                        )
                    except Exception as exc2:
                        mask = np.zeros((h, w), dtype=bool)
                        seg = {
                            "segmentation_area": 0,
                            "segmentation_centroid_y": math.nan,
                            "segmentation_centroid_x": math.nan,
                            "segmentation_centroid_offset_from_anchor": math.nan,
                            "segmentation_border_touch": True,
                            "foreground_low_threshold": math.nan,
                            "foreground_high_threshold": math.nan,
                            "segmentation_method": "failed",
                            "segmentation_prior_source": "day8_fallback_failed",
                            "segmentation_overlap_with_prior": math.nan,
                            "segmentation_seed_488": math.nan,
                        }
                        seg_error = f"primary: {exc}; day8 fallback: {exc2}"
                else:
                    mask = np.zeros((h, w), dtype=bool)
                    seg = {
                        "segmentation_area": 0,
                        "segmentation_centroid_y": math.nan,
                        "segmentation_centroid_x": math.nan,
                        "segmentation_centroid_offset_from_anchor": math.nan,
                        "segmentation_border_touch": True,
                        "foreground_low_threshold": math.nan,
                        "foreground_high_threshold": math.nan,
                        "segmentation_method": "failed",
                        "segmentation_prior_source": prior_source,
                        "segmentation_overlap_with_prior": math.nan,
                        "segmentation_seed_488": math.nan,
                    }
                    seg_error = str(exc)

            if i == 0:
                ref_area = max(int(seg["segmentation_area"]), 1)
            area_ratio = float(seg["segmentation_area"] / ref_area) if ref_area else math.nan
            template_ok = bool(anchor_sources[i].startswith("manual_") or i == 0 or (np.isfinite(scores[i]) and scores[i] >= args.min_template_score))
            area_ok = bool(args.min_area_ratio <= area_ratio <= args.max_area_ratio)
            centroid_ok = bool(np.isfinite(seg["segmentation_centroid_offset_from_anchor"]) and
                               seg["segmentation_centroid_offset_from_anchor"] <= args.max_mask_centroid_offset)
            border_ok = not bool(seg["segmentation_border_touch"])
            area_abs_ok = int(seg["segmentation_area"]) >= args.min_neuron_area
            valid = bool(template_ok and area_ok and centroid_ok and border_ok and area_abs_ok and not seg_error)
            if i == 0 and int(seg["segmentation_area"]) > 0:
                ref_mask = mask.copy()
            if valid:
                last_valid_mask = mask.copy()
                last_valid_anchor = (ay, ax)

            puncta, props, dog_thr = dog_puncta(stack[i, args.mcherry_channel], mask, args.puncta_min_size)
            raw = raw_metrics(stack[i, args.mcherry_channel], mask, puncta, props)
            row = {
                "well": well,
                "condition": CONDITION.get(well, ""),
                "time_index": i,
                "day": day,
                "cell_roi_id": f"{well}_Neuron001",
                "mask_source": "488_soma_template_anchor_adaptive_multithreshold_spatial_prior",
                "seed_source": seed_source,
                "anchor_y": ay,
                "anchor_x": ax,
                "anchor_source": anchor_sources[i],
                "anchor_shift_y_from_day8": ay - ref_y,
                "anchor_shift_x_from_day8": ax - ref_x,
                "anchor_shift_pixels_from_day8": float(np.hypot(ay-ref_y, ax-ref_x)),
                "template_match_score": float(scores[i]),
                "mask_area_ratio_vs_day8": area_ratio,
                "metrics_valid": valid,
                "qc_template_ok": template_ok,
                "qc_area_ok": area_ok,
                "qc_centroid_ok": centroid_ok,
                "qc_border_ok": border_ok,
                "qc_area_absolute_ok": area_abs_ok,
                "segmentation_error": seg_error,
                "dog_threshold": dog_thr,
                "stack_path": str(stack_path),
            }
            row.update(seg)
            # Always retain raw values for diagnostics.
            for k, v in raw.items():
                row[f"raw_{k}"] = v
            # Standard values are withheld when QC fails.
            for k, v in raw.items():
                row[k] = v if valid else math.nan
            row["neuron_mask_area"] = int(seg["segmentation_area"]) if valid else math.nan
            row["interpretation"] = "screening metric for punctate-to-diffuse redistribution; not proof of rupture"

            masks.append(mask)
            puncta_masks.append(puncta)
            rows.append(row)
            all_rows.append(row)

        masks_arr = np.stack(masks).astype(np.uint8)
        puncta_arr = np.stack(puncta_masks).astype(np.uint8)
        bbox_stack = np.stack(bbox_crops, axis=0)
        tif.imwrite(out_root / f"{well}_Neuron001_mask_tyx.ome.tif", masks_arr, metadata={"axes":"TYX"})
        tif.imwrite(out_root / f"{well}_Neuron001_puncta_mask_tyx.ome.tif", puncta_arr, metadata={"axes":"TYX"})
        tif.imwrite(out_root / f"{well}_Neuron001_bbox_tcyx.ome.tif", bbox_stack, metadata={"axes":"TCYX"})
        pd.DataFrame(rows).to_csv(out_root / f"{well}_Neuron001_metrics.csv", index=False)
        pd.DataFrame([{
            "well": well, "day": day, "time_index": i,
            "center_y_488": anchors[i][0], "center_x_488": anchors[i][1],
            "template_match_score": scores[i], "anchor_source": anchor_sources[i],
            "y0": bounds[i][0], "y1": bounds[i][1], "x0": bounds[i][2], "x1": bounds[i][3],
            "bbox_size_pixels": args.bbox_size, "selection_channel":"488",
        } for i, day in enumerate(args.days)]).to_csv(out_root / f"{well}_Neuron001_bbox.csv", index=False)

        write_qc(
            well, args.days, stack, bounds, rows,
            out_root / f"{well}_Neuron001_bbox_qc.png",
            args.alignment_channel, args.mcherry_channel,
        )

        lim488 = display_limits(stack, args.alignment_channel, bounds)
        lim561 = display_limits(stack, args.mcherry_channel, bounds)
        mp4 = out_root / f"{well}_Neuron001_bbox_timelapse.mp4"
        writer = imageio.get_writer(mp4, fps=args.fps, codec="libx264", quality=8, macro_block_size=1)
        repeats = max(1, int(round(args.fps * args.hold_seconds)))
        try:
            for i, day in enumerate(args.days):
                frame = render_frame(
                    well, day,
                    stack[i, args.alignment_channel], stack[i, args.mcherry_channel],
                    puncta_masks[i], rows[i], bounds[i], lim488, lim561,
                )
                for _ in range(repeats):
                    writer.append_data(frame)
        finally:
            writer.close()

        n_valid = int(sum(bool(r["metrics_valid"]) for r in rows))
        print(f"Wrote {well}: {mp4}; QC-valid visits {n_valid}/{len(rows)}")

    pd.DataFrame(all_rows).to_csv(out_root / "all_six_neuron_metrics.csv", index=False)
    print(f"All outputs: {out_root}")


if __name__ == "__main__":
    main()
