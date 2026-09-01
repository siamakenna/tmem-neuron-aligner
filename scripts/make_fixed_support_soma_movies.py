#!/usr/bin/env python3
"""Recompute longitudinal single-neuron mCherry metrics with a fixed soma-centered support mask.

This script is intended to run *after* make_soma_anchored_bbox_movies_v2.py.
It reuses v2's 488-only soma tracking and 128x128 centered bounding boxes, but it
stops using a different neuron segmentation mask at each visit for quantification.

For each well:
1. Extract v2's QC-valid 488 neuron masks into soma-centered 128x128 coordinates.
2. Build one consensus support mask from pixels present on multiple QC-valid visits.
3. Use that exact same support mask at every visit.
4. Estimate local 561 background outside the support mask and subtract it.
5. Detect mCherry puncta with DoG (sigma 1 - sigma 3) within the fixed support.
6. Write corrected metrics, QC images, a fixed-mask OME-TIFF, and a real MP4.

The bounding box is display-only. Tracking and support construction use 488 only;
mCherry never determines neuron identity, position, or analysis-mask geometry.
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
from scipy.ndimage import binary_fill_holes, gaussian_filter
from skimage import measure, morphology

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
    p.add_argument("--v2-root", type=Path, required=True,
                   help="Directory produced by make_soma_anchored_bbox_movies_v2.py")
    p.add_argument("--output-root", type=Path, required=True)
    p.add_argument("--wells", nargs="+", default=WELLS_DEFAULT)
    p.add_argument("--days", nargs="+", type=int, default=DAYS_DEFAULT)
    p.add_argument("--alignment-channel", type=int, default=2)
    p.add_argument("--mcherry-channel", type=int, default=1)
    p.add_argument("--consensus-fraction", type=float, default=0.35,
                   help="Fraction of QC-valid masks that must contain a pixel; minimum two visits.")
    p.add_argument("--support-dilation", type=int, default=2,
                   help="Small dilation of the consensus support to tolerate subpixel/morphology drift.")
    p.add_argument("--min-support-area", type=int, default=150)
    p.add_argument("--max-support-area", type=int, default=3500)
    p.add_argument("--background-exclusion", type=int, default=6,
                   help="Exclude this many pixels around the support mask when estimating local 561 background.")
    p.add_argument("--puncta-min-size", type=int, default=6)
    p.add_argument("--min-template-score", type=float, default=0.08)
    p.add_argument("--fps", type=int, default=10)
    p.add_argument("--hold-seconds", type=float, default=1.0)
    return p.parse_args()


def robust_limits(vals: np.ndarray, lo_q=1.0, hi_q=99.6):
    x = np.asarray(vals, dtype=np.float32)
    return float(np.percentile(x, lo_q)), float(np.percentile(x, hi_q))


def normalize(image: np.ndarray, limits):
    lo, hi = limits
    x = image.astype(np.float32)
    return np.clip((x - lo) / max(hi - lo, 1e-6), 0, 1)


def load_local_masks(v2_root: Path, well: str, bbox_size: int):
    full_masks = tif.imread(v2_root / f"{well}_Neuron001_mask_tyx.ome.tif").astype(bool)
    bbox = pd.read_csv(v2_root / f"{well}_Neuron001_bbox.csv")
    if len(bbox) != full_masks.shape[0]:
        raise RuntimeError(f"{well}: bbox rows {len(bbox)} != mask timepoints {full_masks.shape[0]}")
    local = []
    for i, row in bbox.iterrows():
        y0, y1 = int(row.y0), int(row.y1)
        x0, x1 = int(row.x0), int(row.x1)
        crop = full_masks[i, y0:y1, x0:x1]
        if crop.shape != (bbox_size, bbox_size):
            raise RuntimeError(f"{well} t={i}: expected {(bbox_size,bbox_size)} local mask, got {crop.shape}")
        local.append(crop)
    return np.stack(local), bbox


def keep_component_near_center(mask: np.ndarray, reference: np.ndarray | None = None):
    labels = measure.label(mask)
    if labels.max() == 0:
        return np.zeros_like(mask, dtype=bool)
    h, w = mask.shape
    cy0, cx0 = (h - 1) / 2.0, (w - 1) / 2.0
    ref_dil = morphology.dilation(reference, morphology.disk(6)) if reference is not None and reference.any() else None
    scored = []
    for prop in measure.regionprops(labels):
        comp = labels == prop.label
        cy, cx = prop.centroid
        d = float(np.hypot(cy-cy0, cx-cx0))
        overlap = float((comp & ref_dil).sum() / max(comp.sum(),1)) if ref_dil is not None else 0.0
        score = 2.0 * overlap + math.exp(-d/18.0) + min(float(prop.area)/500.0, 1.0)
        scored.append((score, comp))
    return max(scored, key=lambda x: x[0])[1]


def build_fixed_support(local_masks: np.ndarray, metrics: pd.DataFrame,
                        consensus_fraction: float, dilation_px: int,
                        min_area: int, max_area: int):
    valid = metrics["metrics_valid"].astype(bool).to_numpy()
    candidates = local_masks[valid]
    if len(candidates) < 2:
        raise RuntimeError(f"Need >=2 QC-valid masks for fixed support; found {len(candidates)}")

    count = candidates.sum(axis=0)
    required = max(2, int(math.ceil(consensus_fraction * len(candidates))))
    support = count >= required
    support = morphology.closing(support, morphology.disk(1))
    support = binary_fill_holes(support)
    support = morphology.remove_small_objects(support.astype(bool), max_size=24)
    support = keep_component_near_center(support, reference=local_masks[0])
    if dilation_px > 0:
        support = morphology.dilation(support, morphology.disk(dilation_px))
    support = binary_fill_holes(support)

    area = int(support.sum())
    method = f"consensus_qc_valid_masks_required_{required}_of_{len(candidates)}"
    if area < min_area:
        # Conservative fallback: Day-8 morphology, mildly dilated. This keeps a fixed
        # support while avoiding acceptance of a tiny consensus core.
        support = morphology.dilation(local_masks[0], morphology.disk(max(1, dilation_px)))
        support = binary_fill_holes(support)
        support = keep_component_near_center(support, reference=local_masks[0])
        area = int(support.sum())
        method = "day8_488_mask_fixed_support_fallback"
    if area < min_area or area > max_area:
        raise RuntimeError(f"Fixed support area {area} outside [{min_area}, {max_area}]")
    return support.astype(bool), required, int(len(candidates)), method


def dog_puncta(mcherry_corr: np.ndarray, mask: np.ndarray, min_size: int):
    x = mcherry_corr.astype(np.float32)
    dog = gaussian_filter(x, 1.0) - gaussian_filter(x, 3.0)
    vals = dog[mask]
    med = float(np.median(vals))
    mad = float(np.median(np.abs(vals-med)))
    robust_sigma = 1.4826 * mad
    threshold = max(med + 4.0 * robust_sigma, float(np.percentile(vals, 97.5)))
    puncta = (dog > threshold) & mask
    puncta = morphology.remove_small_objects(puncta, max_size=max(0, min_size-1))
    labels = measure.label(puncta)
    props = measure.regionprops(labels, intensity_image=x)
    return puncta, props, threshold


def quantify(mcherry: np.ndarray, fixed_mask: np.ndarray, background_exclusion: int, puncta_min_size: int):
    exclusion = morphology.dilation(fixed_mask, morphology.disk(background_exclusion))
    bg_region = ~exclusion
    if int(bg_region.sum()) < 50:
        bg_region = ~fixed_mask
    background = float(np.median(mcherry[bg_region])) if bg_region.any() else 0.0
    corr = np.clip(mcherry.astype(np.float32) - background, 0, None)
    puncta, props, dog_thr = dog_puncta(corr, fixed_mask, puncta_min_size)
    diffuse_mask = fixed_mask & ~puncta
    area = int(fixed_mask.sum())
    total = float(corr[fixed_mask].sum(dtype=np.float64))
    punctate = float(corr[puncta].sum(dtype=np.float64))
    diffuse = float(corr[diffuse_mask].sum(dtype=np.float64))
    count = int(len(props))
    pmeans = [float(p.intensity_mean) for p in props]
    pareas = [float(p.area) for p in props]
    ratio = diffuse / punctate if punctate > 0 else math.nan
    return {
        "fixed_support_area": area,
        "local_background_median_561": background,
        "total_mcherry_intensity": total,
        "diffuse_mcherry_integrated_intensity": diffuse,
        "diffuse_mcherry_mean_intensity": float(corr[diffuse_mask].mean()) if diffuse_mask.any() else math.nan,
        "punctate_mcherry_integrated_intensity": punctate,
        "puncta_count": count,
        "puncta_density_per_area": count / area,
        "mean_puncta_intensity": float(np.mean(pmeans)) if pmeans else math.nan,
        "median_puncta_area": float(np.median(pareas)) if pareas else math.nan,
        "diffuse_to_punctate_ratio": ratio,
        "rupture_like_score": ratio,
        "dog_threshold": dog_thr,
    }, puncta


def make_frame(well: str, day: int, ch488: np.ndarray, ch561: np.ndarray,
               fixed_mask: np.ndarray, puncta: np.ndarray, row: dict,
               lim488, lim561):
    green = normalize(ch488, lim488)
    red = normalize(ch561, lim561)
    merge = np.zeros((*green.shape, 3), dtype=np.float32)
    merge[...,0] = red
    merge[...,1] = green

    fig = plt.figure(figsize=(12.8,7.2), dpi=100)
    gs = fig.add_gridspec(2,3, height_ratios=[5,1.35], hspace=0.08, wspace=0.04)
    axes = [fig.add_subplot(gs[0,i]) for i in range(3)]
    axes[0].imshow(green, cmap="gray", vmin=0, vmax=1, interpolation="nearest")
    axes[1].imshow(red, cmap="magma", vmin=0, vmax=1, interpolation="nearest")
    axes[2].imshow(merge, vmin=0, vmax=1, interpolation="nearest")
    titles = ("488 soma-centered", "561 / mCherry", "488 + mCherry")
    mid = (green.shape[0]-1)/2.0
    for ax,title in zip(axes,titles):
        ax.set_title(title, fontsize=12)
        ax.set_axis_off()
        ax.plot([mid-4,mid+4],[mid,mid], lw=0.7, alpha=0.7)
        ax.plot([mid,mid],[mid-4,mid+4], lw=0.7, alpha=0.7)
    axes[0].contour(fixed_mask.astype(float), levels=[0.5], linewidths=0.7)
    axes[1].contour(fixed_mask.astype(float), levels=[0.5], linewidths=0.7)
    if puncta.any():
        axes[2].contour(puncta.astype(float), levels=[0.5], linewidths=0.6)

    txt = fig.add_subplot(gs[1,:]); txt.axis("off")
    ratio = row["diffuse_to_punctate_ratio"]
    ratio_txt = "NA" if not np.isfinite(ratio) else f"{ratio:.3f}"
    header = f"{well} | {CONDITION.get(well,'')} | Day {day} | fixed soma-centered support"
    metrics = (
        f"Puncta: {int(row['puncta_count'])}    Diffuse/Punctate: {ratio_txt}    "
        f"Background: {row['local_background_median_561']:.1f}    "
        f"488 template score: {row['template_match_score']:.3f}    "
        f"Tracking QC: {'PASS' if row['metrics_valid'] else 'REVIEW'}"
    )
    note = "Same fixed 488-derived support mask is used on every day; mCherry never defines tracking or ROI geometry."
    txt.text(0.01,0.78,header,fontsize=15,weight="bold",va="top")
    txt.text(0.01,0.43,metrics,fontsize=11,va="top")
    txt.text(0.01,0.10,note,fontsize=9,va="top")
    canvas = FigureCanvasAgg(fig); canvas.draw()
    rgb = np.asarray(canvas.buffer_rgba())[...,:3].copy()
    plt.close(fig)
    return rgb


def write_qc(well: str, days, bbox_stack, fixed_mask, old_metrics, out_path, alignment_channel, mcherry_channel):
    n = len(days)
    fig, axes = plt.subplots(2,n, figsize=(3*n,6), constrained_layout=True)
    lim488 = robust_limits(bbox_stack[:,alignment_channel])
    lim561 = robust_limits(bbox_stack[:,mcherry_channel])
    for i,day in enumerate(days):
        axes[0,i].imshow(normalize(bbox_stack[i,alignment_channel], lim488), cmap="gray", vmin=0,vmax=1, interpolation="nearest")
        axes[0,i].contour(fixed_mask.astype(float), levels=[0.5], linewidths=0.8)
        axes[0,i].set_title(f"D{day} score={old_metrics.iloc[i]['template_match_score']:.2f}")
        axes[1,i].imshow(normalize(bbox_stack[i,mcherry_channel], lim561), cmap="magma", vmin=0,vmax=1, interpolation="nearest")
        axes[1,i].contour(fixed_mask.astype(float), levels=[0.5], linewidths=0.8)
        axes[1,i].set_title("fixed support")
    for ax in axes.ravel(): ax.set_axis_off()
    fig.suptitle(f"{well}: one fixed 488 consensus support used for all {n} visits", fontsize=16)
    fig.savefig(out_path, dpi=160)
    plt.close(fig)


def main():
    args = parse_args()
    args.output_root.mkdir(parents=True, exist_ok=True)
    if shutil.which("ffmpeg") is None:
        try:
            import imageio_ffmpeg  # noqa: F401
        except Exception as exc:
            raise RuntimeError("MP4 export needs ffmpeg or imageio-ffmpeg") from exc

    all_rows = []
    for well in args.wells:
        bbox_path = args.v2_root / f"{well}_Neuron001_bbox_tcyx.ome.tif"
        metrics_path = args.v2_root / f"{well}_Neuron001_metrics.csv"
        if not bbox_path.exists() or not metrics_path.exists():
            raise FileNotFoundError(f"Missing v2 outputs for {well}")
        bbox_stack = tif.imread(bbox_path)
        old = pd.read_csv(metrics_path)
        if bbox_stack.ndim != 4 or bbox_stack.shape[0] != len(args.days):
            raise RuntimeError(f"{well}: unexpected bbox stack shape {bbox_stack.shape}")
        bbox_size = int(bbox_stack.shape[-1])
        local_masks, bbox_df = load_local_masks(args.v2_root, well, bbox_size)

        fixed_mask, required, n_valid_masks, support_method = build_fixed_support(
            local_masks, old, args.consensus_fraction, args.support_dilation,
            args.min_support_area, args.max_support_area,
        )

        rows = []
        puncta_masks = []
        for i,day in enumerate(args.days):
            oldrow = old.iloc[i]
            tracking_ok = bool(
                np.isfinite(oldrow["template_match_score"]) and
                (i == 0 or float(oldrow["template_match_score"]) >= args.min_template_score)
            )
            q, puncta = quantify(
                bbox_stack[i,args.mcherry_channel], fixed_mask,
                args.background_exclusion, args.puncta_min_size,
            )
            adaptive_local = local_masks[i]
            intersection = int((adaptive_local & fixed_mask).sum())
            adaptive_overlap = intersection / max(int(adaptive_local.sum()),1) if adaptive_local.any() else math.nan
            fixed_covered = intersection / max(int(fixed_mask.sum()),1)
            row = {
                "well": well,
                "condition": CONDITION.get(well,""),
                "time_index": i,
                "day": day,
                "cell_roi_id": f"{well}_Neuron001",
                "mask_source": "fixed_488_consensus_support_in_soma_centered_coordinates",
                "fixed_support_method": support_method,
                "fixed_support_required_visits": required,
                "fixed_support_valid_masks_used": n_valid_masks,
                "template_match_score": float(oldrow["template_match_score"]),
                "anchor_y": float(oldrow["anchor_y"]),
                "anchor_x": float(oldrow["anchor_x"]),
                "tracking_qc_pass": tracking_ok,
                "adaptive_v2_metrics_valid": bool(oldrow["metrics_valid"]),
                "adaptive_v2_segmentation_area": int(oldrow["segmentation_area"]),
                "adaptive_v2_overlap_fraction_of_adaptive": adaptive_overlap,
                "adaptive_v2_fraction_of_fixed_support_covered": fixed_covered,
                "metrics_valid": tracking_ok,
                "interpretation": "fixed-support longitudinal screening metric for punctate-to-diffuse redistribution; not proof of rupture",
            }
            row.update(q)
            rows.append(row)
            all_rows.append(row)
            puncta_masks.append(puncta)

        df = pd.DataFrame(rows)
        df.to_csv(args.output_root / f"{well}_Neuron001_metrics.csv", index=False)
        tif.imwrite(args.output_root / f"{well}_Neuron001_fixed_support_mask_yx.ome.tif",
                    fixed_mask.astype(np.uint8), metadata={"axes":"YX"})
        tif.imwrite(args.output_root / f"{well}_Neuron001_puncta_mask_tyx.ome.tif",
                    np.stack(puncta_masks).astype(np.uint8), metadata={"axes":"TYX"})
        # Copy centered bbox stack so pair renderer can point directly at this output root.
        tif.imwrite(args.output_root / f"{well}_Neuron001_bbox_tcyx.ome.tif",
                    bbox_stack, metadata={"axes":"TCYX"})
        bbox_df.to_csv(args.output_root / f"{well}_Neuron001_bbox.csv", index=False)

        write_qc(well, args.days, bbox_stack, fixed_mask, old,
                 args.output_root / f"{well}_Neuron001_fixed_support_qc.png",
                 args.alignment_channel, args.mcherry_channel)

        lim488 = robust_limits(bbox_stack[:,args.alignment_channel])
        lim561 = robust_limits(bbox_stack[:,args.mcherry_channel])
        mp4 = args.output_root / f"{well}_Neuron001_bbox_timelapse.mp4"
        writer = imageio.get_writer(mp4, fps=args.fps, codec="libx264", quality=8, macro_block_size=1)
        repeats = max(1, int(round(args.fps * args.hold_seconds)))
        try:
            for i,day in enumerate(args.days):
                frame = make_frame(
                    well, day, bbox_stack[i,args.alignment_channel], bbox_stack[i,args.mcherry_channel],
                    fixed_mask, puncta_masks[i], rows[i], lim488, lim561,
                )
                for _ in range(repeats): writer.append_data(frame)
        finally:
            writer.close()
        print(f"Wrote {well}: fixed support area={int(fixed_mask.sum())} px; tracking-valid {int(df.metrics_valid.sum())}/{len(df)}")

    pd.DataFrame(all_rows).to_csv(args.output_root / "all_six_neuron_metrics.csv", index=False)
    print(f"All fixed-support outputs: {args.output_root}")


if __name__ == "__main__":
    main()
