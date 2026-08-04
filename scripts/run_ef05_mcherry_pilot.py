#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")

import matplotlib.pyplot as plt
import pandas as pd
import tifffile as tif

from tmem_align.nd2_tools import extract_nd2_selection, inspect_nd2
from tmem_align.analysis.mcherry_metrics import quantify_mcherry_from_file


DEFAULT_RAW_ROOT = Path(
    "/Users/pmihack/claire/tmem_2026/data/"
    "260213_Feb16recopy_HYdiff_landingpadlines_survival_384well1"
)
DEFAULT_INTERIM_ROOT = Path("/Users/pmihack/claire/tmem_2026/data/TMEM106B_interim")
DEFAULT_PROCESSED_ROOT = Path("/Users/pmihack/claire/tmem_2026/data/TMEM106B_processed")

PILOT_FILES = {
    "E05": {
        "condition": "PLD3_mCherry_reporter_control",
        "nd2_relpath": (
            "20260305_171612_406/"
            "260305_day25_iNeurons_WellE05_Channel405nm Binned,561nm Binned,488nm Binned_Seq0032.nd2"
        ),
    },
    "F05": {
        "condition": "PLD3_TMEM106B_mCherry_primary",
        "nd2_relpath": (
            "20260305_171612_406/"
            "260305_day25_iNeurons_WellF05_Channel405nm Binned,561nm Binned,488nm Binned_Seq0048.nd2"
        ),
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run a tiny fluorescence-only E05/F05 mCherry pilot. This is an image-level "
            "screen, not a validated neuron ROI longitudinal analysis."
        )
    )
    parser.add_argument("--raw-root", type=Path, default=DEFAULT_RAW_ROOT)
    parser.add_argument("--interim-root", type=Path, default=DEFAULT_INTERIM_ROOT)
    parser.add_argument("--processed-root", type=Path, default=DEFAULT_PROCESSED_ROOT)
    parser.add_argument("--channel", type=int, default=1, help="Zero-based channel index; 1 is 561nm in the pilot files.")
    parser.add_argument("--force", action="store_true", help="Overwrite existing pilot OME-TIFF previews.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    pilot_interim = args.interim_root / "pilot" / "ef05_mcherry"
    pilot_processed = args.processed_root / "pilot" / "ef05_mcherry"
    pilot_interim.mkdir(parents=True, exist_ok=True)
    pilot_processed.mkdir(parents=True, exist_ok=True)

    rows: list[pd.DataFrame] = []
    metadata: dict[str, Any] = {
        "analysis_scope": (
            "Preliminary image-level mCherry puncta/diffuse screen on one E05 and one F05 "
            "fluorescence frame. Not a stitched, registered, neuron ROI, or longitudinal result."
        ),
        "channel_index": args.channel,
        "wells": {},
    }

    for well, spec in PILOT_FILES.items():
        nd2_path = args.raw_root / spec["nd2_relpath"]
        if not nd2_path.exists():
            raise FileNotFoundError(nd2_path)

        info = inspect_nd2(nd2_path)
        channel_names = info["channel_names"]
        if args.channel < 0 or args.channel >= len(channel_names):
            raise IndexError(f"Channel {args.channel} outside available channels: {channel_names}")

        output_path = pilot_interim / f"260305_day25_Well{well}_ch{args.channel}_preview.ome.tif"
        if args.force or not output_path.exists():
            extract_nd2_selection(nd2_path, output_path, channel=args.channel)

        metrics = quantify_mcherry_from_file(output_path)
        metrics.insert(0, "well", well)
        metrics.insert(1, "condition", spec["condition"])
        metrics.insert(2, "channel_index", args.channel)
        metrics.insert(3, "channel_name", channel_names[args.channel])
        metrics.insert(4, "preview_path", str(output_path))
        rows.append(metrics)

        arr = tif.imread(output_path)
        metadata["wells"][well] = {
            "condition": spec["condition"],
            "nd2_path": str(nd2_path),
            "nd2_size_bytes": nd2_path.stat().st_size,
            "nd2_axes": info["axis_order"],
            "nd2_sizes": info["sizes"],
            "channels": channel_names,
            "selected_channel_index": args.channel,
            "selected_channel_name": channel_names[args.channel],
            "preview_path": str(output_path),
            "preview_size_bytes": output_path.stat().st_size,
            "array_shape": list(arr.shape),
            "array_dtype": str(arr.dtype),
            "array_min": int(arr.min()),
            "array_max": int(arr.max()),
        }

    results = pd.concat(rows, ignore_index=True)
    csv_path = pilot_processed / "ef05_mcherry_pilot_metrics.csv"
    json_path = pilot_processed / "ef05_mcherry_pilot_metadata.json"
    figure_path = pilot_processed / "ef05_mcherry_pilot_summary.png"

    results.to_csv(csv_path, index=False)
    json_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    write_summary_figure(results, figure_path)

    print(f"Wrote metrics: {csv_path}")
    print(f"Wrote metadata: {json_path}")
    print(f"Wrote figure: {figure_path}")
    print(results.to_string(index=False))


def write_summary_figure(results: pd.DataFrame, figure_path: Path) -> None:
    fig, axes = plt.subplots(1, 3, figsize=(11, 3.5), constrained_layout=True)
    labels = results["well"] + "\n" + results["condition"].str.replace("_", "\n")
    metrics = [
        ("puncta_count", "Puncta count"),
        ("diffuse_mean", "Diffuse mean"),
        ("rupture_like_score", "Diffuse / punctate mean"),
    ]
    colors = ["#4c78a8", "#f58518"]
    for ax, (column, title) in zip(axes, metrics, strict=True):
        ax.bar(labels, results[column], color=colors[: len(results)])
        ax.set_title(title)
        ax.tick_params(axis="x", labelrotation=0)
    fig.suptitle("E05 vs F05 preliminary image-level mCherry screen")
    figure_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(figure_path, dpi=180)
    plt.close(fig)


if __name__ == "__main__":
    main()
