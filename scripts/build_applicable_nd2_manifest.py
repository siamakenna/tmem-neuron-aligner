#!/usr/bin/env python
from __future__ import annotations

import argparse
import re
from pathlib import Path

import pandas as pd


DEFAULT_RAW_ROOT = Path(
    "/Users/pmihack/claire/tmem_2026/data/"
    "260213_Feb16recopy_HYdiff_landingpadlines_survival_384well1"
)
DEFAULT_PROCESSED_ROOT = Path("/Users/pmihack/claire/tmem_2026/data/TMEM106B_processed")

REPORTER_ROWS = {"E", "I", "M"}
PRIMARY_ROWS = {"F", "J", "N"}
NO_MCHERRY_ROWS = {"C", "D", "G", "H", "K", "L"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a filename/size-only ND2 manifest and flag mCherry-valid wells."
    )
    parser.add_argument("--raw-root", type=Path, default=DEFAULT_RAW_ROOT)
    parser.add_argument("--processed-root", type=Path, default=DEFAULT_PROCESSED_ROOT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_dir = args.processed_root / "pilot" / "dataset_manifest"
    output_dir.mkdir(parents=True, exist_ok=True)

    manifest = build_manifest(args.raw_root)
    manifest_path = output_dir / "nd2_filename_size_manifest.csv"
    applicable_path = output_dir / "mcherry_applicable_nd2_manifest.csv"
    summary_path = output_dir / "mcherry_applicable_summary.csv"

    manifest.to_csv(manifest_path, index=False)
    applicable = manifest[manifest["mcherry_valid"] & ~manifest["is_brightfield"]].copy()
    applicable.to_csv(applicable_path, index=False)
    summary = summarize_applicable(applicable)
    summary.to_csv(summary_path, index=False)

    print(f"Wrote full filename/size manifest: {manifest_path}")
    print(f"Wrote mCherry-applicable manifest: {applicable_path}")
    print(f"Wrote mCherry-applicable summary: {summary_path}")
    print(summary.to_string(index=False))


def build_manifest(raw_root: Path) -> pd.DataFrame:
    rows = []
    for path in sorted(raw_root.rglob("*.nd2")):
        parsed = parse_filename(path)
        rows.append(
            {
                "path": str(path),
                "parent_folder": path.parent.name,
                "file_name": path.name,
                "file_size_bytes": path.stat().st_size,
                **parsed,
            }
        )
    return pd.DataFrame(rows)


def parse_filename(path: Path) -> dict[str, object]:
    name = path.name
    well = parse_well(name)
    row = well[0] if well else ""
    column = well[1:] if well else ""
    day = parse_day(name)
    channel_label = parse_channel_label(name)
    is_brightfield = "brightfield" in name.lower()
    condition = condition_for_row(row)
    return {
        "day": day,
        "well": well or "",
        "row": row,
        "column": column,
        "channel_label": channel_label,
        "is_brightfield": is_brightfield,
        "condition": condition,
        "mcherry_valid": row in REPORTER_ROWS | PRIMARY_ROWS,
        "safe_for_mcherry_puncta_diffusion": (row in REPORTER_ROWS | PRIMARY_ROWS)
        and not is_brightfield,
    }


def parse_well(name: str) -> str | None:
    match = re.search(r"Well([A-P]\d{2})", name, re.IGNORECASE)
    if not match:
        return None
    return match.group(1).upper()


def parse_day(name: str) -> int | None:
    match = re.search(r"day\s*(\d+)", name, re.IGNORECASE)
    if not match:
        return None
    return int(match.group(1))


def parse_channel_label(name: str) -> str:
    match = re.search(r"Channel(.+?)_Seq", name)
    if not match:
        return ""
    return match.group(1)


def condition_for_row(row: str) -> str:
    if row in REPORTER_ROWS:
        return "PLD3 + mCherry reporter control"
    if row in PRIMARY_ROWS:
        return "PLD3 + TMEM106B + mCherry primary"
    if row in NO_MCHERRY_ROWS:
        return "not valid for mCherry puncta/diffusion"
    return "unmapped_or_other"


def summarize_applicable(applicable: pd.DataFrame) -> pd.DataFrame:
    return (
        applicable.groupby(["condition", "day"], dropna=False, sort=True)
        .agg(
            nd2_files=("path", "count"),
            wells=("well", "nunique"),
            total_bytes=("file_size_bytes", "sum"),
            min_file_size_bytes=("file_size_bytes", "min"),
            max_file_size_bytes=("file_size_bytes", "max"),
        )
        .reset_index()
    )


if __name__ == "__main__":
    main()
