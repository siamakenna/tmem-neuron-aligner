#!/usr/bin/env python3
"""High-throughput longitudinal neuron atlas for the six TMEM106B pilot wells.

Purpose
-------
- Detect all compact Day-8 488-positive neuron candidates in each registered well.
- Track each candidate sequentially across the nine visits using ONLY the 488 channel.
- Extract a fixed-size soma-centered bounding box at every visit.
- Build ONE consensus fixed 488 support mask per neuron from QC-valid visits.
- Quantify 561/mCherry inside the same fixed support at every visit.
- Preserve raw measurements but gate standard metrics when 488 tracking fails.
- Render up to N best-QC individual neuron MP4s.
- Write master longitudinal CSV + summaries + QC + video manifest.
- Optionally write an XLSX workbook if xlsxwriter/openpyxl is available.

Important
---------
"Every neuron" here means every automatically detected compact Day-8 488 candidate
that passes the candidate filters. Biological completeness still requires manual/model
validation of the Day-8 candidate set.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

import imageio.v2 as imageio
import numpy as np
import pandas as pd
import tifffile as tif
from PIL import Image, ImageDraw, ImageFont
from scipy.ndimage import binary_fill_holes, gaussian_filter
from skimage import filters, measure, morphology

# Reuse the already-tested tracking/segmentation/quantification functions.
from make_soma_anchored_bbox_movies_v2 import (
    make_template,
    refine_peak_center,
    robust01,
    segment_neuron_in_box,
    square_bounds,
    track_anchor,
)
from make_fixed_support_soma_movies import build_fixed_support, quantify

DAYS_DEFAULT = [8, 12, 16, 20, 25, 29, 32, 36, 39]
WELLS_DEFAULT = ["E05", "F05", "I05", "J05", "M05", "N05"]
PAIR = {"E05":"E05_F05", "F05":"E05_F05", "I05":"I05_J05", "J05":"I05_J05", "M05":"M05_N05", "N05":"M05_N05"}
ROLE = {"E05":"control", "F05":"TMEM106B", "I05":"control", "J05":"TMEM106B", "M05":"control", "N05":"TMEM106B"}
CONDITION = {
    "E05":"PLD3 + mCherry reporter control",
    "F05":"PLD3 + TMEM106B + mCherry",
    "I05":"PLD3 + mCherry reporter control",
    "J05":"PLD3 + TMEM106B + mCherry",
    "M05":"PLD3 + mCherry reporter control",
    "N05":"PLD3 + TMEM106B + mCherry",
}


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--processed-root", type=Path, required=True)
    p.add_argument("--output-root", type=Path, required=True)
    p.add_argument("--wells", nargs="+", default=WELLS_DEFAULT)
    p.add_argument("--days", nargs="+", type=int, default=DAYS_DEFAULT)
    p.add_argument("--alignment-channel", type=int, default=2)
    p.add_argument("--mcherry-channel", type=int, default=1)
    p.add_argument("--pixel-size-um", type=float, default=0.647675729)
    p.add_argument("--bbox-size", type=int, default=128)
    p.add_argument("--template-size", type=int, default=64)
    p.add_argument("--search-radius", type=int, default=96)
    p.add_argument("--min-template-score", type=float, default=0.18)
    p.add_argument("--min-neuron-area", type=int, default=180)
    p.add_argument("--min-area-ratio", type=float, default=0.35)
    p.add_argument("--max-area-ratio", type=float, default=2.5)
    p.add_argument("--max-mask-centroid-offset", type=float, default=24.0)
    p.add_argument("--candidate-min-area", type=int, default=300)
    p.add_argument("--candidate-max-area", type=int, default=5000)
    p.add_argument("--candidate-max-aspect", type=float, default=3.5)
    p.add_argument("--min-candidate-distance", type=float, default=48.0)
    p.add_argument("--max-candidates-per-well", type=int, default=0,
                   help="0 means all detected candidates; otherwise keep top N per well.")
    p.add_argument("--consensus-fraction", type=float, default=0.35)
    p.add_argument("--support-dilation", type=int, default=2)
    p.add_argument("--puncta-min-size", type=int, default=6)
    p.add_argument("--background-exclusion", type=int, default=8)
    p.add_argument("--max-videos", type=int, default=25)
    p.add_argument("--min-valid-days-for-video", type=int, default=8)
    p.add_argument("--fps", type=int, default=10)
    p.add_argument("--hold-seconds", type=float, default=0.8)
    p.add_argument("--write-xlsx", action="store_true")
    return p.parse_args()


def find_full_stack(root: Path, well: str) -> Path:
    matches = sorted(root.rglob(f"{well}_registered_common_overlap_tcyx.ome.tif"))
    if len(matches) != 1:
        raise RuntimeError(f"Expected one full registered stack for {well}; found {len(matches)}: {matches}")
    return matches[0]


def detect_day8_candidates(frame488, *, min_area, max_area, max_aspect, margin, min_distance):
    align = frame488.astype(np.float32)
    lo, hi = np.percentile(align, [2, 99.5])
    norm = np.clip((align - lo) / max(float(hi-lo), 1.0), 0, 1)
    smooth = gaussian_filter(norm, sigma=2.0)
    threshold = max(float(filters.threshold_otsu(smooth)), float(np.percentile(smooth, 72)))
    mask = smooth > threshold
    mask = morphology.remove_small_objects(mask, max_size=127)
    mask = binary_fill_holes(mask)
    labels = measure.label(mask)
    h, w = frame488.shape
    candidates = []
    for prop in measure.regionprops(labels, intensity_image=align):
        y0,x0,y1,x1 = prop.bbox
        area = int(prop.area)
        if area < min_area or area > max_area:
            continue
        cy,cx = map(float, prop.centroid)
        if cy < margin or cx < margin or cy > h-margin or cx > w-margin:
            continue
        bh,bw = y1-y0, x1-x0
        aspect = max(bh/max(bw,1), bw/max(bh,1))
        if aspect > max_aspect:
            continue
        intensity = float(prop.intensity_mean)
        # Refine centroid toward the bright soma/core, but keep component metadata.
        rcy, rcx = refine_peak_center(gaussian_filter(robust01(frame488), 1.25), int(round(cy)), int(round(cx)), radius=14)
        score = intensity * math.sqrt(area)
        candidates.append({
            "candidate_y": rcy, "candidate_x": rcx,
            "component_centroid_y": cy, "component_centroid_x": cx,
            "component_area_day8": area, "component_aspect_day8": float(aspect),
            "component_mean_488_day8": intensity, "candidate_score": score,
            "component_bbox_y0": int(y0), "component_bbox_x0": int(x0),
            "component_bbox_y1": int(y1), "component_bbox_x1": int(x1),
        })
    candidates.sort(key=lambda r: r["candidate_score"], reverse=True)
    kept=[]
    for c in candidates:
        if all(np.hypot(c["candidate_y"]-k["candidate_y"], c["candidate_x"]-k["candidate_x"]) >= min_distance for k in kept):
            kept.append(c)
    return kept, float(threshold)


def crop_centered(frame, cy, cx, size):
    y0,y1,x0,x1 = square_bounds(cy,cx,size,*frame.shape[-2:])
    return frame[...,y0:y1,x0:x1], (y0,y1,x0,x1)


def normalize_u8(x, limits):
    lo,hi=limits
    y=np.clip((x.astype(np.float32)-lo)/max(hi-lo,1e-6),0,1)
    return (255*y).astype(np.uint8)


def robust_limits(stack):
    vals=stack.astype(np.float32).ravel()
    lo,hi=np.percentile(vals,[1,99.6])
    return float(lo), float(max(hi,lo+1))


def mask_outline(mask):
    er = morphology.erosion(mask, morphology.disk(1))
    return mask & ~er


def render_video(path, well, neuron_id, days, boxes, fixed_support, metrics, alignment_channel, mcherry_channel, fps, hold_seconds):
    lim488=robust_limits(boxes[:,alignment_channel])
    lim561=robust_limits(boxes[:,mcherry_channel])
    out_size=384
    repeats=max(1,int(round(fps*hold_seconds)))
    writer=imageio.get_writer(path,fps=fps,codec="libx264",quality=8,macro_block_size=1)
    outline=mask_outline(fixed_support)
    font=ImageFont.load_default()
    try:
        for i,day in enumerate(days):
            a=normalize_u8(boxes[i,alignment_channel],lim488)
            m=normalize_u8(boxes[i,mcherry_channel],lim561)
            # draw fixed-support contour on 488 only; leave mCherry raw.
            ar=np.stack([a,a,a],axis=-1)
            ar[outline]=[255,255,255]
            im488=Image.fromarray(ar).resize((out_size,out_size),Image.Resampling.NEAREST)
            im561=Image.fromarray(m,"L").convert("RGB").resize((out_size,out_size),Image.Resampling.NEAREST)
            canvas=Image.new("RGB",(out_size*2, out_size+88),"black")
            canvas.paste(im488,(0,32)); canvas.paste(im561,(out_size,32))
            d=ImageDraw.Draw(canvas)
            d.text((8,8),f"{well} {neuron_id} | Day {day}",fill="white",font=font)
            d.text((8,20),"488 tracking/support",fill="white",font=font)
            d.text((out_size+8,20),"561 mCherry",fill="white",font=font)
            r=metrics.iloc[i]
            valid=bool(r["metrics_valid"])
            line=(f"QC={'PASS' if valid else 'FAIL'}  match={r['template_match_score']:.2f}  "
                  f"puncta={r['puncta_count'] if pd.notna(r['puncta_count']) else 'NA'}  "
                  f"diff/punct={r['diffuse_to_punctate_ratio']:.3f}" if pd.notna(r['diffuse_to_punctate_ratio']) else
                  f"QC={'PASS' if valid else 'FAIL'}  match={r['template_match_score']:.2f}  puncta=NA  diff/punct=NA")
            d.text((8,out_size+48),line,fill="white",font=font)
            frame=np.asarray(canvas)
            for _ in range(repeats): writer.append_data(frame)
    finally:
        writer.close()


def infer_join_cols(df):
    lower={c:str(c).lower() for c in df.columns}
    well=next((c for c,v in lower.items() if v=="well" or v.endswith("_well")),None)
    day=next((c for c,v in lower.items() if v in {"day","timepoint_day","visit_day","day_number"}),None)
    if day is None:
        day=next((c for c,v in lower.items() if "day" in v and "weekday" not in v),None)
    return well,day


def aux_metadata_for_report(report_root: Path):
    by_day={}
    for fname,prefix in [("registration_qc.csv","global_reg_"),("dataset_inventory.csv","inventory_"),("summary_stats.csv","wholewell_summary_")]:
        p=report_root/fname
        if not p.exists(): continue
        try: df=pd.read_csv(p)
        except Exception: continue
        wcol,dcol=infer_join_cols(df)
        if wcol is None: continue
        for _,r in df.iterrows():
            well=str(r[wcol])
            day=None
            if dcol is not None:
                try: day=int(float(r[dcol]))
                except Exception: day=None
            key=(well,day)
            payload={}
            for c,v in r.items():
                if c in {wcol,dcol}: continue
                if isinstance(v,(np.generic,)): v=v.item()
                payload[prefix+str(c)]=v
            by_day.setdefault(key,{}).update(payload)
    return by_day


def merge_aux(row, aux, well, day):
    # day-specific first, then well-level summary rows if available.
    row.update(aux.get((well,None),{}))
    row.update(aux.get((well,int(day)),{}))


def track_one_candidate(stack, well, candidate, neuron_index, args, aux, source_stack):
    days=args.days
    frame8=stack[0,args.alignment_channel]
    ay8=float(candidate["candidate_y"]); ax8=float(candidate["candidate_x"])
    template=make_template(frame8,ay8,ax8,args.template_size)
    boxes=[]; adaptive_masks=[]; tracking_rows=[]
    prev_valid_mask=None; day8_mask=None; ref_area=None
    # Track sequentially from the previous QC-valid anchor. This prevents many
    # Day-8 templates with overlapping large search windows from collapsing
    # onto the same bright soma at later visits. The appearance template
    # remains the Day-8 488 template, so mCherry never drives identity.
    prev_anchor_y, prev_anchor_x = ay8, ax8
    for ti,day in enumerate(days):
        f488=stack[ti,args.alignment_channel]
        if ti==0:
            ay,ax,score=ay8,ax8,1.0
        else:
            cand_y,cand_x,score=track_anchor(f488,template,prev_anchor_y,prev_anchor_x,args.search_radius)
            # If the match is too weak, keep the previous valid center for this
            # visit and do not advance the sequential reference. The visit is
            # still marked tracking-invalid below and its standard phenotype
            # metrics are gated to NaN.
            if np.isfinite(score) and score >= args.min_template_score:
                ay,ax=cand_y,cand_x
                prev_anchor_y,prev_anchor_x=ay,ax
            else:
                ay,ax=prev_anchor_y,prev_anchor_x
        box,bounds=crop_centered(stack[ti],ay,ax,args.bbox_size)
        # In box coordinates, tracked soma is nominally central. Use exact center after any integer crop rounding.
        y0,y1,x0,x1=bounds
        local_ay=ay-y0; local_ax=ax-x0
        track_ok=bool(np.isfinite(score) and score>=args.min_template_score)
        seg_error=""
        try:
            prior=prev_valid_mask if prev_valid_mask is not None else day8_mask
            prior_source="previous_valid_local_488_mask" if prev_valid_mask is not None else ("day8_local_488_mask" if day8_mask is not None else "none")
            seg,meta=segment_neuron_in_box(
                box[args.alignment_channel], local_ay, local_ax, args.bbox_size,
                args.min_neuron_area, ref_area=ref_area, prior_mask=prior, prior_source=prior_source)
            area=int(meta["segmentation_area"])
            if ti==0:
                ref_area=area; day8_mask=seg.copy()
            ratio=area/ref_area if ref_area else math.nan
            seg_ok=(area>=args.min_neuron_area and args.min_area_ratio<=ratio<=args.max_area_ratio and
                    meta["segmentation_centroid_offset_from_anchor"]<=args.max_mask_centroid_offset and
                    not bool(meta["segmentation_border_touch"]))
            adaptive_valid=bool(track_ok and seg_ok)
            if adaptive_valid: prev_valid_mask=seg.copy()
        except Exception as e:
            seg=np.zeros((args.bbox_size,args.bbox_size),dtype=bool)
            meta={"segmentation_area":0,"segmentation_centroid_y":math.nan,"segmentation_centroid_x":math.nan,
                  "segmentation_centroid_offset_from_anchor":math.nan,"segmentation_border_touch":True,
                  "foreground_low_threshold":math.nan,"foreground_high_threshold":math.nan,
                  "segmentation_method":"failed","segmentation_prior_source":"none","segmentation_overlap_with_prior":math.nan,
                  "segmentation_seed_488":math.nan}
            ratio=0.0; adaptive_valid=False; seg_error=str(e)
        boxes.append(box); adaptive_masks.append(seg)
        rr={
            "well":well,"pair_id":PAIR.get(well,""),"role":ROLE.get(well,""),"condition":CONDITION.get(well,""),
            "neuron_id":f"{well}_N{neuron_index:03d}","neuron_index":neuron_index,
            "time_index":ti,"day":int(day),"anchor_y":float(ay),"anchor_x":float(ax),
            "day8_anchor_y":ay8,"day8_anchor_x":ax8,"anchor_shift_pixels_from_day8":float(np.hypot(ay-ay8,ax-ax8)),
            "template_match_score":float(score),"tracking_valid":track_ok,
            "bbox_y0":int(y0),"bbox_y1":int(y1),"bbox_x0":int(x0),"bbox_x1":int(x1),"bbox_size":args.bbox_size,
            "adaptive_segmentation_area":int(meta["segmentation_area"]),"adaptive_mask_area_ratio_vs_day8":float(ratio),
            "adaptive_segmentation_centroid_offset_from_anchor":float(meta["segmentation_centroid_offset_from_anchor"]),
            "adaptive_segmentation_border_touch":bool(meta["segmentation_border_touch"]),
            "adaptive_segmentation_method":meta.get("segmentation_method",""),
            "adaptive_segmentation_prior_source":meta.get("segmentation_prior_source",""),
            "adaptive_segmentation_overlap_with_prior":meta.get("segmentation_overlap_with_prior",math.nan),
            "adaptive_segmentation_valid":adaptive_valid,"adaptive_segmentation_error":seg_error,
            "source_registered_stack":str(source_stack),"source_report_root":str(source_stack.parent.parent),
            "pixel_size_um":args.pixel_size_um,"alignment_channel_index":args.alignment_channel,
            "alignment_channel_label":"488nm Binned","mcherry_channel_index":args.mcherry_channel,
            "mcherry_channel_label":"561nm Binned","channel0_label":"405nm Binned",
            "image_dtype":str(stack.dtype),"registered_height_px":int(stack.shape[-2]),"registered_width_px":int(stack.shape[-1]),
        }
        rr.update(candidate)
        merge_aux(rr,aux,well,day)
        tracking_rows.append(rr)
    boxes=np.stack(boxes); adaptive_masks=np.stack(adaptive_masks)
    tdf=pd.DataFrame(tracking_rows)
    try:
        fixed,required,nvalid,method=build_fixed_support(
            adaptive_masks, pd.DataFrame({"metrics_valid":tdf["adaptive_segmentation_valid"]}),
            args.consensus_fraction,args.support_dilation,args.min_neuron_area,5000)
        fixed_ok=True; fixed_error=""
    except Exception as e:
        fixed=np.zeros((args.bbox_size,args.bbox_size),dtype=bool); required=0; nvalid=0; method="failed"; fixed_ok=False; fixed_error=str(e)
    rows=[]; puncta_masks=[]
    for ti,day in enumerate(days):
        base=tracking_rows[ti].copy()
        base.update({"fixed_support_valid":fixed_ok,"fixed_support_method":method,"fixed_support_required_visits":required,
                     "fixed_support_valid_masks_used":nvalid,"fixed_support_area":int(fixed.sum()),"fixed_support_error":fixed_error})
        if fixed_ok:
            q,puncta=quantify(boxes[ti,args.mcherry_channel],fixed,args.background_exclusion,args.puncta_min_size)
            rawq={"raw_"+k:v for k,v in q.items()}
            base.update(rawq)
            # Final longitudinal metrics are gated only by 488 tracking because the support is fixed.
            valid=bool(base["tracking_valid"])
            base["metrics_valid"]=valid
            for k,v in q.items(): base[k]=v if valid else math.nan
            adaptive=adaptive_masks[ti]
            base["adaptive_fraction_of_fixed_support_covered"]=float((adaptive & fixed).sum()/max(fixed.sum(),1))
        else:
            puncta=np.zeros_like(fixed)
            base["metrics_valid"]=False
            for k in ["local_background_median_561","total_mcherry_intensity","diffuse_mcherry_integrated_intensity",
                      "diffuse_mcherry_mean_intensity","punctate_mcherry_integrated_intensity","puncta_count",
                      "puncta_density_per_area","mean_puncta_intensity","median_puncta_area","diffuse_to_punctate_ratio",
                      "rupture_like_score","dog_threshold"]: base[k]=math.nan
            base["adaptive_fraction_of_fixed_support_covered"]=math.nan
        rows.append(base); puncta_masks.append(puncta)
    return pd.DataFrame(rows), boxes, fixed, np.stack(puncta_masks)


def write_xlsx_optional(out, master, tracks, wells, failures, videos, runmeta):
    path=out/"neuron_longitudinal_atlas.xlsx"
    engine=None
    try:
        import xlsxwriter  # noqa
        engine="xlsxwriter"
    except Exception:
        try:
            import openpyxl  # noqa
            engine="openpyxl"
        except Exception:
            return None, "Neither xlsxwriter nor openpyxl is installed"
    try:
        with pd.ExcelWriter(path,engine=engine) as xw:
            master.to_excel(xw,"Longitudinal_Data",index=False)
            tracks.to_excel(xw,"Neuron_Summary",index=False)
            wells.to_excel(xw,"Well_Summary",index=False)
            failures.to_excel(xw,"QC_Failures",index=False)
            videos.to_excel(xw,"Video_Manifest",index=False)
            runmeta.to_excel(xw,"Run_Metadata",index=False)
        return path,None
    except Exception as e:
        return None,str(e)


def main():
    args=parse_args(); args.output_root.mkdir(parents=True,exist_ok=True)
    videos_dir=args.output_root/"videos"; videos_dir.mkdir(exist_ok=True)
    all_rows=[]; track_artifacts=[]; aux_cache={}
    for well in args.wells:
        stack_path=find_full_stack(args.processed_root,well)
        report_root=stack_path.parent.parent
        aux=aux_cache.setdefault(str(report_root),aux_metadata_for_report(report_root))
        stack=tif.imread(stack_path)
        if stack.ndim!=4 or stack.shape[0]!=len(args.days):
            raise RuntimeError(f"{well}: expected TCYX with {len(args.days)} visits, got {stack.shape}")
        margin=max(args.bbox_size//2+args.search_radius+args.template_size//2,160)
        cands,thr=detect_day8_candidates(stack[0,args.alignment_channel],min_area=args.candidate_min_area,
            max_area=args.candidate_max_area,max_aspect=args.candidate_max_aspect,margin=margin,min_distance=args.min_candidate_distance)
        if args.max_candidates_per_well>0: cands=cands[:args.max_candidates_per_well]
        print(f"{well}: detected {len(cands)} compact Day-8 488 candidates (threshold={thr:.4f})")
        for j,c in enumerate(cands,1):
            try:
                df,boxes,fixed,puncta=track_one_candidate(stack,well,c,j,args,aux,stack_path)
                all_rows.extend(df.to_dict("records"))
                track_artifacts.append({"well":well,"neuron_id":f"{well}_N{j:03d}","df":df,"boxes":boxes,"fixed":fixed,
                                        "valid_days":int(df.metrics_valid.sum()),"mean_template_score":float(df.loc[df.time_index>0,"template_match_score"].mean()),
                                        "fixed_support_area":int(fixed.sum())})
            except Exception as e:
                print(f"WARNING {well}_N{j:03d}: {e}")
    master=pd.DataFrame(all_rows)
    if master.empty: raise RuntimeError("No neuron tracks were produced")
    # Stable sort for longitudinal review.
    master=master.sort_values(["well","neuron_index","time_index"]).reset_index(drop=True)
    track_rows=[]
    for a in track_artifacts:
        d=a["df"]
        track_rows.append({"well":a["well"],"pair_id":PAIR.get(a["well"],""),"role":ROLE.get(a["well"],""),
            "condition":CONDITION.get(a["well"],""),"neuron_id":a["neuron_id"],"valid_days":a["valid_days"],
            "total_days":len(args.days),"mean_template_match_score":a["mean_template_score"],"min_template_match_score":float(d.template_match_score.min()),
            "max_anchor_shift_pixels":float(d.anchor_shift_pixels_from_day8.max()),"fixed_support_area":a["fixed_support_area"],
            "day8_anchor_y":float(d.day8_anchor_y.iloc[0]),"day8_anchor_x":float(d.day8_anchor_x.iloc[0]),
            "candidate_component_area_day8":int(d.component_area_day8.iloc[0]),"candidate_score":float(d.candidate_score.iloc[0])})
    tracks=pd.DataFrame(track_rows).sort_values(["valid_days","mean_template_match_score","fixed_support_area"],ascending=[False,False,False]).reset_index(drop=True)
    well_summary=(tracks.groupby(["well","pair_id","role","condition"],dropna=False)
                  .agg(detected_neuron_tracks=("neuron_id","count"),tracks_9of9=("valid_days",lambda s:int((s==len(args.days)).sum())),
                       tracks_8plus=("valid_days",lambda s:int((s>=8).sum())),median_fixed_support_area=("fixed_support_area","median"),
                       mean_template_score=("mean_template_match_score","mean")).reset_index())
    failures=master.loc[~master.metrics_valid.astype(bool)].copy()
    # Render best-QC tracks only. Data remains for all tracks.
    ranked=sorted(track_artifacts,key=lambda a:(a["valid_days"],a["mean_template_score"],a["fixed_support_area"]),reverse=True)
    video_rows=[]
    nvid=0
    for a in ranked:
        if nvid>=args.max_videos: break
        if a["valid_days"]<args.min_valid_days_for_video or a["fixed_support_area"]<=0: continue
        vp=videos_dir/f"{a['neuron_id']}_fixed_support_timelapse.mp4"
        render_video(vp,a["well"],a["neuron_id"],args.days,a["boxes"],a["fixed"],a["df"],args.alignment_channel,args.mcherry_channel,args.fps,args.hold_seconds)
        video_rows.append({"video_rank":nvid+1,"well":a["well"],"neuron_id":a["neuron_id"],"video_path":str(vp),
                           "valid_days":a["valid_days"],"mean_template_match_score":a["mean_template_score"],"fixed_support_area":a["fixed_support_area"]})
        nvid+=1; print(f"video {nvid}/{args.max_videos}: {vp.name}")
    videos=pd.DataFrame(video_rows)
    tracks=tracks.merge(videos[["neuron_id","video_path"]] if not videos.empty else pd.DataFrame(columns=["neuron_id","video_path"]),on="neuron_id",how="left")
    runmeta=pd.DataFrame([{
        "created_utc":datetime.now(timezone.utc).isoformat(),"experiment":"TMEM106B six-well longitudinal pilot",
        "wells":" ".join(args.wells),"days":" ".join(map(str,args.days)),"alignment_channel_index":args.alignment_channel,
        "alignment_channel":"488nm Binned","mcherry_channel_index":args.mcherry_channel,"mcherry_channel":"561nm Binned",
        "pixel_size_um":args.pixel_size_um,"bbox_size_px":args.bbox_size,"template_size_px":args.template_size,
        "search_radius_px":args.search_radius,"candidate_min_area":args.candidate_min_area,"candidate_max_area":args.candidate_max_area,
        "min_candidate_distance_px":args.min_candidate_distance,"consensus_fraction":args.consensus_fraction,
        "support_dilation_px":args.support_dilation,"puncta_method":"DoG sigma1-sigma3; threshold=max(median+4*MADsigma,97.5th percentile)",
        "puncta_min_size_px":args.puncta_min_size,"background_method":"local median outside dilated fixed support",
        "tracking_method":"Day8 488 soma template; sequential bounded template matching from previous valid anchor; mCherry excluded from identity/tracking",
        "analysis_mask_method":"one consensus fixed 488 support per neuron across all visits",
        "candidate_definition":"automatic compact Day8 488-positive components; requires validation for biological completeness",
        "python":sys.version.replace("\n"," "),"platform":platform.platform(),"hostname":platform.node(),"command":" ".join(sys.argv),
    }])
    # Authoritative CSV outputs.
    master.to_csv(args.output_root/"all_neurons_longitudinal_master.csv",index=False)
    tracks.to_csv(args.output_root/"neuron_track_summary.csv",index=False)
    well_summary.to_csv(args.output_root/"well_summary.csv",index=False)
    failures.to_csv(args.output_root/"qc_failures.csv",index=False)
    videos.to_csv(args.output_root/"video_manifest.csv",index=False)
    runmeta.to_csv(args.output_root/"run_metadata.csv",index=False)
    if args.write_xlsx:
        xlsx,err=write_xlsx_optional(args.output_root,master,tracks,well_summary,failures,videos,runmeta)
        if xlsx: print(f"Wrote {xlsx}")
        else: print(f"XLSX skipped: {err}. CSV outputs are complete and Excel-readable.")
    print(f"\nDONE: {len(tracks)} neuron tracks; {len(master)} neuron-day rows; {len(videos)} MP4s")
    print(f"Master CSV: {args.output_root/'all_neurons_longitudinal_master.csv'}")
    print(f"Outputs: {args.output_root}")

if __name__=="__main__":
    main()
