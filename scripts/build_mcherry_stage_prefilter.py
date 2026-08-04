#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

from tmem_align.stage_qc import (
    DEFAULT_STAGE_XY_THRESHOLD_UM,
    build_stage_prefilter_rows,
    read_nd2_stage_coordinates,
)


DEFAULT_PROCESSED_ROOT = Path("/Users/pmihack/claire/tmem_2026/data/TMEM106B_processed")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build metadata-only stage-coordinate prefilter rows for processed mCherry pilots."
    )
    parser.add_argument("--processed-root", type=Path, default=DEFAULT_PROCESSED_ROOT)
    parser.add_argument("--reference-day", type=int, default=8)
    parser.add_argument("--stage-xy-threshold-um", type=float, default=DEFAULT_STAGE_XY_THRESHOLD_UM)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    pilot_root = args.processed_root / "pilot"
    manifest_path = pilot_root / "dataset_manifest" / "mcherry_applicable_nd2_manifest.csv"
    if not manifest_path.exists():
        raise FileNotFoundError(
            f"Expected applicable manifest at {manifest_path}; run build_applicable_nd2_manifest.py first."
        )

    observations = collect_processed_observations(pilot_root, manifest_path)
    rows = []
    for well, well_rows in observations.groupby("well", sort=True):
        stage_rows = [
            row.dropna().to_dict()
            for _, row in well_rows.sort_values("day").iterrows()
        ]
        rows.extend(
            build_stage_prefilter_rows(
                stage_rows,
                reference_day=args.reference_day,
                threshold_um=args.stage_xy_threshold_um,
            )
        )

    output_dir = pilot_root / "stage_prefilter"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "mcherry_stage_prefilter.csv"
    summary_path = output_dir / "mcherry_stage_prefilter_summary.csv"
    result = pd.DataFrame(rows)
    result.to_csv(output_path, index=False)
    summarize(result).to_csv(summary_path, index=False)

    print(f"Wrote stage prefilter: {output_path}")
    print(f"Wrote stage prefilter summary: {summary_path}")
    print(summarize(result).to_string(index=False))


def collect_processed_observations(pilot_root: Path, manifest_path: Path) -> pd.DataFrame:
    manifest = pd.read_csv(manifest_path)
    manifest = manifest[["path", "file_name", "file_size_bytes", "condition", "row", "column"]]
    rows: list[dict[str, Any]] = []
    for metadata_path in sorted(pilot_root.glob("*_longitudinal/*_metadata.json")):
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        well = str(metadata.get("well", "")).upper()
        if not well:
            continue
        for day_record in metadata.get("days", []):
            nd2_path = Path(day_record["nd2_path"])
            manifest_match = manifest[manifest["path"] == str(nd2_path)]
            manifest_row = manifest_match.iloc[0].to_dict() if not manifest_match.empty else {}
            rows.append(
                {
                    "well": well,
                    "day": int(day_record["day"]),
                    "nd2_path": str(nd2_path),
                    "file_name": nd2_path.name,
                    "metadata_json": str(metadata_path),
                    **manifest_row,
                    **read_nd2_stage_coordinates(nd2_path),
                }
            )
    if not rows:
        raise FileNotFoundError(f"No processed longitudinal metadata JSON files found under {pilot_root}")
    return pd.DataFrame(rows)


def summarize(result: pd.DataFrame) -> pd.DataFrame:
    return (
        result.groupby(["stage_prefilter_pass", "stage_prefilter_reason"], dropna=False)
        .agg(observations=("well", "count"), wells=("well", "nunique"))
        .reset_index()
    )


if __name__ == "__main__":
    main()
