#!/usr/bin/env python
from __future__ import annotations

import argparse
import os
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")

import matplotlib.pyplot as plt
import pandas as pd
import tifffile as tif

from tmem_align.analysis.mcherry_metrics import quantify_mcherry_from_file


DEFAULT_INTERIM_ROOT = Path("/Users/pmihack/claire/tmem_2026/data/TMEM106B_interim")
DEFAULT_PROCESSED_ROOT = Path("/Users/pmihack/claire/tmem_2026/data/TMEM106B_processed")
DEFAULT_COLUMNS = ["05", "06", "07"]
DEFAULT_ROWS = ["E", "F", "I", "J", "M", "N"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare full-frame and ROI-restricted mCherry metrics for processed pilots."
    )
    parser.add_argument("--interim-root", type=Path, default=DEFAULT_INTERIM_ROOT)
    parser.add_argument("--processed-root", type=Path, default=DEFAULT_PROCESSED_ROOT)
    parser.add_argument("--columns", nargs="+", default=DEFAULT_COLUMNS)
    parser.add_argument("--rows", nargs="+", default=DEFAULT_ROWS)
    parser.add_argument("--days-label", default="day8_day25_day39")
    parser.add_argument("--mcherry-channel", type=int, default=1)
    parser.add_argument("--reuse-existing-metrics", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_dir = args.processed_root / "pilot" / "mcherry_roi_quantification"
    output_dir.mkdir(parents=True, exist_ok=True)

    metrics_path = output_dir / "mcherry_full_frame_vs_roi_metrics.csv"
    if args.reuse_existing_metrics and metrics_path.exists():
        combined = pd.read_csv(metrics_path)
        combined = combined.drop(
            columns=[
                "include_in_qc_filtered_analysis",
                "exclusion_reason",
                "stage_distance_xy_um",
                "large_shift",
                "dy",
                "dx",
            ],
            errors="ignore",
        )
    else:
        combined = run_roi_quantification(args)
    combined = attach_qc_report(combined, args.processed_root / "pilot")
    summary = summarize(combined)
    qc_summary = summarize(combined[combined["include_in_qc_filtered_analysis"]])

    summary_path = output_dir / "mcherry_full_frame_vs_roi_condition_summary.csv"
    qc_summary_path = output_dir / "mcherry_full_frame_vs_roi_condition_summary_qc_passing.csv"
    interpretation_path = output_dir / "mcherry_roi_interpretation.md"
    combined.to_csv(metrics_path, index=False)
    summary.to_csv(summary_path, index=False)
    qc_summary.to_csv(qc_summary_path, index=False)

    write_score_comparison(combined, output_dir / "mcherry_full_frame_vs_roi_score_scatter.png")
    write_condition_summary(summary, output_dir / "mcherry_full_frame_vs_roi_condition_summary.png")
    write_delta_trajectories(combined, output_dir / "mcherry_roi_minus_full_frame_delta.png")
    interpretation_path.write_text(render_interpretation(combined, summary, qc_summary), encoding="utf-8")

    print(f"Wrote ROI metrics: {metrics_path}")
    print(f"Wrote ROI condition summary: {summary_path}")
    print(f"Wrote QC-passing ROI condition summary: {qc_summary_path}")
    print(f"Wrote ROI interpretation: {interpretation_path}")
    print(summary.to_string(index=False))


def run_roi_quantification(args: argparse.Namespace) -> pd.DataFrame:
    rows = []
    for column in args.columns:
        for row in args.rows:
            well = f"{row.upper()}{column}"
            stack_path = (
                args.interim_root
                / "pilot"
                / f"{well.lower()}_longitudinal"
                / f"{well}_days_{args.days_label}_registered_common_overlap_tcyx.ome.tif"
            )
            full_metrics_path = (
                args.processed_root
                / "pilot"
                / f"{well.lower()}_longitudinal"
                / f"{well}_days_{args.days_label}_mcherry_metrics.csv"
            )
            if not stack_path.exists() or not full_metrics_path.exists():
                continue

            roi = quantify_mcherry_from_file(stack_path, phenotype_channel_index=args.mcherry_channel)
            page_shape = tif.TiffFile(str(stack_path)).pages[0].shape
            frame_pixels = page_shape[-2] * page_shape[-1]
            roi["roi_fraction"] = roi["cell_roi_area"] / frame_pixels
            roi = roi.rename(columns={"diffuse_mcherry_mean_intensity": "diffuse_mean"})
            full = pd.read_csv(full_metrics_path)
            full = full.rename(columns={"diffuse_mcherry_mean_intensity": "diffuse_mean"})
            merged = full.merge(roi, on="time_index", suffixes=("_full_frame", "_roi"))
            merged.insert(0, "well", well)
            merged.insert(1, "row", row.upper())
            merged.insert(2, "column", column)
            merged.insert(3, "condition", condition_for_row(row.upper()))
            merged.insert(4, "common_overlap_stack", str(stack_path))
            merged["rupture_like_score_roi_minus_full_frame"] = (
                merged["rupture_like_score_roi"] - merged["rupture_like_score_full_frame"]
            )
            merged["diffuse_mean_roi_minus_full_frame"] = (
                merged["diffuse_mean_roi"] - merged["diffuse_mean_full_frame"]
            )
            rows.append(merged)
    if not rows:
        raise FileNotFoundError("No matching common-overlap stacks and full-frame metrics found.")
    return pd.concat(rows, ignore_index=True).sort_values(["column", "row", "well", "day"])


def summarize(combined: pd.DataFrame) -> pd.DataFrame:
    if combined.empty:
        return pd.DataFrame()
    return (
        combined.groupby(["condition", "day"], sort=True)
        .agg(
            n_wells=("well", "nunique"),
            full_frame_score_mean=("rupture_like_score_full_frame", "mean"),
            full_frame_score_sem=("rupture_like_score_full_frame", sem),
            roi_score_mean=("rupture_like_score_roi", "mean"),
            roi_score_sem=("rupture_like_score_roi", sem),
            roi_minus_full_frame_score_mean=("rupture_like_score_roi_minus_full_frame", "mean"),
            roi_area_fraction_mean=("roi_fraction", "mean"),
            roi_area_fraction_sem=("roi_fraction", sem),
            roi_puncta_count_mean=("puncta_count_roi", "mean"),
            full_frame_puncta_count_mean=("puncta_count_full_frame", "mean"),
        )
        .reset_index()
    )


def attach_qc_report(combined: pd.DataFrame, pilot_root: Path) -> pd.DataFrame:
    path = pilot_root / "mcherry_qc_report" / "mcherry_longitudinal_qc_report.csv"
    if not path.exists():
        combined = combined.copy()
        combined["include_in_qc_filtered_analysis"] = False
        combined["exclusion_reason"] = "qc_report_missing"
        return combined
    qc = pd.read_csv(path)
    qc = qc[
        [
            "well",
            "day",
            "include_in_qc_filtered_analysis",
            "exclusion_reason",
            "stage_distance_xy_um",
            "large_shift",
            "dy",
            "dx",
        ]
    ]
    qc["well"] = qc["well"].astype(str).str.upper()
    qc["day"] = qc["day"].astype(int)
    return combined.merge(qc, on=["well", "day"], how="left")


def write_score_comparison(combined: pd.DataFrame, figure_path: Path) -> None:
    fig, ax = plt.subplots(figsize=(6, 5), constrained_layout=True)
    colors = {
        "PLD3 + mCherry": "#2f6f9f",
        "PLD3 + TMEM106B + mCherry": "#b55d15",
    }
    for condition, df in combined.groupby("condition", sort=True):
        ax.scatter(
            df["rupture_like_score_full_frame"],
            df["rupture_like_score_roi"],
            label=condition,
            c=colors[condition],
            alpha=0.8,
            s=50,
        )
    limit = max(
        float(combined["rupture_like_score_full_frame"].max()),
        float(combined["rupture_like_score_roi"].max()),
    )
    ax.plot([0, limit], [0, limit], color="#555555", linewidth=1)
    ax.set_xlabel("Full-frame diffuse / punctate score")
    ax.set_ylabel("ROI-restricted diffuse / punctate score")
    ax.set_title("mCherry score: full frame versus foreground ROI")
    ax.grid(True, alpha=0.25)
    ax.legend()
    fig.savefig(figure_path, dpi=220)
    plt.close(fig)


def write_condition_summary(summary: pd.DataFrame, figure_path: Path) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(11, 4), constrained_layout=True)
    colors = {
        "PLD3 + mCherry": "#2f6f9f",
        "PLD3 + TMEM106B + mCherry": "#b55d15",
    }
    for condition, df in summary.groupby("condition", sort=True):
        axes[0].errorbar(
            df["day"],
            df["full_frame_score_mean"],
            yerr=df["full_frame_score_sem"],
            marker="o",
            linestyle="--",
            capsize=4,
            color=colors[condition],
            label=f"{condition}, full frame",
        )
        axes[0].errorbar(
            df["day"],
            df["roi_score_mean"],
            yerr=df["roi_score_sem"],
            marker="o",
            capsize=4,
            color=colors[condition],
            label=f"{condition}, ROI",
        )
        axes[1].errorbar(
            df["day"],
            df["roi_area_fraction_mean"],
            yerr=df["roi_area_fraction_sem"],
            marker="o",
            capsize=4,
            color=colors[condition],
            label=condition,
        )
    axes[0].set_title("Diffuse / punctate score")
    axes[0].set_xlabel("Day")
    axes[0].grid(True, alpha=0.25)
    axes[1].set_title("Foreground ROI area fraction")
    axes[1].set_xlabel("Day")
    axes[1].grid(True, alpha=0.25)
    axes[0].legend(fontsize=8)
    axes[1].legend(fontsize=8)
    fig.suptitle("Full-frame versus ROI-restricted mCherry quantification")
    fig.savefig(figure_path, dpi=220)
    plt.close(fig)


def write_delta_trajectories(combined: pd.DataFrame, figure_path: Path) -> None:
    fig, ax = plt.subplots(figsize=(8, 4.5), constrained_layout=True)
    for well, df in combined.groupby("well", sort=True):
        ax.plot(
            df["day"],
            df["rupture_like_score_roi_minus_full_frame"],
            marker="o",
            linewidth=1.5,
            alpha=0.75,
            label=well,
        )
    ax.axhline(0, color="#555555", linewidth=1)
    ax.set_xlabel("Day")
    ax.set_ylabel("ROI score minus full-frame score")
    ax.set_title("Effect of foreground ROI restriction by well")
    ax.grid(True, alpha=0.25)
    ax.legend(ncol=3, fontsize=8)
    fig.savefig(figure_path, dpi=220)
    plt.close(fig)


def render_interpretation(
    combined: pd.DataFrame,
    summary: pd.DataFrame,
    qc_summary: pd.DataFrame,
) -> str:
    day25 = summary[summary["day"] == 25].copy()
    qc_day25 = qc_summary[qc_summary["day"] == 25].copy() if not qc_summary.empty else qc_summary
    lines = [
        "# First-pass ROI-based mCherry quantification",
        "",
        "This analysis compares the existing full-frame mCherry diffuse/punctate score against",
        "a conservative foreground-ROI-restricted score for columns 05-07. The ROI mask is",
        "thresholded from the 561 nm mCherry channel and should be treated as preliminary.",
        "",
        "It does not establish lysosomal rupture.",
        "",
        "## Outputs",
        "",
        "- `mcherry_full_frame_vs_roi_metrics.csv`",
        "- `mcherry_full_frame_vs_roi_condition_summary.csv`",
        "- `mcherry_full_frame_vs_roi_condition_summary_qc_passing.csv`",
        "- `mcherry_full_frame_vs_roi_score_scatter.png`",
        "- `mcherry_full_frame_vs_roi_condition_summary.png`",
        "- `mcherry_roi_minus_full_frame_delta.png`",
        "",
        "## Day 25 Summary",
        "",
        markdown_table(
            day25[
                [
                    "condition",
                    "n_wells",
                    "full_frame_score_mean",
                    "roi_score_mean",
                    "roi_minus_full_frame_score_mean",
                    "roi_area_fraction_mean",
                ]
            ]
        ),
        "",
        "## QC-Passing Day 25 Summary",
        "",
        markdown_table(
            qc_day25[
                [
                    "condition",
                    "n_wells",
                    "full_frame_score_mean",
                    "roi_score_mean",
                    "roi_minus_full_frame_score_mean",
                    "roi_area_fraction_mean",
                ]
            ]
            if not qc_day25.empty
            else qc_day25
        ),
        "",
        "## Interpretation",
        "",
        "ROI restriction asks whether the diffuse/punctate trend remains when the analysis is",
        "limited to foreground mCherry signal rather than the whole camera frame. This reduces",
        "the influence of empty background, but it is still not a validated cell segmentation.",
        "",
        f"Rows analyzed: {len(combined)} well/day observations across {combined['well'].nunique()} wells.",
    ]
    return "\n".join(lines) + "\n"


def markdown_table(df: pd.DataFrame) -> str:
    if df.empty:
        return "_None._"
    formatted = df.copy()
    for column in formatted.columns:
        if pd.api.types.is_float_dtype(formatted[column]):
            formatted[column] = formatted[column].map(lambda value: "" if pd.isna(value) else f"{value:.3f}")
    formatted = formatted.fillna("")
    headers = [str(column) for column in formatted.columns]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for _, row in formatted.iterrows():
        lines.append("| " + " | ".join(str(row[column]) for column in formatted.columns) + " |")
    return "\n".join(lines)


def condition_for_row(row: str) -> str:
    if row in {"E", "I", "M"}:
        return "PLD3 + mCherry"
    if row in {"F", "J", "N"}:
        return "PLD3 + TMEM106B + mCherry"
    return "not valid for mCherry puncta/diffusion"


def sem(series: pd.Series) -> float:
    if len(series) < 2:
        return 0.0
    return float(series.sem())


if __name__ == "__main__":
    main()
