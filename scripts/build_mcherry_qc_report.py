#!/usr/bin/env python
from __future__ import annotations

import argparse
import re
from pathlib import Path

import pandas as pd


DEFAULT_PROCESSED_ROOT = Path("/Users/pmihack/claire/tmem_2026/data/TMEM106B_processed")
REPORTER_ROWS = {"E", "I", "M"}
PRIMARY_ROWS = {"F", "J", "N"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a lab-facing mCherry longitudinal QC report from pilot outputs."
    )
    parser.add_argument("--processed-root", type=Path, default=DEFAULT_PROCESSED_ROOT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    pilot_root = args.processed_root / "pilot"
    metrics = collect_metrics(pilot_root)
    registration_qc = collect_registration_qc(pilot_root)
    stage = collect_stage_prefilter(pilot_root)
    report = build_qc_report(metrics, registration_qc, stage)

    output_dir = pilot_root / "mcherry_qc_report"
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "mcherry_longitudinal_qc_report.csv"
    md_path = output_dir / "mcherry_longitudinal_qc_report.md"
    report.to_csv(csv_path, index=False)
    md_path.write_text(render_markdown_summary(report), encoding="utf-8")

    print(f"Wrote QC report CSV: {csv_path}")
    print(f"Wrote QC report Markdown: {md_path}")
    print(report.groupby(["include_in_qc_filtered_analysis", "exclusion_reason"]).size().to_string())


def collect_metrics(pilot_root: Path) -> pd.DataFrame:
    rows = []
    for path in sorted(pilot_root.glob("*_longitudinal/*_mcherry_metrics.csv")):
        well = infer_well(path)
        if well is None or well[0] not in REPORTER_ROWS | PRIMARY_ROWS:
            continue
        df = pd.read_csv(path)
        df.insert(0, "well", well)
        df.insert(1, "row", well[0])
        df.insert(2, "column", well[1:])
        df.insert(3, "condition", condition_for_row(well[0]))
        df.insert(4, "metrics_csv", str(path))
        rows.append(df)
    if not rows:
        raise FileNotFoundError(f"No mCherry longitudinal metric files found under {pilot_root}")
    return pd.concat(rows, ignore_index=True)


def collect_registration_qc(pilot_root: Path) -> pd.DataFrame:
    rows = []
    for path in sorted(pilot_root.glob("registration_qc*/registration_qc_shift_summary.csv")):
        df = pd.read_csv(path)
        df.insert(0, "registration_qc_csv", str(path))
        rows.append(df)
    if not rows:
        return pd.DataFrame(columns=["well", "day"])
    qc = pd.concat(rows, ignore_index=True)
    qc["well"] = qc["well"].astype(str).str.upper()
    qc["day"] = qc["day"].astype(int)
    return qc.sort_values(["well", "day", "registration_qc_csv"]).drop_duplicates(
        ["well", "day"],
        keep="last",
    )


def collect_stage_prefilter(pilot_root: Path) -> pd.DataFrame:
    path = pilot_root / "stage_prefilter" / "mcherry_stage_prefilter.csv"
    if not path.exists():
        return pd.DataFrame(columns=["well", "day"])
    stage = pd.read_csv(path)
    stage["well"] = stage["well"].astype(str).str.upper()
    stage["day"] = stage["day"].astype(int)
    return stage.sort_values(["well", "day"]).drop_duplicates(["well", "day"], keep="last")


def build_qc_report(
    metrics: pd.DataFrame,
    registration_qc: pd.DataFrame,
    stage: pd.DataFrame,
) -> pd.DataFrame:
    registration_columns = [
        "well",
        "day",
        "dy",
        "dx",
        "large_shift",
        "alignment_corr_to_day8_common_overlap",
        "mcherry_corr_to_day8_common_overlap",
        "registration_qc_csv",
        "registered_alignment_montage",
        "registered_mcherry_montage",
        "common_overlap_mcherry_montage",
        "alignment_overlay",
    ]
    stage_columns = [
        "well",
        "day",
        "stage_x_um",
        "stage_y_um",
        "stage_z_um",
        "stage_distance_xy_um",
        "stage_distance_z_um",
        "stage_xy_threshold_um",
        "stage_coordinate_source",
        "stage_prefilter_available",
        "stage_prefilter_pass",
        "stage_prefilter_reason",
    ]
    report = metrics.merge(
        registration_qc[[c for c in registration_columns if c in registration_qc.columns]],
        on=["well", "day"],
        how="left",
    )
    report = report.merge(
        stage[[c for c in stage_columns if c in stage.columns]],
        on=["well", "day"],
        how="left",
    )
    report["registration_qc_available"] = report["registration_qc_csv"].notna()
    report["large_shift"] = report["large_shift"].fillna(False).astype(bool)
    report["stage_prefilter_pass"] = report["stage_prefilter_pass"].fillna(True).astype(bool)
    report["stage_prefilter_available"] = report["stage_prefilter_available"].fillna(False).astype(bool)

    reasons = []
    included = []
    for row in report.to_dict("records"):
        row_reasons = exclusion_reasons(row)
        reasons.append("; ".join(row_reasons) if row_reasons else "included")
        included.append(not row_reasons)
    report["include_in_qc_filtered_analysis"] = included
    report["exclusion_reason"] = reasons

    keep_first = [
        "include_in_qc_filtered_analysis",
        "exclusion_reason",
        "condition",
        "well",
        "row",
        "column",
        "day",
        "file_name",
        "puncta_count",
        "punctate_mean",
        "diffuse_mean",
        "rupture_like_score",
        "registration_qc_available",
        "large_shift",
        "dy",
        "dx",
        "stage_prefilter_available",
        "stage_prefilter_pass",
        "stage_prefilter_reason",
        "stage_distance_xy_um",
        "stage_xy_threshold_um",
        "stage_distance_z_um",
        "stage_x_um",
        "stage_y_um",
        "stage_z_um",
    ]
    ordered = [c for c in keep_first if c in report.columns]
    remaining = [c for c in report.columns if c not in ordered]
    return report[ordered + remaining].sort_values(["column", "row", "well", "day"])


def exclusion_reasons(row: dict[str, object]) -> list[str]:
    reasons = []
    if not bool(row.get("registration_qc_available")):
        reasons.append("registration_qc_missing")
    if bool(row.get("large_shift")):
        reasons.append("registration_large_shift")
    if not bool(row.get("stage_prefilter_pass", True)):
        reasons.append(str(row.get("stage_prefilter_reason") or "stage_prefilter_failed"))
    return reasons


def render_markdown_summary(report: pd.DataFrame) -> str:
    included = report[report["include_in_qc_filtered_analysis"]]
    excluded = report[~report["include_in_qc_filtered_analysis"]]
    lines = [
        "# mCherry Longitudinal QC Report",
        "",
        "Preliminary automated QC for the mCherry longitudinal pilot. This report combines",
        "registration shift flags and metadata-only XY stage-coordinate prefiltering. It does",
        "not claim lysosomal rupture.",
        "",
        "## Scope",
        "",
        f"- Observations reviewed: {len(report)}",
        f"- Included observations: {len(included)}",
        f"- Excluded observations: {len(excluded)}",
        f"- Wells reviewed: {report['well'].nunique()}",
        f"- Days reviewed: {', '.join(str(day) for day in sorted(report['day'].unique()))}",
        "",
        "## Inclusion By Condition And Day",
        "",
        markdown_table(
            report.groupby(["condition", "day", "include_in_qc_filtered_analysis"])
            .size()
            .reset_index(name="observations")
        ),
        "",
        "## Exclusion Reasons",
        "",
        markdown_table(excluded.groupby("exclusion_reason").size().reset_index(name="observations")),
        "",
        "## Included Observations",
        "",
        markdown_table(
            included[
                [
                    "condition",
                    "well",
                    "column",
                    "day",
                    "stage_distance_xy_um",
                    "dy",
                    "dx",
                    "rupture_like_score",
                ]
            ]
        ),
        "",
        "## Excluded Observations",
        "",
        markdown_table(
            excluded[
                [
                    "condition",
                    "well",
                    "column",
                    "day",
                    "exclusion_reason",
                    "stage_distance_xy_um",
                    "dy",
                    "dx",
                    "rupture_like_score",
                ]
            ]
        ),
        "",
        "## Notes",
        "",
        "- Stage prefiltering uses XY distance only by default. Z values are retained for review,",
        "  but are not exclusionary because these ND2 files mix relative and absolute Z metadata.",
        "- Registration large-shift flags are currently the dominant exclusion reason.",
        "- Rows C/D/G/H/K/L remain excluded from mCherry puncta/diffusion interpretation because",
        "  they do not contain mCherry reporter signal by design.",
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


def infer_well(path: Path) -> str | None:
    match = re.search(r"([A-P]\d{2})_days_", path.name, re.IGNORECASE)
    if not match:
        return None
    return match.group(1).upper()


def condition_for_row(row: str) -> str:
    if row in REPORTER_ROWS:
        return "PLD3 + mCherry"
    if row in PRIMARY_ROWS:
        return "PLD3 + TMEM106B + mCherry"
    return "not valid for mCherry puncta/diffusion"


if __name__ == "__main__":
    main()
