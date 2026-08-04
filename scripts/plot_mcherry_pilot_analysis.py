#!/usr/bin/env python
from __future__ import annotations

import argparse
import os
import re
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


DEFAULT_PROCESSED_ROOT = Path("/Users/pmihack/claire/tmem_2026/data/TMEM106B_processed")

REPORTER_ROWS = {"E", "I", "M"}
PRIMARY_ROWS = {"F", "J", "N"}
PAIR_FOR_ROW = {"E": "E_F", "F": "E_F", "I": "I_J", "J": "I_J", "M": "M_N", "N": "M_N"}

METRICS = [
    ("puncta_count", "Puncta count"),
    ("punctate_mean", "Punctate mean intensity"),
    ("diffuse_mean", "Diffuse mean intensity"),
    ("rupture_like_score", "Diffuse / punctate mean"),
    ("mean_puncta_area_pixels", "Mean puncta area"),
    ("max_puncta_intensity", "Max puncta intensity"),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create graphical summaries from local mCherry longitudinal pilot metrics."
    )
    parser.add_argument("--processed-root", type=Path, default=DEFAULT_PROCESSED_ROOT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    pilot_root = args.processed_root / "pilot"
    output_dir = pilot_root / "mcherry_graphical_analysis"
    output_dir.mkdir(parents=True, exist_ok=True)

    combined = collect_metrics(pilot_root)
    if combined.empty:
        raise FileNotFoundError(f"No mCherry metrics found under {pilot_root}")
    qc = collect_registration_qc(pilot_root)
    combined = attach_registration_qc(combined, qc)
    analysis_qc = collect_analysis_qc(pilot_root)
    if not analysis_qc.empty:
        combined = attach_analysis_qc(combined, analysis_qc)
        qc_passing = combined[combined["include_in_qc_filtered_analysis"]].copy()
    else:
        combined["include_in_qc_filtered_analysis"] = combined["registration_qc_pass"]
        combined["exclusion_reason"] = np.where(
            combined["include_in_qc_filtered_analysis"],
            "included",
            "registration_qc_missing_or_failed",
        )
        qc_passing = combined[combined["registration_qc_pass"]].copy()

    group_summary = summarize_by_condition(combined)
    paired_delta = summarize_paired_delta(combined)
    qc_group_summary = summarize_by_condition(qc_passing) if not qc_passing.empty else pd.DataFrame()
    qc_paired_delta = summarize_paired_delta(qc_passing) if not qc_passing.empty else pd.DataFrame()

    combined_path = output_dir / "combined_mcherry_metrics.csv"
    group_path = output_dir / "condition_day_summary.csv"
    delta_path = output_dir / "paired_primary_minus_control_delta.csv"
    qc_group_path = output_dir / "condition_day_summary_qc_passing.csv"
    qc_delta_path = output_dir / "paired_primary_minus_control_delta_qc_passing.csv"
    combined.to_csv(combined_path, index=False)
    group_summary.to_csv(group_path, index=False)
    paired_delta.to_csv(delta_path, index=False)
    qc_group_summary.to_csv(qc_group_path, index=False)
    qc_paired_delta.to_csv(qc_delta_path, index=False)

    write_metric_grid(combined, output_dir / "mcherry_metric_trajectories.png")
    write_metric_grid(qc_passing, output_dir / "mcherry_metric_trajectories_qc_passing.png")
    write_group_summary(
        group_summary,
        output_dir / "mcherry_condition_mean_sem.png",
        title="Condition mean +/- SEM for processed mCherry-valid wells",
    )
    write_group_summary(
        qc_group_summary,
        output_dir / "mcherry_condition_mean_sem_qc_passing.png",
        title="Condition mean +/- SEM for QC-passing mCherry-valid observations",
    )
    write_delta_figure(
        paired_delta,
        output_dir / "mcherry_primary_minus_control_delta.png",
        title="Matched primary-control differences",
    )
    write_delta_figure(
        qc_paired_delta,
        output_dir / "mcherry_primary_minus_control_delta_qc_passing.png",
        title="Matched primary-control differences, QC-passing observations only",
    )
    write_puncta_diffuse_scatter(combined, output_dir / "mcherry_puncta_diffuse_scatter.png")
    write_puncta_diffuse_scatter(
        qc_passing,
        output_dir / "mcherry_puncta_diffuse_scatter_qc_passing.png",
    )

    print(f"Wrote combined metrics: {combined_path}")
    print(f"Wrote condition/day summary: {group_path}")
    print(f"Wrote paired deltas: {delta_path}")
    print(f"Wrote QC-passing condition/day summary: {qc_group_path}")
    print(f"Wrote QC-passing paired deltas: {qc_delta_path}")
    print(f"Wrote figures under: {output_dir}")
    print(group_summary.to_string(index=False))
    if not qc_group_summary.empty:
        print("\nQC-passing summary:")
        print(qc_group_summary.to_string(index=False))


def collect_metrics(pilot_root: Path) -> pd.DataFrame:
    rows: list[pd.DataFrame] = []
    for path in sorted(pilot_root.glob("*_longitudinal/*_mcherry_metrics.csv")):
        well = infer_well(path)
        if well is None or not is_mcherry_valid(well):
            continue
        df = pd.read_csv(path)
        row = well[0]
        column = well[1:]
        df.insert(0, "well", well)
        df.insert(1, "row", row)
        df.insert(2, "column", column)
        df.insert(3, "condition", condition_for_row(row))
        df.insert(4, "condition_label", condition_label_for_row(row))
        df.insert(5, "replicate_pair", f"{PAIR_FOR_ROW[row]}_{column}")
        df.insert(6, "source_metrics_csv", str(path))
        rows.append(df)
    if not rows:
        return pd.DataFrame()
    return pd.concat(rows, ignore_index=True).sort_values(["column", "replicate_pair", "well", "day"])


def collect_registration_qc(pilot_root: Path) -> pd.DataFrame:
    rows = []
    for path in sorted(pilot_root.glob("registration_qc*/registration_qc_shift_summary.csv")):
        df = pd.read_csv(path)
        df.insert(0, "registration_qc_source", str(path))
        rows.append(df)
    if not rows:
        return pd.DataFrame()
    qc = pd.concat(rows, ignore_index=True)
    qc["well"] = qc["well"].astype(str).str.upper()
    qc["day"] = qc["day"].astype(int)
    return qc.sort_values(["well", "day", "registration_qc_source"]).drop_duplicates(
        ["well", "day"],
        keep="last",
    )


def attach_registration_qc(combined: pd.DataFrame, qc: pd.DataFrame) -> pd.DataFrame:
    if qc.empty:
        combined = combined.copy()
        combined["registration_qc_available"] = False
        combined["large_shift"] = False
        combined["registration_qc_pass"] = False
        return combined

    qc_columns = [
        "registration_qc_source",
        "well",
        "day",
        "dy",
        "dx",
        "alignment_corr_to_day8_common_overlap",
        "mcherry_corr_to_day8_common_overlap",
        "large_shift",
        "registered_alignment_montage",
        "registered_mcherry_montage",
        "common_overlap_mcherry_montage",
        "alignment_overlay",
    ]
    available_columns = [column for column in qc_columns if column in qc.columns]
    merged = combined.merge(qc[available_columns], on=["well", "day"], how="left")
    merged["registration_qc_available"] = merged["registration_qc_source"].notna()
    merged["large_shift"] = merged["large_shift"].fillna(False).astype(bool)
    merged["registration_qc_pass"] = merged["registration_qc_available"] & ~merged["large_shift"]
    return merged


def collect_analysis_qc(pilot_root: Path) -> pd.DataFrame:
    path = pilot_root / "mcherry_qc_report" / "mcherry_longitudinal_qc_report.csv"
    if not path.exists():
        return pd.DataFrame()
    report = pd.read_csv(path)
    report["well"] = report["well"].astype(str).str.upper()
    report["day"] = report["day"].astype(int)
    return report


def attach_analysis_qc(combined: pd.DataFrame, report: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "well",
        "day",
        "include_in_qc_filtered_analysis",
        "exclusion_reason",
        "stage_prefilter_available",
        "stage_prefilter_pass",
        "stage_prefilter_reason",
        "stage_distance_xy_um",
        "stage_xy_threshold_um",
        "stage_distance_z_um",
    ]
    available = [column for column in columns if column in report.columns]
    merged = combined.merge(report[available], on=["well", "day"], how="left")
    merged["include_in_qc_filtered_analysis"] = (
        merged["include_in_qc_filtered_analysis"].fillna(False).astype(bool)
    )
    merged["exclusion_reason"] = merged["exclusion_reason"].fillna("qc_report_missing")
    return merged


def infer_well(path: Path) -> str | None:
    match = re.search(r"([A-P]\d{2})_days_", path.name, re.IGNORECASE)
    if not match:
        return None
    return match.group(1).upper()


def is_mcherry_valid(well: str) -> bool:
    return well[0] in REPORTER_ROWS | PRIMARY_ROWS


def condition_for_row(row: str) -> str:
    if row in REPORTER_ROWS:
        return "PLD3_mCherry_reporter_control"
    if row in PRIMARY_ROWS:
        return "PLD3_TMEM106B_mCherry_primary"
    raise ValueError(f"Row {row} is not mCherry-valid")


def condition_label_for_row(row: str) -> str:
    if row in REPORTER_ROWS:
        return "PLD3 + mCherry"
    if row in PRIMARY_ROWS:
        return "PLD3 + TMEM106B + mCherry"
    raise ValueError(f"Row {row} is not mCherry-valid")


def summarize_by_condition(combined: pd.DataFrame) -> pd.DataFrame:
    summary = (
        combined.groupby(["condition", "condition_label", "day"], sort=True)
        .agg(
            n_wells=("well", "nunique"),
            puncta_count_mean=("puncta_count", "mean"),
            puncta_count_sem=("puncta_count", sem),
            punctate_mean_mean=("punctate_mean", "mean"),
            punctate_mean_sem=("punctate_mean", sem),
            diffuse_mean_mean=("diffuse_mean", "mean"),
            diffuse_mean_sem=("diffuse_mean", sem),
            rupture_like_score_mean=("rupture_like_score", "mean"),
            rupture_like_score_sem=("rupture_like_score", sem),
            mean_puncta_area_pixels_mean=("mean_puncta_area_pixels", "mean"),
            mean_puncta_area_pixels_sem=("mean_puncta_area_pixels", sem),
            max_puncta_intensity_mean=("max_puncta_intensity", "mean"),
            max_puncta_intensity_sem=("max_puncta_intensity", sem),
        )
        .reset_index()
    )
    return summary


def summarize_paired_delta(combined: pd.DataFrame) -> pd.DataFrame:
    pivot = combined.pivot_table(
        index=["column", "replicate_pair", "day"],
        columns="condition",
        values=[metric for metric, _ in METRICS],
        aggfunc="mean",
    )
    rows = []
    for index, values in pivot.iterrows():
        column, replicate_pair, day = index
        row = {"column": column, "replicate_pair": replicate_pair, "day": day}
        for metric, _ in METRICS:
            try:
                primary = values[(metric, "PLD3_TMEM106B_mCherry_primary")]
                control = values[(metric, "PLD3_mCherry_reporter_control")]
            except KeyError:
                primary = np.nan
                control = np.nan
            row[f"{metric}_primary_minus_control"] = primary - control
        rows.append(row)
    return pd.DataFrame(rows).dropna(how="all", subset=[f"{metric}_primary_minus_control" for metric, _ in METRICS])


def sem(series: pd.Series) -> float:
    if len(series) < 2:
        return 0.0
    return float(series.sem())


def write_metric_grid(combined: pd.DataFrame, figure_path: Path) -> None:
    if combined.empty:
        return
    fig, axes = plt.subplots(2, 3, figsize=(15, 8), constrained_layout=True)
    colors = {
        "PLD3 + mCherry": "#2f6f9f",
        "PLD3 + TMEM106B + mCherry": "#b55d15",
    }
    markers = {"05": "o", "06": "s", "07": "^", "08": "D"}
    for ax, (metric, title) in zip(axes.ravel(), METRICS, strict=True):
        for well, df in combined.groupby("well", sort=True):
            label = well
            condition_label = df["condition_label"].iloc[0]
            column = df["column"].iloc[0]
            ax.plot(
                df["day"],
                df[metric],
                marker=markers.get(column, "o"),
                linewidth=1.8,
                alpha=0.85,
                label=label,
                color=colors[condition_label],
            )
        ax.set_title(title)
        ax.set_xlabel("Day")
        ax.grid(True, alpha=0.25)
    handles, labels = axes[0, 0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="outside lower center", ncol=min(len(labels), 8))
    fig.suptitle("mCherry puncta and diffusion metrics by well")
    fig.savefig(figure_path, dpi=220)
    plt.close(fig)


def write_group_summary(group_summary: pd.DataFrame, figure_path: Path, *, title: str) -> None:
    if group_summary.empty:
        return
    fig, axes = plt.subplots(2, 2, figsize=(11, 8), constrained_layout=True)
    metrics = [
        ("puncta_count", "Puncta count"),
        ("punctate_mean", "Punctate mean intensity"),
        ("diffuse_mean", "Diffuse mean intensity"),
        ("rupture_like_score", "Diffuse / punctate mean"),
    ]
    colors = {
        "PLD3 + mCherry": "#2f6f9f",
        "PLD3 + TMEM106B + mCherry": "#b55d15",
    }
    for ax, (metric, metric_title) in zip(axes.ravel(), metrics, strict=True):
        for condition_label, df in group_summary.groupby("condition_label", sort=True):
            ax.errorbar(
                df["day"],
                df[f"{metric}_mean"],
                yerr=df[f"{metric}_sem"],
                marker="o",
                linewidth=2.4,
                capsize=4,
                label=condition_label,
                color=colors[condition_label],
            )
        ax.set_title(metric_title)
        ax.set_xlabel("Day")
        ax.grid(True, alpha=0.25)
    axes[0, 0].legend()
    fig.suptitle(title)
    fig.savefig(figure_path, dpi=220)
    plt.close(fig)


def write_delta_figure(paired_delta: pd.DataFrame, figure_path: Path, *, title: str) -> None:
    if paired_delta.empty:
        return
    fig, axes = plt.subplots(1, 2, figsize=(11, 4), constrained_layout=True)
    metrics = [
        ("rupture_like_score_primary_minus_control", "Diffuse / punctate delta"),
        ("puncta_count_primary_minus_control", "Puncta count delta"),
    ]
    for ax, (metric, metric_title) in zip(axes, metrics, strict=True):
        for replicate_pair, df in paired_delta.groupby("replicate_pair", sort=True):
            ax.axhline(0, color="#555555", linewidth=1, alpha=0.7)
            ax.plot(df["day"], df[metric], marker="o", linewidth=2, label=replicate_pair)
        ax.set_title(metric_title)
        ax.set_xlabel("Day")
        ax.set_ylabel("Primary minus matched control")
        ax.grid(True, alpha=0.25)
    axes[-1].legend(title="Pair")
    fig.suptitle(title)
    fig.savefig(figure_path, dpi=220)
    plt.close(fig)


def write_puncta_diffuse_scatter(combined: pd.DataFrame, figure_path: Path) -> None:
    if combined.empty:
        return
    fig, ax = plt.subplots(figsize=(7, 5), constrained_layout=True)
    colors = {
        "PLD3 + mCherry": "#2f6f9f",
        "PLD3 + TMEM106B + mCherry": "#b55d15",
    }
    for condition_label, df in combined.groupby("condition_label", sort=True):
        scatter = ax.scatter(
            df["punctate_mean"],
            df["diffuse_mean"],
            s=np.clip(df["puncta_count"] / 4, 25, 260),
            c=df["day"],
            cmap="viridis",
            edgecolor=colors[condition_label],
            linewidth=1.5,
            alpha=0.8,
            label=condition_label,
        )
    ax.set_xlabel("Punctate mean intensity")
    ax.set_ylabel("Diffuse mean intensity")
    ax.set_title("Diffuse versus punctate mCherry signal")
    ax.grid(True, alpha=0.25)
    ax.legend()
    cbar = fig.colorbar(scatter, ax=ax)
    cbar.set_label("Day")
    fig.savefig(figure_path, dpi=220)
    plt.close(fig)


if __name__ == "__main__":
    main()
