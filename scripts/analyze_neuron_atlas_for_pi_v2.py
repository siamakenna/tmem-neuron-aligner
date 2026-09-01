#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gc
import json
import math
import os
import shutil
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import tifffile as tif
from PIL import Image, ImageDraw, ImageFont

DAYS_DEFAULT = [8, 12, 16, 20, 25, 29, 32, 36, 39]
WELLS_DEFAULT = ["E05", "F05", "I05", "J05", "M05", "N05"]
PAIR_MAP = {"E05":"E05_F05", "F05":"E05_F05", "I05":"I05_J05", "J05":"I05_J05", "M05":"M05_N05", "N05":"M05_N05"}
ROLE_MAP = {"E05":"control", "F05":"TMEM106B", "I05":"control", "J05":"TMEM106B", "M05":"control", "N05":"TMEM106B"}

PRIMARY_METRICS = [
    {
        "metric": "diffuse_to_punctate_ratio",
        "short_name": "Diffuse:Punctate ratio",
        "biological_question": "Is mCherry redistributed between diffuse and punctate pools?",
        "priority": 1,
        "direction_note": "Do not hard-code direction; evaluate trajectory and pair consistency.",
        "pseudocount": 0.01,
    },
    {
        "metric": "puncta_density_per_area",
        "short_name": "Puncta density",
        "biological_question": "Does puncta burden per fixed neuron support change?",
        "priority": 2,
        "direction_note": "Higher = more detected puncta per support area; segmentation/support QC remains important.",
        "pseudocount": 1e-6,
    },
    {
        "metric": "diffuse_mcherry_mean_intensity",
        "short_name": "Diffuse mCherry mean",
        "biological_question": "Does the diffuse mCherry pool change within the fixed support?",
        "priority": 3,
        "direction_note": "Background-subtracted intensity; compare within-neuron change first.",
        "pseudocount": 1.0,
    },
    {
        "metric": "punctate_mcherry_integrated_intensity",
        "short_name": "Punctate mCherry integrated",
        "biological_question": "Does the punctate mCherry pool change longitudinally?",
        "priority": 4,
        "direction_note": "Integrated signal inside puncta within the fixed support.",
        "pseudocount": 1.0,
    },
    {
        "metric": "total_mcherry_intensity",
        "short_name": "Total mCherry",
        "biological_question": "Does overall reporter abundance change within the fixed support?",
        "priority": 5,
        "direction_note": "Useful context for redistribution metrics; not a direct rupture/fibril marker.",
        "pseudocount": 1.0,
    },
]

SECONDARY_METRICS = [
    ("puncta_count", "Puncta count", "Secondary morphology burden metric."),
    ("mean_puncta_intensity", "Mean puncta intensity", "Secondary puncta brightness metric."),
    ("median_puncta_area", "Median puncta area", "Secondary puncta size metric."),
    ("rupture_like_score", "Rupture-like score", "Screening/derived score only; not direct evidence of membrane rupture."),
]


def parse_args():
    p = argparse.ArgumentParser(description="Build a PI-ready TMEM106B neuron-atlas QC and trajectory package.")
    p.add_argument("--atlas-root", type=Path, required=True)
    p.add_argument("--pair-root", type=Path, required=True)
    p.add_argument("--output-root", type=Path, required=True)
    p.add_argument("--days", nargs="+", type=int, default=DAYS_DEFAULT)
    p.add_argument("--alignment-channel", type=int, default=2)
    p.add_argument("--contact-box-size", type=int, default=128)
    p.add_argument("--max-contact-sheets", type=int, default=0, help="0 = all B/C review tracks.")
    return p.parse_args()


def semijoin_reasons(flags):
    return "; ".join([x for x in flags if x]) if any(flags) else "none"


def nearest_neighbor_by_well_day(master):
    out = pd.Series(np.nan, index=master.index, dtype=float)
    for (_, _), idx in master.groupby(["well", "day"], sort=False).groups.items():
        ids = list(idx)
        if len(ids) < 2:
            out.loc[ids] = np.inf
            continue
        coords = master.loc[ids, ["anchor_y", "anchor_x"]].to_numpy(float)
        dif = coords[:, None, :] - coords[None, :, :]
        dist = np.sqrt((dif ** 2).sum(axis=2))
        np.fill_diagonal(dist, np.inf)
        out.loc[ids] = dist.min(axis=1)
    return out


def build_identity_qc(master, tracks):
    m = master.sort_values(["well", "neuron_id", "time_index"]).copy()
    m["nearest_neighbor_anchor_distance_px"] = nearest_neighbor_by_well_day(m)
    m["step_displacement_px"] = np.nan
    for _, idx in m.groupby("neuron_id", sort=False).groups.items():
        ids = list(idx)
        coords = m.loc[ids, ["anchor_y", "anchor_x"]].to_numpy(float)
        if len(coords) > 1:
            step = np.sqrt(((coords[1:] - coords[:-1]) ** 2).sum(axis=1))
            m.loc[ids[1:], "step_displacement_px"] = step

    agg = m.groupby(["well", "neuron_id"], as_index=False).agg(
        valid_days_master=("metrics_valid", lambda s: int(pd.Series(s).astype(bool).sum())),
        min_template_match_score_master=("template_match_score", "min"),
        mean_template_match_score_master=("template_match_score", "mean"),
        max_step_displacement_px=("step_displacement_px", "max"),
        min_nearest_neighbor_anchor_distance_px=("nearest_neighbor_anchor_distance_px", "min"),
        collision_days_lt8px=("nearest_neighbor_anchor_distance_px", lambda x: int((pd.to_numeric(x, errors="coerce") < 8).sum())),
        collision_days_lt12px=("nearest_neighbor_anchor_distance_px", lambda x: int((pd.to_numeric(x, errors="coerce") < 12).sum())),
        collision_days_lt20px=("nearest_neighbor_anchor_distance_px", lambda x: int((pd.to_numeric(x, errors="coerce") < 20).sum())),
        min_adaptive_fraction_of_fixed_support_covered=("adaptive_fraction_of_fixed_support_covered", "min"),
        median_adaptive_fraction_of_fixed_support_covered=("adaptive_fraction_of_fixed_support_covered", "median"),
        fixed_support_valid_all=("fixed_support_valid", lambda s: bool(pd.Series(s).astype(bool).all())),
        fixed_support_area_master=("fixed_support_area", "first"),
        max_anchor_shift_pixels_master=("anchor_shift_pixels_from_day8", "max"),
    )
    q = tracks.merge(agg, on=["well", "neuron_id"], how="left", suffixes=("", "_calc"))

    tiers = []
    reasons = []
    hard_flags_col = []
    review_flags_col = []
    identity_status = []
    severity = []
    for _, r in q.iterrows():
        valid = int(r.get("valid_days", r.get("valid_days_master", 0)))
        min_score = float(r.get("min_template_match_score", r.get("min_template_match_score_master", np.nan)))
        mean_score = float(r.get("mean_template_match_score", r.get("mean_template_match_score_master", np.nan)))
        max_step = float(r.get("max_step_displacement_px", np.nan))
        min_nn = float(r.get("min_nearest_neighbor_anchor_distance_px", np.nan))
        coll8 = int(r.get("collision_days_lt8px", 0) or 0)
        coll12 = int(r.get("collision_days_lt12px", 0) or 0)
        coll20 = int(r.get("collision_days_lt20px", 0) or 0)
        med_cover = float(r.get("median_adaptive_fraction_of_fixed_support_covered", np.nan))
        min_cover = float(r.get("min_adaptive_fraction_of_fixed_support_covered", np.nan))
        fixed_ok = bool(r.get("fixed_support_valid_all", True))
        area = float(r.get("fixed_support_area", r.get("fixed_support_area_master", np.nan)))

        hard = []
        soft = []
        # Informal-leaning identity tiers. A single close-neighbor event is a
        # REVIEW flag, not an automatic exclusion. Repeated near-identical
        # anchors (<8 px on >=2 visits) are treated as a likely identity
        # collision and remain a hard exclusion.
        if valid < 8: hard.append(f"only {valid}/9 valid days")
        if not fixed_ok: hard.append("fixed support invalid")
        if np.isfinite(min_score) and min_score < 0.15: hard.append(f"template score <0.15 ({min_score:.2f})")
        if np.isfinite(max_step) and max_step > 75: hard.append(f"large between-visit jump ({max_step:.1f}px)")
        if coll8 >= 2: hard.append(f"repeated likely track collision ({coll8} visits <8px from another anchor)")
        if np.isfinite(area) and (area < 150 or area > 5500): hard.append(f"implausible fixed support area ({area:.0f}px)")

        if valid == 8: soft.append("8/9 valid days")
        if np.isfinite(min_score) and min_score < 0.30: soft.append(f"low minimum template score ({min_score:.2f})")
        if np.isfinite(mean_score) and mean_score < 0.50: soft.append(f"low mean template score ({mean_score:.2f})")
        if np.isfinite(max_step) and max_step > 45: soft.append(f"moderate between-visit jump ({max_step:.1f}px)")
        if coll12 >= 1: soft.append(f"close neighboring track on {coll12} visit(s) (<12px)")
        elif coll20 >= 1: soft.append(f"near neighboring track on {coll20} visit(s) (<20px)")
        if np.isfinite(med_cover) and med_cover < 0.35: soft.append(f"low median adaptive/support overlap ({med_cover:.2f})")
        if np.isfinite(min_cover) and min_cover < 0.10: soft.append(f"very low visit adaptive/support overlap ({min_cover:.2f})")

        if hard:
            tier = "C_exclude"
            status = "automated_identity_fail_or_unreliable"
            sev = 3
        elif soft:
            tier = "B_include_review"
            status = "automated_identity_plausible_review_recommended"
            sev = 2
        else:
            tier = "A_include"
            status = "automated_identity_consistent"
            sev = 1
        tiers.append(tier)
        hard_flags_col.append(semijoin_reasons(hard))
        review_flags_col.append(semijoin_reasons(soft))
        reasons.append(semijoin_reasons(hard + soft))
        identity_status.append(status)
        severity.append(sev)

    q["analysis_qc_tier"] = tiers
    q["automated_identity_status"] = identity_status
    q["hard_exclusion_reasons"] = hard_flags_col
    q["review_reasons"] = review_flags_col
    q["qc_reasons"] = reasons
    q["informal_analysis_include"] = q["analysis_qc_tier"].isin(["A_include", "B_include_review"])
    q["strict_analysis_include"] = q["analysis_qc_tier"].eq("A_include")
    q["manual_identity_review"] = np.where(q["analysis_qc_tier"].eq("A_include"), "optional spot-check", "pending")
    q["qc_severity"] = severity
    q = q.sort_values(["qc_severity", "valid_days", "mean_template_match_score"], ascending=[False, True, True]).reset_index(drop=True)
    return m, q


def primary_metric_dictionary():
    rows = []
    for d in PRIMARY_METRICS:
        rows.append({
            "metric": d["metric"], "display_name": d["short_name"], "set": "PRIMARY", "priority": d["priority"],
            "biological_question": d["biological_question"], "interpretation_note": d["direction_note"],
            "normalization": "Within-neuron Day-8 baseline; report raw, delta, relative, percent change, and log2 fold with pseudocount.",
            "pseudocount_for_log2_fold": d["pseudocount"],
        })
    for m, name, note in SECONDARY_METRICS:
        rows.append({"metric":m, "display_name":name, "set":"SECONDARY", "priority":"", "biological_question":"Supportive/secondary phenotype characterization.", "interpretation_note":note, "normalization":"Raw/Day-8-normalized where useful.", "pseudocount_for_log2_fold":""})
    return pd.DataFrame(rows)


def build_trajectory_tables(master_with_dist, qc, days):
    qcols = ["neuron_id", "analysis_qc_tier", "automated_identity_status", "informal_analysis_include", "strict_analysis_include", "qc_reasons"]
    m = master_with_dist.merge(qc[qcols], on="neuron_id", how="left")
    records = []
    pc_map = {x["metric"]: x["pseudocount"] for x in PRIMARY_METRICS}
    for metric in [x["metric"] for x in PRIMARY_METRICS]:
        if metric not in m.columns:
            continue
        base = m.loc[m["day"] == days[0], ["neuron_id", metric]].rename(columns={metric:"baseline_value"})
        x = m[["well","pair_id","role","condition","neuron_id","day","time_index",metric,"metrics_valid","analysis_qc_tier","informal_analysis_include","strict_analysis_include"]].merge(base, on="neuron_id", how="left")
        x = x.rename(columns={metric:"value"})
        pc = pc_map[metric]
        x["metric"] = metric
        x["delta_from_day8"] = x["value"] - x["baseline_value"]
        x["relative_to_day8"] = np.where(x["baseline_value"].abs() > 1e-12, x["value"] / x["baseline_value"], np.nan)
        x["percent_change_from_day8"] = 100.0 * (x["relative_to_day8"] - 1.0)
        x["log2_fold_vs_day8"] = np.log2((x["value"] + pc) / (x["baseline_value"] + pc))
        records.append(x)
    long = pd.concat(records, ignore_index=True) if records else pd.DataFrame()

    summaries = []
    pair_rows = []
    effect_rows = []
    for set_name, include_col in [("informal_AplusB", "informal_analysis_include"), ("strict_A_only", "strict_analysis_include")]:
        inc = long.loc[long[include_col].astype(bool) & long["metrics_valid"].astype(bool)].copy()
        if inc.empty:
            continue
        well = inc.groupby(["metric","well","pair_id","role","day"], as_index=False).agg(
            n_neurons=("neuron_id","nunique"),
            median_raw=("value","median"), mean_raw=("value","mean"),
            median_delta=("delta_from_day8","median"),
            median_relative=("relative_to_day8","median"),
            median_pct_change=("percent_change_from_day8","median"),
            q25_pct_change=("percent_change_from_day8", lambda s: s.quantile(0.25)),
            q75_pct_change=("percent_change_from_day8", lambda s: s.quantile(0.75)),
            median_log2_fold=("log2_fold_vs_day8","median"),
        )
        well["analysis_set"] = set_name
        summaries.append(well)

        for (metric, pair_id, day), g in well.groupby(["metric","pair_id","day"]):
            control = g.loc[g["role"] == "control"]
            tmem = g.loc[g["role"] == "TMEM106B"]
            if control.empty or tmem.empty:
                continue
            c = control.iloc[0]; t = tmem.iloc[0]
            pair_rows.append({
                "analysis_set":set_name, "metric":metric, "pair_id":pair_id, "day":int(day),
                "control_well":c["well"], "tmem_well":t["well"],
                "control_n_neurons":int(c["n_neurons"]), "tmem_n_neurons":int(t["n_neurons"]),
                "control_median_log2_fold":c["median_log2_fold"], "tmem_median_log2_fold":t["median_log2_fold"],
                "pair_difference_tmem_minus_control_log2_fold":t["median_log2_fold"] - c["median_log2_fold"],
                "control_median_pct_change":c["median_pct_change"], "tmem_median_pct_change":t["median_pct_change"],
                "pair_difference_tmem_minus_control_pct_points":t["median_pct_change"] - c["median_pct_change"],
            })
    well_summary = pd.concat(summaries, ignore_index=True) if summaries else pd.DataFrame()
    pair_effects = pd.DataFrame(pair_rows)
    if not pair_effects.empty:
        for (aset, metric, day), g in pair_effects.groupby(["analysis_set","metric","day"]):
            vals = g["pair_difference_tmem_minus_control_log2_fold"].dropna()
            effect_rows.append({
                "analysis_set":aset, "metric":metric, "day":int(day), "n_pairs":len(vals),
                "mean_pair_difference_log2_fold":vals.mean() if len(vals) else np.nan,
                "median_pair_difference_log2_fold":vals.median() if len(vals) else np.nan,
                "pairs_positive":int((vals > 0).sum()), "pairs_negative":int((vals < 0).sum()), "pairs_zero":int((vals == 0).sum()),
                "direction_consistency":f"{max(int((vals>0).sum()), int((vals<0).sum()))}/{len(vals)} same sign" if len(vals) else "NA",
            })
    cross_pair = pd.DataFrame(effect_rows)
    day39 = cross_pair.loc[cross_pair["day"] == days[-1]].copy() if not cross_pair.empty else pd.DataFrame()
    return m, long, well_summary, pair_effects, cross_pair, day39


def make_plots(well_summary, pair_effects, outdir, days):
    outdir.mkdir(parents=True, exist_ok=True)
    metric_names = {x["metric"]:x["short_name"] for x in PRIMARY_METRICS}
    informal = well_summary.loc[well_summary["analysis_set"] == "informal_AplusB"].copy()
    for metric, g in informal.groupby("metric"):
        fig, ax = plt.subplots(figsize=(9, 5.5))
        for well in WELLS_DEFAULT:
            z = g.loc[g["well"] == well].sort_values("day")
            if z.empty: continue
            ax.plot(z["day"], z["median_log2_fold"], marker="o", label=f"{well} ({ROLE_MAP.get(well,'')})")
        ax.axhline(0, linewidth=1)
        ax.set_xlabel("Day")
        ax.set_ylabel("Median within-neuron log2 fold vs Day 8")
        ax.set_title(metric_names.get(metric, metric))
        ax.legend(fontsize=8, ncol=2)
        fig.tight_layout()
        fig.savefig(outdir / f"trajectory_{metric}.png", dpi=180)
        plt.close(fig)

    informal_pair = pair_effects.loc[pair_effects["analysis_set"] == "informal_AplusB"].copy()
    for metric, g in informal_pair.groupby("metric"):
        fig, ax = plt.subplots(figsize=(8, 5))
        for pair in ["E05_F05","I05_J05","M05_N05"]:
            z = g.loc[g["pair_id"] == pair].sort_values("day")
            if z.empty: continue
            ax.plot(z["day"], z["pair_difference_tmem_minus_control_log2_fold"], marker="o", label=pair.replace("_"," vs "))
        ax.axhline(0, linewidth=1)
        ax.set_xlabel("Day")
        ax.set_ylabel("TMEM - control median log2 fold")
        ax.set_title(f"Matched-pair effect: {metric_names.get(metric, metric)}")
        ax.legend(fontsize=8)
        fig.tight_layout()
        fig.savefig(outdir / f"pair_effect_{metric}.png", dpi=180)
        plt.close(fig)


def crop_center(frame, cy, cx, size):
    h, w = frame.shape[-2:]
    half = size // 2
    y0 = int(round(cy)) - half; x0 = int(round(cx)) - half
    y0 = min(max(y0, 0), max(h-size, 0)); x0 = min(max(x0, 0), max(w-size, 0))
    return frame[y0:y0+size, x0:x0+size]


def norm_u8(a):
    a = a.astype(np.float32)
    lo, hi = np.percentile(a, [1, 99.5])
    if hi <= lo: hi = lo + 1
    return (255*np.clip((a-lo)/(hi-lo),0,1)).astype(np.uint8)


def make_contact_sheets(master, qc, outdir, alignment_channel, box_size, max_sheets):
    outdir.mkdir(parents=True, exist_ok=True)
    review = qc.loc[qc["analysis_qc_tier"].isin(["B_include_review","C_exclude"])].copy()
    review = review.sort_values(["qc_severity","valid_days","mean_template_match_score"], ascending=[False,True,True])
    if max_sheets > 0:
        review = review.head(max_sheets)
    if review.empty:
        return pd.DataFrame(columns=["neuron_id","contact_sheet_path"])

    paths = []
    font = ImageFont.load_default()
    for well, gq in review.groupby("well"):
        gm = master.loc[master["well"] == well].copy()
        source_candidates = gm["source_registered_stack"].dropna().astype(str).unique().tolist()
        if not source_candidates:
            continue
        source = Path(source_candidates[0])
        try:
            stack = tif.imread(source)
        except Exception as e:
            print(f"WARNING contact sheets {well}: cannot read {source}: {e}")
            continue
        for _, qr in gq.iterrows():
            nid = qr["neuron_id"]
            rows = gm.loc[gm["neuron_id"] == nid].sort_values("time_index")
            if rows.empty: continue
            tile = 176
            canvas = Image.new("RGB", (tile*3, tile*3), "black")
            for k, (_, r) in enumerate(rows.head(9).iterrows()):
                ti = int(r["time_index"]); day = int(r["day"])
                c = crop_center(stack[ti, alignment_channel], r["anchor_y"], r["anchor_x"], box_size)
                im = Image.fromarray(norm_u8(c), "L").convert("RGB").resize((tile,tile), Image.Resampling.NEAREST)
                draw = ImageDraw.Draw(im)
                cx = tile//2; cy = tile//2
                draw.line((cx-7,cy,cx+7,cy),fill="white",width=1); draw.line((cx,cy-7,cx,cy+7),fill="white",width=1)
                draw.rectangle((2,2,82,18),fill="black")
                draw.text((5,5),f"D{day} s={r['template_match_score']:.2f}",font=font,fill="white")
                canvas.paste(im, ((k%3)*tile, (k//3)*tile))
            p = outdir / f"{nid}_488_identity_contact.png"
            canvas.save(p)
            paths.append({"well":well,"neuron_id":nid,"analysis_qc_tier":qr["analysis_qc_tier"],"contact_sheet_path":str(p)})
        del stack
        gc.collect()
    return pd.DataFrame(paths)


def copy_tree_files(src_dir, dst_dir, pattern="*"):
    dst_dir.mkdir(parents=True, exist_ok=True)
    copied = []
    if not src_dir.exists(): return copied
    for p in src_dir.glob(pattern):
        if p.is_file():
            target = dst_dir / p.name
            shutil.copy2(p, target)
            copied.append(target)
    return copied


def write_readme(path, counts, tier_counts, day39):
    text = f"""# TMEM106B longitudinal neuron atlas - PI/lab review package

## Start here
This package is a frozen review-oriented analysis of the six-well TMEM106B longitudinal pilot.

- Automatically detected neuron tracks: {counts['tracks']}
- Neuron-day rows: {counts['rows']}
- 9/9-valid tracks in original atlas: {counts['valid9']}
- Individual neuron videos copied: {counts['videos']}
- Corrected matched-pair videos copied: {counts['pair_videos']}

## Experimental pairing
- E05 control vs F05 TMEM106B
- I05 control vs J05 TMEM106B
- M05 control vs N05 TMEM106B
- Visits: Days 8, 12, 16, 20, 25, 29, 32, 36, 39
- Identity/tracking channel: 488
- Phenotype channel: 561 mCherry

## Automated identity/QC tiers (informal, intentionally permissive)
- A_include: strong automated identity consistency. Use in strict sensitivity analysis.
- B_include_review: plausible track with one or more soft flags. Included in the informal/exploratory analysis, but prioritized for visual review.
- C_exclude: severe automated QC concern. Excluded from biological inference unless manually rescued.

Tier counts:
{tier_counts.to_string()}

Important: these are automated identity-consistency tiers, not proof of biological identity. Review contact sheets and videos before final claims.

## Primary metric set
1. diffuse_to_punctate_ratio - central redistribution metric.
2. puncta_density_per_area - puncta burden normalized to the fixed support.
3. diffuse_mcherry_mean_intensity - diffuse reporter pool.
4. punctate_mcherry_integrated_intensity - punctate reporter pool.
5. total_mcherry_intensity - overall reporter abundance/context.

Secondary metrics are retained, but rupture_like_score is screening only and must not be described as direct evidence of lysosomal rupture or fibrils.

## Statistical unit / interpretation
Hundreds of neurons are nested within six wells. The biological replicate structure is the three matched well pairs, not the individual neurons. The package therefore provides neuron-level trajectories for visualization and well-level medians before matched-pair contrasts. With only three matched pairs, pair effects are descriptive; avoid treating neuron count as independent biological n.

## Analysis sets
- informal_AplusB: A_include + B_include_review. Main exploratory analysis requested here.
- strict_A_only: A_include only. Sensitivity analysis.
Conclusions are more credible when the direction is stable across both analysis sets and across the three matched well pairs.

## Folder guide
- 00_START_HERE: workbook and this README.
- 01_CORE_DATA: master neuron-day table with QC plus track summary.
- 02_QC_IDENTITY: automated identity tiers and visual-review queue/contact sheets.
- 03_TRAJECTORY_ANALYSIS: normalized primary-metric trajectories, matched-pair effects, and plots.
- 04_VIDEOS: individual and matched-pair MP4s.
- 05_METADATA_METHODS: run metadata, dictionaries, manifests, and original supporting tables.

## Day-39 matched-pair snapshot
See `03_TRAJECTORY_ANALYSIS/day39_primary_effects.csv` and the Executive_Summary workbook sheet. A positive pair effect means the TMEM106B well had a higher median within-neuron log2-fold change than its paired control. Direction should be interpreted metric-by-metric, not as a generic "better/worse" score.

## Recommended review sequence
1. Open `00_START_HERE/TMEM106B_neuron_atlas_PI_review.xlsx`.
2. Read Executive_Summary and README.
3. Inspect the B/C manual review queue/contact sheets.
4. Watch the three corrected matched-pair videos plus representative individual videos.
5. Review primary trajectory plots and Day-39 pair effects.
6. Only then draft biological conclusions.
"""
    path.write_text(text)


def write_excel(path, executive_rows, readme_rows, metric_dict, qc, day39_neuron, well_summary, pair_effects, day39, review_queue, runmeta):
    import xlsxwriter
    path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(path, engine="xlsxwriter") as xw:
        pd.DataFrame(executive_rows, columns=["Item","Value","Interpretation"]).to_excel(xw, sheet_name="Executive_Summary", index=False, startrow=2)
        pd.DataFrame(readme_rows, columns=["Section","Details"]).to_excel(xw, sheet_name="README", index=False)
        metric_dict.to_excel(xw, sheet_name="Primary_Metrics", index=False)
        qc.to_excel(xw, sheet_name="QC_Tiers", index=False)
        day39_neuron.to_excel(xw, sheet_name="Day39_Neuron_Changes", index=False)
        well_summary.to_excel(xw, sheet_name="Well_Day_Summary", index=False)
        pair_effects.to_excel(xw, sheet_name="Pair_Effects", index=False)
        day39.to_excel(xw, sheet_name="Day39_Effects", index=False)
        review_queue.to_excel(xw, sheet_name="Manual_Review_Queue", index=False)
        runmeta.to_excel(xw, sheet_name="Run_Metadata", index=False)

        wb = xw.book
        title_fmt = wb.add_format({"bold":True,"font_size":16,"font_color":"#FFFFFF","bg_color":"#1F4E78","align":"left","valign":"vcenter"})
        hdr = wb.add_format({"bold":True,"font_color":"#FFFFFF","bg_color":"#4472C4","border":1,"text_wrap":True,"valign":"top"})
        wrap = wb.add_format({"text_wrap":True,"valign":"top"})
        good = wb.add_format({"bg_color":"#E2F0D9"})
        reviewf = wb.add_format({"bg_color":"#FFF2CC"})
        bad = wb.add_format({"bg_color":"#FCE4D6"})
        pct = wb.add_format({"num_format":"0.0%"})

        for sheet_name in xw.sheets:
            ws = xw.sheets[sheet_name]
            ws.freeze_panes(1,0)
            ws.autofilter(0,0,0, max(0, (len(xw.sheets[sheet_name].table) if False else 0))) if False else None
            ws.set_default_row(18)
        ex = xw.sheets["Executive_Summary"]
        ex.merge_range("A1:C1", "TMEM106B Longitudinal Neuron Atlas - PI Review", title_fmt)
        ex.set_row(0, 24)
        ex.set_column("A:A", 30); ex.set_column("B:B", 20); ex.set_column("C:C", 70)
        ex.set_row(2, 34)
        ex.set_row(3, 34)
        ex.set_row(4, 34)
        ex.set_row(5, 34)
        ex.set_row(6, 34)
        ex.set_row(7, 34)
        ex.set_row(8, 34)
        ex.set_row(9, 34)
        ex.set_row(10, 34)
        ex.set_row(11, 34)
        ex.set_row(12, 34)
        ex.set_row(13, 34)
        ex.set_row(14, 34)
        ex.set_row(15, 34)
        ex.set_row(16, 34)
        ex.set_row(17, 34)
        ex.set_row(18, 34)
        ex.set_row(19, 34)
        ex.set_row(20, 34)
        ex.set_row(21, 34)
        ex.set_row(22, 34)
        ex.set_row(23, 34)
        ex.set_row(24, 34)
        ex.set_row(25, 34)
        ex.set_row(26, 34)
        ex.set_row(27, 34)
        ex.set_row(28, 34)
        ex.set_row(29, 34)
        ex.set_row(30, 34)
        ex.set_row(31, 34)
        ex.set_row(32, 34)
        ex.set_row(33, 34)
        ex.set_row(34, 34)
        ex.set_row(35, 34)
        ex.set_row(36, 34)
        ex.set_row(37, 34)
        ex.set_row(38, 34)
        ex.set_row(39, 34)
        ex.set_row(40, 34)
        ex.set_column("C:C", 78, wrap)

        for name, df in [("README", pd.DataFrame(readme_rows, columns=["Section","Details"])), ("Primary_Metrics", metric_dict), ("QC_Tiers", qc), ("Day39_Neuron_Changes", day39_neuron), ("Well_Day_Summary", well_summary), ("Pair_Effects", pair_effects), ("Day39_Effects", day39), ("Manual_Review_Queue", review_queue), ("Run_Metadata", runmeta)]:
            ws = xw.sheets[name]
            ncols = max(1, len(df.columns))
            if len(df.columns):
                ws.set_row(0, 30, hdr)
                ws.autofilter(0,0,max(len(df),1),ncols-1)
            ws.freeze_panes(1, 1 if name in {"QC_Tiers","Day39_Neuron_Changes"} else 0)
            for j, col in enumerate(df.columns):
                width = min(max(len(str(col))+2, 12), 32)
                if col in {"condition","qc_reasons","review_reasons","hard_exclusion_reasons","interpretation_note","biological_question","Details"}: width = 46
                ws.set_column(j,j,width, wrap if width >= 40 else None)
        ws = xw.sheets["QC_Tiers"]
        if "analysis_qc_tier" in qc.columns:
            c = qc.columns.get_loc("analysis_qc_tier")
            ws.conditional_format(1,c,len(qc),c,{"type":"text","criteria":"containing","value":"A_include","format":good})
            ws.conditional_format(1,c,len(qc),c,{"type":"text","criteria":"containing","value":"B_include_review","format":reviewf})
            ws.conditional_format(1,c,len(qc),c,{"type":"text","criteria":"containing","value":"C_exclude","format":bad})


def build_manifest(root):
    rows=[]
    for p in sorted(root.rglob("*")):
        if p.is_file():
            rows.append({"relative_path":str(p.relative_to(root)),"size_bytes":p.stat().st_size,"size_mb":round(p.stat().st_size/1024/1024,3)})
    df=pd.DataFrame(rows)
    df.to_csv(root/"MANIFEST.csv",index=False)
    return df


def main():
    args = parse_args()
    atlas = args.atlas_root
    out = args.output_root
    dirs = {
        "start": out/"00_START_HERE",
        "core": out/"01_CORE_DATA",
        "qc": out/"02_QC_IDENTITY",
        "contacts": out/"02_QC_IDENTITY"/"review_contact_sheets",
        "traj": out/"03_TRAJECTORY_ANALYSIS",
        "plots": out/"03_TRAJECTORY_ANALYSIS"/"plots",
        "vid": out/"04_VIDEOS"/"individual",
        "pairs": out/"04_VIDEOS"/"pair_comparisons",
        "meta": out/"05_METADATA_METHODS",
    }
    for d in dirs.values(): d.mkdir(parents=True, exist_ok=True)

    master = pd.read_csv(atlas/"all_neurons_longitudinal_master.csv")
    tracks = pd.read_csv(atlas/"neuron_track_summary.csv")
    video_manifest = pd.read_csv(atlas/"video_manifest.csv") if (atlas/"video_manifest.csv").exists() else pd.DataFrame()
    runmeta = pd.read_csv(atlas/"run_metadata.csv") if (atlas/"run_metadata.csv").exists() else pd.DataFrame()

    master_dist, qc = build_identity_qc(master, tracks)
    master_qc, traj_long, well_day, pair_effects, cross_pair, day39 = build_trajectory_tables(master_dist, qc, args.days)
    metric_dict = primary_metric_dictionary()

    # Primary outputs.
    qc.to_csv(dirs["qc"]/"identity_qc_tracks.csv", index=False)
    tier_counts = qc["analysis_qc_tier"].value_counts().reindex(["A_include","B_include_review","C_exclude"], fill_value=0)
    tier_counts.rename_axis("analysis_qc_tier").reset_index(name="n_tracks").to_csv(dirs["qc"]/"qc_tier_counts.csv", index=False)

    review_queue = qc.loc[qc["analysis_qc_tier"].isin(["B_include_review","C_exclude"])].copy()
    review_queue = review_queue.sort_values(["qc_severity","valid_days","mean_template_match_score"], ascending=[False,True,True])
    review_queue.to_csv(dirs["qc"]/"manual_review_queue.csv", index=False)

    contact_df = make_contact_sheets(master_dist, qc, dirs["contacts"], args.alignment_channel, args.contact_box_size, args.max_contact_sheets)
    contact_df.to_csv(dirs["qc"]/"contact_sheet_manifest.csv", index=False)
    if not contact_df.empty:
        review_queue = review_queue.merge(contact_df[["neuron_id","contact_sheet_path"]], on="neuron_id", how="left")
        review_queue.to_csv(dirs["qc"]/"manual_review_queue.csv", index=False)

    master_qc.to_csv(dirs["core"]/"all_neurons_longitudinal_master_with_qc.csv", index=False)
    qc.to_csv(dirs["core"]/"neuron_track_summary_with_qc.csv", index=False)
    metric_dict.to_csv(dirs["core"]/"primary_metric_dictionary.csv", index=False)

    traj_long.to_csv(dirs["traj"]/"primary_metric_neuron_day.csv", index=False)
    well_day.to_csv(dirs["traj"]/"well_day_primary_summary.csv", index=False)
    pair_effects.to_csv(dirs["traj"]/"pair_day_primary_effects.csv", index=False)
    cross_pair.to_csv(dirs["traj"]/"cross_pair_primary_effects.csv", index=False)
    day39.to_csv(dirs["traj"]/"day39_primary_effects.csv", index=False)
    make_plots(well_day, pair_effects, dirs["plots"], args.days)

    # Copy videos and supporting metadata.
    copied_ind = copy_tree_files(atlas/"videos", dirs["vid"], "*.mp4")
    copied_pairs = copy_tree_files(args.pair_root, dirs["pairs"], "*.mp4")
    for fname in ["well_summary.csv","qc_failures.csv","video_manifest.csv","run_metadata.csv","neuron_track_summary.csv","all_neurons_longitudinal_master.csv","neuron_longitudinal_atlas.xlsx"]:
        p=atlas/fname
        if p.exists(): shutil.copy2(p, dirs["meta"]/p.name)

    counts = {
        "tracks": int(qc["neuron_id"].nunique()),
        "rows": int(len(master_qc)),
        "valid9": int((qc["valid_days"] == len(args.days)).sum()) if "valid_days" in qc.columns else np.nan,
        "videos": len(copied_ind),
        "pair_videos": len(copied_pairs),
    }
    executive_rows = [
        ("Automatically detected tracks", counts["tracks"], "Every compact Day-8 488 candidate that passed candidate filters; not a manually proven census of all biological neurons."),
        ("Neuron-day rows", counts["rows"], "One row per neuron per visit."),
        ("Original 9/9-valid tracks", counts["valid9"], "Original atlas tracking validity before the informal identity tiering."),
        ("A_include", int(tier_counts.get("A_include",0)), "Strong automated identity consistency; strict sensitivity set."),
        ("B_include_review", int(tier_counts.get("B_include_review",0)), "Plausible identity with soft flag(s); included in requested informal exploratory set, prioritized for visual review."),
        ("C_exclude", int(tier_counts.get("C_exclude",0)), "Severe QC concern; exclude from biological inference unless manually rescued."),
        ("Primary analysis set", "A + B", "Informal/exploratory analysis requested; always compare with A-only sensitivity."),
        ("Biological replicate structure", "3 matched well pairs", "Do not treat hundreds of neurons as independent biological replicates."),
        ("Primary metrics", "5", "Diffuse:punctate ratio, puncta density, diffuse mean, punctate integrated intensity, total mCherry."),
        ("Individual videos", len(copied_ind), "Representative best-QC tracks from the atlas."),
        ("Matched-pair videos", len(copied_pairs), "Corrected fixed-support E/F, I/J, M/N pair comparisons."),
        ("Interpretation guardrail", "mCherry phenotype", "mCherry redistribution is not direct proof of fibrils or lysosomal rupture."),
    ]
    if not day39.empty:
        for _, r in day39.loc[day39["analysis_set"]=="informal_AplusB"].iterrows():
            executive_rows.append((f"Day39 pair effect: {r['metric']}", round(float(r['median_pair_difference_log2_fold']),4), f"TMEM minus control; {r['direction_consistency']} across {int(r['n_pairs'])} matched pairs."))

    readme_rows = [
        ("Purpose", "PI/lab-ready frozen package for automated identity QC, longitudinal trajectory review, and sharing."),
        ("Identity validation", "Automated consistency validation uses template scores, stepwise motion, repeated/isolated close-anchor events, fixed-support validity/area, and adaptive/support overlap. B/C require visual review; contact sheets are provided."),
        ("QC tiers", "A_include = strong automated consistency; B_include_review = acceptable for informal exploratory analysis but review recommended; C_exclude = do not use for inference unless manually rescued."),
        ("Analysis sets", "Main informal analysis = A+B. Sensitivity = A only. Prefer conclusions robust to both."),
        ("Primary metrics", ", ".join([x['metric'] for x in PRIMARY_METRICS])),
        ("Trajectory normalization", "Within-neuron Day-8 baseline. CSVs include raw value, delta, relative value, percent change, and log2 fold."),
        ("Matched-pair inference", "Summarize neurons within each well first, then compare E05/F05, I05/J05, and M05/N05. n=3 matched well pairs for biological replication."),
        ("Caveat", "Automated Day-8 488 candidates and automated tracking are not equivalent to manually verified biological identity. Use contact sheets/videos before final claims."),
        ("mCherry caveat", "Do not describe mCherry redistribution or rupture_like_score as direct evidence of fibrils or membrane rupture."),
        ("Start here", "Executive_Summary -> QC_Tiers/Manual_Review_Queue -> primary trajectory plots -> matched-pair videos -> detailed longitudinal data."),
    ]
    # Write README before Excel so the package still has a human-readable
    # entry point even if a workbook writer encounters an environment issue.
    write_readme(dirs["start"]/"README_TMEM106B_neuron_atlas.md", counts, tier_counts, day39)
    day39_neuron = traj_long.loc[traj_long["day"] == args.days[-1]].copy()
    workbook_path = dirs["start"]/"TMEM106B_neuron_atlas_PI_review.xlsx"
    try:
        write_excel(workbook_path, executive_rows, readme_rows, metric_dict, qc, day39_neuron, well_day, pair_effects, day39, review_queue, runmeta)
    except Exception as exc:
        # Compact fallback workbook: preserve the key PI-facing sheets rather
        # than failing the entire share-package build.
        import xlsxwriter
        with pd.ExcelWriter(workbook_path, engine="xlsxwriter") as xw:
            pd.DataFrame(executive_rows, columns=["Item","Value","Interpretation"]).to_excel(xw, sheet_name="Executive_Summary", index=False)
            pd.DataFrame(readme_rows, columns=["Section","Details"]).to_excel(xw, sheet_name="README", index=False)
            metric_dict.to_excel(xw, sheet_name="Primary_Metrics", index=False)
            qc.to_excel(xw, sheet_name="QC_Tiers", index=False)
            day39.to_excel(xw, sheet_name="Day39_Effects", index=False)
        (dirs["start"]/"WORKBOOK_FALLBACK_NOTE.txt").write_text(f"Full compact workbook formatting failed; fallback workbook written. Error: {exc}\n")

    share_text = f"""SHARE THIS FOLDER
=================
Folder: {out}

Recommended recipient entry points:
1. 00_START_HERE/TMEM106B_neuron_atlas_PI_review.xlsx
2. 00_START_HERE/README_TMEM106B_neuron_atlas.md
3. 04_VIDEOS/pair_comparisons/
4. 03_TRAJECTORY_ANALYSIS/plots/

Analysis policy:
- Informal/exploratory: A_include + B_include_review
- Sensitivity: A_include only
- Exclude: C_exclude unless manually rescued

This package is a review snapshot. Do not overwrite it with future reruns; create v2 instead.
"""
    (dirs["start"]/"SHARE_THIS_FOLDER.txt").write_text(share_text)

    manifest = build_manifest(out)
    print("\nPI PACKAGE COMPLETE")
    print(f"Output: {out}")
    print(f"Tracks: {counts['tracks']} | rows: {counts['rows']}")
    print("QC tiers:")
    print(tier_counts.to_string())
    print(f"Review contact sheets: {len(contact_df)}")
    print(f"Individual videos: {len(copied_ind)} | pair videos: {len(copied_pairs)}")
    print(f"Workbook: {workbook_path}")
    print(f"Manifest files: {len(manifest)}")


if __name__ == "__main__":
    main()
