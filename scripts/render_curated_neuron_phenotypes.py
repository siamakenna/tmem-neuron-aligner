#!/usr/bin/env python3
"""Render tight-ROI longitudinal phenotype videos from an existing TMEM106B v2 atlas.

This script DOES NOT retrack neurons. It reuses the stored v2 488 anchors and the
registered source stacks, keeping the existing 128x128 soma-centered crops unchanged.

For each requested neuron:
1. Reconstruct the nine 128x128 crops from the stored v2 anchor coordinates.
2. Recompute 488-only local masks at those fixed anchors.
3. Build a TIGHT identity core from a >=60% longitudinal consensus, with no dilation.
4. Build a phenotype ROI as identity core + 1 px dilation.
5. Run an explicit second-soma screen on the longitudinal median 488 reference.
6. Quantify background-corrected 561/mCherry inside the phenotype ROI.
7. Detect puncta with the existing DoG sigma1-sigma3 method.
8. Render a 2x2 audit video:
      488 identity | raw 561
      puncta       | diffuse residual
   with fixed longitudinal display scales.

mCherry never determines identity, tracking, or ROI geometry.

The second-soma screen is a conservative automated review flag, not a definitive
biological classifier. Its purpose is to identify F05_N025-like multi-soma crops for
manual exclusion/review before phenotype inference.
"""
from __future__ import annotations

import argparse
import gc
import math
import shutil
from dataclasses import dataclass
from pathlib import Path

import imageio.v2 as imageio
import numpy as np
import pandas as pd
import tifffile as tif
from PIL import Image, ImageDraw, ImageFont
from scipy.ndimage import binary_fill_holes, gaussian_filter
from skimage import filters, measure, morphology
from skimage.feature import peak_local_max

from make_soma_anchored_bbox_movies_v2 import robust01, segment_neuron_in_box, square_bounds

DAYS_DEFAULT = [8, 12, 16, 20, 25, 29, 32, 36, 39]


@dataclass
class SomaScreen:
    single_soma_pass: bool
    secondary_soma_score: float
    secondary_soma_distance_px: float
    secondary_soma_area_ratio: float
    secondary_peak_ratio: float
    primary_y: float
    primary_x: float
    secondary_y: float
    secondary_x: float
    n_candidate_peaks: int


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--atlas-root", type=Path, required=True,
                   help="Existing multi_neuron_atlas_v2 directory. Never modified.")
    p.add_argument("--output-root", type=Path, required=True)
    p.add_argument("--neuron-ids", nargs="*", default=[])
    p.add_argument("--video-manifest", type=Path, default=None,
                   help="Optional atlas video_manifest.csv; adds all neuron IDs in video_rank order.")
    p.add_argument("--days", nargs="+", type=int, default=DAYS_DEFAULT)
    p.add_argument("--alignment-channel", type=int, default=2)
    p.add_argument("--mcherry-channel", type=int, default=1)
    p.add_argument("--bbox-size", type=int, default=128)

    p.add_argument("--identity-consensus-fraction", type=float, default=0.60)
    p.add_argument("--phenotype-dilation", type=int, default=1)
    p.add_argument("--min-core-area", type=int, default=80)
    p.add_argument("--max-core-area", type=int, default=2500)
    p.add_argument("--segmentation-min-area", type=int, default=180)

    p.add_argument("--background-exclusion", type=int, default=8)
    p.add_argument("--puncta-min-size", type=int, default=6)

    p.add_argument("--secondary-search-radius", type=float, default=52.0)
    p.add_argument("--secondary-min-distance", type=int, default=14)
    p.add_argument("--secondary-peak-ratio-threshold", type=float, default=0.55)
    p.add_argument("--secondary-area-ratio-threshold", type=float, default=0.30)
    p.add_argument("--secondary-score-threshold", type=float, default=0.40)

    p.add_argument("--fps", type=int, default=10)
    p.add_argument("--hold-seconds", type=float, default=1.0)
    return p.parse_args()


def resample_nearest():
    return getattr(getattr(Image, "Resampling", Image), "NEAREST")


def normalize_u8(x: np.ndarray, limits) -> np.ndarray:
    lo, hi = map(float, limits)
    y = np.clip((x.astype(np.float32) - lo) / max(hi - lo, 1e-6), 0, 1)
    return (255 * y).astype(np.uint8)


def robust_limits(stack: np.ndarray, lo=1.0, hi=99.6):
    x = np.asarray(stack, dtype=np.float32)
    return float(np.percentile(x, lo)), float(max(np.percentile(x, hi), np.percentile(x, lo) + 1e-6))


def mask_outline(mask: np.ndarray) -> np.ndarray:
    if not np.any(mask):
        return np.zeros_like(mask, dtype=bool)
    return mask & ~morphology.erosion(mask, morphology.disk(1))


def keep_component_near_center(mask: np.ndarray, reference: np.ndarray | None = None) -> np.ndarray:
    labels = measure.label(mask)
    if labels.max() == 0:
        return np.zeros_like(mask, dtype=bool)
    h, w = mask.shape
    cy0, cx0 = (h - 1) / 2.0, (w - 1) / 2.0
    ref_dil = morphology.dilation(reference, morphology.disk(4)) if reference is not None and np.any(reference) else None
    scored = []
    for prop in measure.regionprops(labels):
        comp = labels == prop.label
        cy, cx = prop.centroid
        d = float(np.hypot(cy - cy0, cx - cx0))
        overlap = float((comp & ref_dil).sum() / max(comp.sum(), 1)) if ref_dil is not None else 0.0
        center_bonus = math.exp(-d / 14.0)
        area_bonus = min(float(prop.area) / 400.0, 1.0)
        scored.append((3.0 * overlap + 1.5 * center_bonus + 0.4 * area_bonus, comp))
    return max(scored, key=lambda z: z[0])[1]


def build_tight_identity_core(local_masks: np.ndarray, valid_mask: np.ndarray,
                              consensus_fraction: float, min_area: int, max_area: int):
    candidates = local_masks[np.asarray(valid_mask, dtype=bool)]
    if len(candidates) < 3:
        raise RuntimeError(f"Need >=3 valid 488 masks for tight consensus; found {len(candidates)}")
    required = max(3, int(math.ceil(float(consensus_fraction) * len(candidates))))
    count = candidates.sum(axis=0)
    core = count >= required
    core = morphology.closing(core, morphology.disk(1))
    core = binary_fill_holes(core)
    core = morphology.remove_small_objects(core.astype(bool), max_size=24)
    core = keep_component_near_center(core, reference=candidates[0])
    core = binary_fill_holes(core)
    area = int(core.sum())
    if area < min_area or area > max_area:
        raise RuntimeError(
            f"Tight identity-core area {area} outside [{min_area}, {max_area}] "
            f"at consensus {required}/{len(candidates)}"
        )
    method = f"tight_488_consensus_{required}_of_{len(candidates)}_fraction_{consensus_fraction:.2f}_dilation_0"
    return core.astype(bool), required, len(candidates), method


def _disk_values(image: np.ndarray, y: float, x: float, radius: float, threshold: float | None = None):
    yy, xx = np.ogrid[:image.shape[0], :image.shape[1]]
    m = (yy - y) ** 2 + (xx - x) ** 2 <= radius ** 2
    if threshold is not None:
        m &= image >= threshold
    return m


def screen_secondary_soma(reference488: np.ndarray, *, search_radius: float,
                          min_distance: int, peak_ratio_threshold: float,
                          area_ratio_threshold: float, score_threshold: float) -> SomaScreen:
    """Conservative second-soma review screen on the longitudinal median 488 crop.

    Peaks are detected in a smoothed, robustly normalized 488 reference. The target
    (primary) peak is the strongest local maximum within 18 px of crop center. A
    second peak is considered soma-like only if it is spatially separated and has
    both substantial peak intensity and substantial local high-signal area relative
    to the primary soma.
    """
    ref = np.asarray(reference488, dtype=np.float32)
    smooth = gaussian_filter(ref, sigma=2.0)
    h, w = smooth.shape
    cy, cx = (h - 1) / 2.0, (w - 1) / 2.0
    yy, xx = np.ogrid[:h, :w]
    search = (yy - cy) ** 2 + (xx - cx) ** 2 <= float(search_radius) ** 2
    vals = smooth[search]
    if vals.size < 100:
        raise RuntimeError("Secondary-soma search region too small")

    try:
        otsu = float(filters.threshold_otsu(vals))
    except ValueError:
        otsu = float(np.percentile(vals, 75))
    peak_thr = max(otsu, float(np.percentile(vals, 82)))

    peaks = peak_local_max(
        smooth,
        min_distance=int(min_distance),
        threshold_abs=peak_thr,
        exclude_border=False,
        labels=search.astype(np.uint8),
    )
    if len(peaks) == 0:
        # The crop center itself is the fallback target location.
        peaks = np.array([[int(round(cy)), int(round(cx))]], dtype=int)

    # Primary = strongest peak close to the tracked center; if none is close,
    # use the nearest peak. This does not alter the stored tracking anchor.
    close = []
    for k, (py, px) in enumerate(peaks):
        d = float(np.hypot(py - cy, px - cx))
        if d <= 18:
            close.append((float(smooth[py, px]), -d, k))
    if close:
        primary_idx = max(close)[2]
    else:
        primary_idx = int(np.argmin([np.hypot(py - cy, px - cx) for py, px in peaks]))

    py, px = map(float, peaks[primary_idx])
    pval = float(smooth[int(py), int(px)])
    bg = float(np.percentile(vals, 45))
    common_thr = bg + 0.35 * max(pval - bg, 1e-6)
    parea = int(_disk_values(smooth, py, px, 12.0, common_thr).sum())
    parea = max(parea, 1)

    best = None
    for k, (syi, sxi) in enumerate(peaks):
        if k == primary_idx:
            continue
        sy, sx = float(syi), float(sxi)
        dist = float(np.hypot(sy - py, sx - px))
        if dist < float(min_distance) or dist > float(search_radius):
            continue
        sval = float(smooth[syi, sxi])
        peak_ratio = max(0.0, (sval - bg) / max(pval - bg, 1e-6))
        sarea = int(_disk_values(smooth, sy, sx, 12.0, common_thr).sum())
        area_ratio = float(sarea / parea)
        score = float(peak_ratio * math.sqrt(max(area_ratio, 0.0)))
        candidate = (score, peak_ratio, area_ratio, dist, sy, sx)
        if best is None or candidate[0] > best[0]:
            best = candidate

    if best is None:
        return SomaScreen(True, 0.0, math.nan, 0.0, 0.0, py, px, math.nan, math.nan, int(len(peaks)))

    score, peak_ratio, area_ratio, dist, sy, sx = best
    fail = bool(
        score >= score_threshold
        and peak_ratio >= peak_ratio_threshold
        and area_ratio >= area_ratio_threshold
    )
    return SomaScreen(
        not fail, float(score), float(dist), float(area_ratio), float(peak_ratio),
        py, px, sy, sx, int(len(peaks))
    )


def quantify_phenotype(mcherry: np.ndarray, roi: np.ndarray, background_exclusion: int,
                       puncta_min_size: int):
    exclusion = morphology.dilation(roi, morphology.disk(int(background_exclusion)))
    bg_region = ~exclusion
    if int(bg_region.sum()) < 50:
        bg_region = ~roi
    background = float(np.median(mcherry[bg_region])) if np.any(bg_region) else 0.0
    corrected = np.clip(mcherry.astype(np.float32) - background, 0, None)

    dog = gaussian_filter(corrected, 1.0) - gaussian_filter(corrected, 3.0)
    vals = dog[roi]
    if vals.size == 0:
        raise RuntimeError("Phenotype ROI is empty")
    med = float(np.median(vals))
    mad = float(np.median(np.abs(vals - med)))
    robust_sigma = 1.4826 * mad
    dog_thr = max(med + 4.0 * robust_sigma, float(np.percentile(vals, 97.5)))
    puncta = (dog > dog_thr) & roi
    puncta = morphology.remove_small_objects(puncta, max_size=max(0, int(puncta_min_size) - 1))
    labels = measure.label(puncta)
    props = measure.regionprops(labels, intensity_image=corrected)
    diffuse_mask = roi & ~puncta

    area = int(roi.sum())
    total = float(corrected[roi].sum(dtype=np.float64))
    punctate = float(corrected[puncta].sum(dtype=np.float64))
    diffuse = float(corrected[diffuse_mask].sum(dtype=np.float64))
    count = int(len(props))
    pmeans = [float(p.intensity_mean) for p in props]
    pareas = [float(p.area) for p in props]
    ratio = diffuse / punctate if punctate > 0 else math.nan
    metrics = {
        "phenotype_roi_area": area,
        "local_background_median_561": background,
        "total_mcherry_intensity": total,
        "diffuse_mcherry_integrated_intensity": diffuse,
        "diffuse_mcherry_mean_intensity": float(corrected[diffuse_mask].mean()) if np.any(diffuse_mask) else math.nan,
        "punctate_mcherry_integrated_intensity": punctate,
        "puncta_count": count,
        "puncta_density_per_area": count / area if area else math.nan,
        "mean_puncta_intensity": float(np.mean(pmeans)) if pmeans else math.nan,
        "median_puncta_area": float(np.median(pareas)) if pareas else math.nan,
        "diffuse_to_punctate_ratio": ratio,
        "dog_threshold": dog_thr,
    }
    return metrics, puncta.astype(bool), diffuse_mask.astype(bool), corrected


def reconstruct_masks(boxes: np.ndarray, track_rows: pd.DataFrame, alignment_channel: int,
                      bbox_size: int, segmentation_min_area: int):
    masks = []
    seg_valid = []
    seg_meta = []
    prev_valid_mask = None
    day8_mask = None
    ref_area = None

    for i, (_, row) in enumerate(track_rows.iterrows()):
        f488 = boxes[i, alignment_channel]
        # Anchors were used to center each 128x128 box. Keep their exact subpixel
        # position within the crop for segmentation only.
        local_ay = float(row["anchor_y"] - row["bbox_y0"])
        local_ax = float(row["anchor_x"] - row["bbox_x0"])
        tracking_ok = bool(row.get("tracking_valid", True))
        try:
            prior = prev_valid_mask if prev_valid_mask is not None else day8_mask
            prior_source = "previous_valid_tight_input" if prev_valid_mask is not None else ("day8_input" if day8_mask is not None else "none")
            seg, meta = segment_neuron_in_box(
                f488, local_ay, local_ax, bbox_size, segmentation_min_area,
                ref_area=ref_area, prior_mask=prior, prior_source=prior_source,
            )
            area = int(meta["segmentation_area"])
            if i == 0:
                ref_area = area
                day8_mask = seg.copy()
            ratio = area / ref_area if ref_area else math.nan
            ok = bool(
                tracking_ok
                and area >= segmentation_min_area
                and np.isfinite(ratio) and 0.30 <= ratio <= 2.5
                and float(meta["segmentation_centroid_offset_from_anchor"]) <= 24.0
                and not bool(meta["segmentation_border_touch"])
            )
            if ok:
                prev_valid_mask = seg.copy()
            masks.append(seg.astype(bool))
            seg_valid.append(ok)
            seg_meta.append({"adaptive_area": area, "adaptive_valid_recomputed": ok,
                             "adaptive_centroid_offset": float(meta["segmentation_centroid_offset_from_anchor"]),
                             "adaptive_method": meta.get("segmentation_method", "")})
        except Exception as exc:
            masks.append(np.zeros((bbox_size, bbox_size), dtype=bool))
            seg_valid.append(False)
            seg_meta.append({"adaptive_area": 0, "adaptive_valid_recomputed": False,
                             "adaptive_centroid_offset": math.nan,
                             "adaptive_method": f"failed: {exc}"})
    return np.stack(masks), np.asarray(seg_valid, dtype=bool), pd.DataFrame(seg_meta)


def build_reference_488(boxes: np.ndarray, alignment_channel: int, valid: np.ndarray):
    imgs = []
    for i in range(len(boxes)):
        if valid[i]:
            imgs.append(robust01(boxes[i, alignment_channel]).astype(np.float32))
    if not imgs:
        imgs = [robust01(x).astype(np.float32) for x in boxes[:, alignment_channel]]
    return np.median(np.stack(imgs), axis=0).astype(np.float32)


def draw_outline(rgb: np.ndarray, mask: np.ndarray, color=(255, 255, 255)):
    out = rgb.copy()
    out[mask_outline(mask)] = np.asarray(color, dtype=np.uint8)
    return out


def draw_secondary_marker(im: Image.Image, screen: SomaScreen, scale: float):
    if not np.isfinite(screen.secondary_y) or not np.isfinite(screen.secondary_x):
        return
    draw = ImageDraw.Draw(im)
    x = screen.secondary_x * scale
    y = screen.secondary_y * scale
    r = 8 * scale
    color = (255, 80, 80) if not screen.single_soma_pass else (255, 200, 80)
    draw.ellipse((x-r, y-r, x+r, y+r), outline=color, width=max(1, int(round(scale))))


def render_video(path: Path, neuron_id: str, days, boxes, core, roi, puncta_masks,
                 diffuse_masks, corrected_stack, metrics: pd.DataFrame, screen: SomaScreen,
                 alignment_channel: int, mcherry_channel: int, fps: int, hold_seconds: float):
    path.parent.mkdir(parents=True, exist_ok=True)
    lim488 = robust_limits(boxes[:, alignment_channel])
    lim561raw = robust_limits(boxes[:, mcherry_channel])
    roi_vals = np.concatenate([corrected_stack[i][roi].ravel() for i in range(len(corrected_stack))])
    corr_hi = float(np.percentile(roi_vals, 99.6)) if roi_vals.size else 1.0
    corr_lim = (0.0, max(corr_hi, 1.0))

    panel = 320
    scale = panel / boxes.shape[-1]
    header_h = 38
    footer_h = 82
    repeats = max(1, int(round(fps * hold_seconds)))
    font = ImageFont.load_default()
    rs = resample_nearest()
    writer = imageio.get_writer(path, fps=fps, codec="libx264", quality=8, macro_block_size=1)

    try:
        for i, day in enumerate(days):
            # 488 identity panel: fixed tight core only.
            a = normalize_u8(boxes[i, alignment_channel], lim488)
            rgb488 = np.stack([a, a, a], axis=-1)
            rgb488 = draw_outline(rgb488, core, (255, 255, 255))
            im488 = Image.fromarray(rgb488).resize((panel, panel), rs)
            draw_secondary_marker(im488, screen, scale)

            # Raw 561 panel: one fixed scale across all 9 days.
            raw561 = normalize_u8(boxes[i, mcherry_channel], lim561raw)
            imraw = Image.fromarray(raw561, "L").convert("RGB").resize((panel, panel), rs)

            # Puncta panel: background-corrected 561 with phenotype ROI + puncta overlay.
            corr = normalize_u8(corrected_stack[i], corr_lim)
            rgbp = np.stack([corr, corr, corr], axis=-1)
            rgbp = draw_outline(rgbp, roi, (255, 255, 255))
            # Fill detected puncta in red so the algorithm is visually auditable.
            rgbp[puncta_masks[i]] = np.array([255, 40, 40], dtype=np.uint8)
            imp = Image.fromarray(rgbp).resize((panel, panel), rs)

            # Diffuse residual: same corrected scale, only non-punctate ROI pixels retained.
            diff = np.zeros_like(corrected_stack[i], dtype=np.float32)
            diff[diffuse_masks[i]] = corrected_stack[i][diffuse_masks[i]]
            d8 = normalize_u8(diff, corr_lim)
            rgbd = np.stack([d8, d8, d8], axis=-1)
            rgbd = draw_outline(rgbd, roi, (255, 255, 255))
            imd = Image.fromarray(rgbd).resize((panel, panel), rs)

            canvas = Image.new("RGB", (panel * 2, header_h + panel * 2 + footer_h), "black")
            canvas.paste(im488, (0, header_h))
            canvas.paste(imraw, (panel, header_h))
            canvas.paste(imp, (0, header_h + panel))
            canvas.paste(imd, (panel, header_h + panel))
            dr = ImageDraw.Draw(canvas)
            well = neuron_id.split("_")[0]
            soma_txt = "PASS" if screen.single_soma_pass else "FAIL/REVIEW"
            dr.text((8, 6), f"{neuron_id} | Day {day} | single-soma screen: {soma_txt}", fill="white", font=font)
            dr.text((8, 23), "488 identity core", fill="white", font=font)
            dr.text((panel + 8, 23), "raw 561 mCherry (fixed 9-day scale)", fill="white", font=font)
            dr.text((8, header_h + panel + 5), "puncta overlay (red)", fill="white", font=font)
            dr.text((panel + 8, header_h + panel + 5), "diffuse residual (puncta removed)", fill="white", font=font)

            r = metrics.iloc[i]
            base_y = header_h + panel * 2 + 8
            ratio = r["diffuse_to_punctate_ratio"]
            ratio_txt = "NA" if not np.isfinite(ratio) else f"{ratio:.3f}"
            dr.text((8, base_y),
                    f"puncta={int(r['puncta_count'])}  diffuse_mean={r['diffuse_mcherry_mean_intensity']:.1f}  "
                    f"punctate_int={r['punctate_mcherry_integrated_intensity']:.0f}  D/P={ratio_txt}",
                    fill="white", font=font)
            dr.text((8, base_y + 17),
                    f"core={int(core.sum())}px  phenotypeROI={int(roi.sum())}px  "
                    f"2nd_score={screen.secondary_soma_score:.2f}  "
                    f"2nd_dist={screen.secondary_soma_distance_px:.1f}px" if np.isfinite(screen.secondary_soma_distance_px)
                    else f"core={int(core.sum())}px  phenotypeROI={int(roi.sum())}px  2nd_score=0.00  2nd_dist=NA",
                    fill="white", font=font)
            dr.text((8, base_y + 34),
                    "Identity/ROI geometry = 488 only. mCherry never drives tracking or mask geometry.",
                    fill="white", font=font)
            frame = np.asarray(canvas)
            for _ in range(repeats):
                writer.append_data(frame)
    finally:
        writer.close()


def render_identity_qc_png(path: Path, neuron_id: str, days, boxes, core, screen: SomaScreen,
                           alignment_channel: int):
    lim = robust_limits(boxes[:, alignment_channel])
    tile = 180
    rs = resample_nearest()
    canvas = Image.new("RGB", (tile * 3, tile * 3), "black")
    font = ImageFont.load_default()
    scale = tile / boxes.shape[-1]
    for i, day in enumerate(days[:9]):
        a = normalize_u8(boxes[i, alignment_channel], lim)
        rgb = np.stack([a, a, a], axis=-1)
        rgb = draw_outline(rgb, core, (255, 255, 255))
        im = Image.fromarray(rgb).resize((tile, tile), rs)
        draw_secondary_marker(im, screen, scale)
        d = ImageDraw.Draw(im)
        d.rectangle((2, 2, 118, 19), fill="black")
        d.text((5, 5), f"D{day} tight core", fill="white", font=font)
        canvas.paste(im, ((i % 3) * tile, (i // 3) * tile))
    path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(path)


def process_track(stack: np.ndarray, track: pd.DataFrame, neuron_id: str, args, outdir: Path):
    track = track.sort_values("time_index").copy()
    if len(track) != len(args.days):
        raise RuntimeError(f"{neuron_id}: expected {len(args.days)} rows, found {len(track)}")

    boxes = []
    for _, r in track.iterrows():
        ti = int(r["time_index"])
        cy, cx = float(r["anchor_y"]), float(r["anchor_x"])
        y0, y1, x0, x1 = square_bounds(cy, cx, args.bbox_size, stack.shape[-2], stack.shape[-1])
        box = stack[ti, :, y0:y1, x0:x1]
        if box.shape[-2:] != (args.bbox_size, args.bbox_size):
            raise RuntimeError(f"{neuron_id} D{r['day']}: crop shape {box.shape[-2:]} != {(args.bbox_size,args.bbox_size)}")
        boxes.append(box)
        # Preserve exact reconstruction bounds for local-anchor segmentation.
        track.loc[r.name, "bbox_y0"] = y0
        track.loc[r.name, "bbox_y1"] = y1
        track.loc[r.name, "bbox_x0"] = x0
        track.loc[r.name, "bbox_x1"] = x1
    boxes = np.stack(boxes)

    adaptive_masks, adaptive_valid, seg_meta = reconstruct_masks(
        boxes, track, args.alignment_channel, args.bbox_size, args.segmentation_min_area
    )
    core, required, nvalid, core_method = build_tight_identity_core(
        adaptive_masks, adaptive_valid, args.identity_consensus_fraction,
        args.min_core_area, args.max_core_area,
    )
    roi = morphology.dilation(core, morphology.disk(int(args.phenotype_dilation))) if args.phenotype_dilation > 0 else core.copy()
    roi = binary_fill_holes(roi).astype(bool)

    reference488 = build_reference_488(boxes, args.alignment_channel, adaptive_valid)
    screen = screen_secondary_soma(
        reference488,
        search_radius=args.secondary_search_radius,
        min_distance=args.secondary_min_distance,
        peak_ratio_threshold=args.secondary_peak_ratio_threshold,
        area_ratio_threshold=args.secondary_area_ratio_threshold,
        score_threshold=args.secondary_score_threshold,
    )

    metric_rows = []
    puncta_masks = []
    diffuse_masks = []
    corrected = []
    for i, (_, r) in enumerate(track.iterrows()):
        q, puncta, diffuse, corr = quantify_phenotype(
            boxes[i, args.mcherry_channel], roi,
            args.background_exclusion, args.puncta_min_size,
        )
        row = {
            "well": r["well"], "neuron_id": neuron_id,
            "time_index": int(r["time_index"]), "day": int(r["day"]),
            "anchor_y": float(r["anchor_y"]), "anchor_x": float(r["anchor_x"]),
            "tracking_valid_original": bool(r.get("tracking_valid", True)),
            "template_match_score": float(r.get("template_match_score", math.nan)),
            "adaptive_valid_recomputed": bool(adaptive_valid[i]),
            "identity_core_area": int(core.sum()),
            "identity_core_consensus_required": int(required),
            "identity_core_valid_masks": int(nvalid),
            "identity_core_method": core_method,
            "single_soma_pass": bool(screen.single_soma_pass),
            "secondary_soma_score": screen.secondary_soma_score,
            "secondary_soma_distance_px": screen.secondary_soma_distance_px,
            "secondary_soma_area_ratio": screen.secondary_soma_area_ratio,
            "secondary_peak_ratio": screen.secondary_peak_ratio,
        }
        row.update(seg_meta.iloc[i].to_dict())
        row.update(q)
        metric_rows.append(row)
        puncta_masks.append(puncta)
        diffuse_masks.append(diffuse)
        corrected.append(corr)

    metrics = pd.DataFrame(metric_rows)
    puncta_masks = np.stack(puncta_masks)
    diffuse_masks = np.stack(diffuse_masks)
    corrected = np.stack(corrected)

    prefix = outdir / neuron_id
    metrics.to_csv(prefix.with_name(prefix.name + "_tight_roi_metrics.csv"), index=False)
    tif.imwrite(prefix.with_name(prefix.name + "_identity_core_yx.ome.tif"), core.astype(np.uint8), metadata={"axes": "YX"})
    tif.imwrite(prefix.with_name(prefix.name + "_phenotype_roi_yx.ome.tif"), roi.astype(np.uint8), metadata={"axes": "YX"})
    tif.imwrite(prefix.with_name(prefix.name + "_puncta_mask_tyx.ome.tif"), puncta_masks.astype(np.uint8), metadata={"axes": "TYX"})
    render_identity_qc_png(
        prefix.with_name(prefix.name + "_tight_identity_qc.png"), neuron_id, args.days,
        boxes, core, screen, args.alignment_channel,
    )
    render_video(
        prefix.with_name(prefix.name + "_phenotype_audit.mp4"), neuron_id, args.days,
        boxes, core, roi, puncta_masks, diffuse_masks, corrected, metrics, screen,
        args.alignment_channel, args.mcherry_channel, args.fps, args.hold_seconds,
    )

    summary = {
        "well": str(track.iloc[0]["well"]),
        "neuron_id": neuron_id,
        "tracking_valid_days_original": int(pd.Series(track.get("tracking_valid", True)).astype(bool).sum()),
        "adaptive_valid_days_recomputed": int(adaptive_valid.sum()),
        "identity_core_area": int(core.sum()),
        "phenotype_roi_area": int(roi.sum()),
        "identity_consensus_fraction": float(args.identity_consensus_fraction),
        "identity_consensus_required": int(required),
        "identity_valid_masks_used": int(nvalid),
        "phenotype_dilation_px": int(args.phenotype_dilation),
        "single_soma_pass": bool(screen.single_soma_pass),
        "secondary_soma_score": screen.secondary_soma_score,
        "secondary_soma_distance_px": screen.secondary_soma_distance_px,
        "secondary_soma_area_ratio": screen.secondary_soma_area_ratio,
        "secondary_peak_ratio": screen.secondary_peak_ratio,
        "candidate_peaks_detected": screen.n_candidate_peaks,
        "auto_phenotype_use": "ELIGIBLE_FOR_MANUAL_REVIEW" if screen.single_soma_pass else "EXCLUDE_MULTI_SOMA_REVIEW",
        "phenotype_video": str(prefix.with_name(prefix.name + "_phenotype_audit.mp4")),
        "identity_qc_png": str(prefix.with_name(prefix.name + "_tight_identity_qc.png")),
    }
    return summary


def requested_ids(args) -> list[str]:
    ids = list(args.neuron_ids)
    if args.video_manifest is not None:
        vm = pd.read_csv(args.video_manifest)
        if "video_rank" in vm.columns:
            vm = vm.sort_values("video_rank")
        ids.extend(vm["neuron_id"].astype(str).tolist())
    # stable unique
    out = []
    seen = set()
    for x in ids:
        if x not in seen:
            out.append(x)
            seen.add(x)
    if not out:
        raise RuntimeError("No neuron IDs requested. Use --neuron-ids and/or --video-manifest.")
    return out


def main():
    args = parse_args()
    args.output_root.mkdir(parents=True, exist_ok=True)
    master_path = args.atlas_root / "all_neurons_longitudinal_master.csv"
    if not master_path.exists():
        raise FileNotFoundError(master_path)
    master = pd.read_csv(master_path)
    ids = requested_ids(args)

    missing = [nid for nid in ids if nid not in set(master["neuron_id"].astype(str))]
    if missing:
        raise RuntimeError(f"Requested neuron IDs missing from atlas: {missing}")

    summaries = []
    # Load one registered well stack at a time.
    for well, well_ids in pd.Series(ids).groupby(pd.Series(ids).str.split("_").str[0], sort=False):
        group_ids = well_ids.tolist()
        gm = master.loc[(master["well"].astype(str) == well) & master["neuron_id"].isin(group_ids)].copy()
        sources = gm["source_registered_stack"].dropna().astype(str).unique().tolist()
        if len(sources) != 1:
            raise RuntimeError(f"{well}: expected one source_registered_stack, found {sources}")
        source = Path(sources[0])
        print(f"Loading {well}: {source}", flush=True)
        stack = tif.imread(source)
        try:
            for nid in group_ids:
                print(f"Processing {nid}", flush=True)
                track = gm.loc[gm["neuron_id"] == nid].copy()
                try:
                    summaries.append(process_track(stack, track, nid, args, args.output_root))
                except Exception as exc:
                    print(f"ERROR {nid}: {exc}", flush=True)
                    summaries.append({
                        "well": well, "neuron_id": nid,
                        "single_soma_pass": False,
                        "auto_phenotype_use": "PROCESSING_FAILED",
                        "error": str(exc),
                    })
        finally:
            del stack
            gc.collect()

    summary = pd.DataFrame(summaries)
    summary.to_csv(args.output_root / "reference_renderer_summary.csv", index=False)

    readme = f"""TMEM106B tight-ROI phenotype renderer\n\nInput atlas (unchanged):\n{args.atlas_root}\n\nIdentity geometry:\n- Existing v2 488 anchors reused exactly; no retracking.\n- Bounding box remains {args.bbox_size}x{args.bbox_size}.\n- Tight identity core requires {args.identity_consensus_fraction:.2f} of recomputed QC-valid 488 masks.\n- Identity-core dilation: 0 px.\n- Phenotype ROI dilation: {args.phenotype_dilation} px.\n\nMulti-soma screen:\n- Conservative automated review flag on longitudinal median 488 reference.\n- A FAIL means phenotype use should be excluded/reviewed; it does not mean the center tracking failed.\n\nPhenotype display:\n- Raw 561 uses one fixed longitudinal scale per neuron.\n- Puncta use DoG sigma1-sigma3 and the existing robust threshold logic.\n- Diffuse residual is background-corrected 561 inside the phenotype ROI after puncta pixels are removed.\n- mCherry never drives tracking or ROI geometry.\n\nDo not promote these test outputs to final inference until manual review of the reference tracks passes.\n"""
    (args.output_root / "README_renderer_test.txt").write_text(readme)
    print("\nDONE", flush=True)
    print(summary.to_string(index=False), flush=True)
    print(f"Outputs: {args.output_root}", flush=True)


if __name__ == "__main__":
    main()
