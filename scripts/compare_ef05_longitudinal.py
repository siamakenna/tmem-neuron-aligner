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


DEFAULT_PROCESSED_ROOT = Path("/Users/pmihack/claire/tmem_2026/data/TMEM106B_processed")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Combine matched same-well longitudinal pilot metrics into comparison tables."
    )
    parser.add_argument("--processed-root", type=Path, default=DEFAULT_PROCESSED_ROOT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    pilot_root = args.processed_root / "pilot"
    inputs = {
        "E05": {
            "condition": "PLD3_mCherry_reporter_control",
            "pair": "E05_F05",
            "path": pilot_root
            / "e05_longitudinal"
            / "E05_days_day8_day25_day39_mcherry_metrics.csv",
        },
        "F05": {
            "condition": "PLD3_TMEM106B_mCherry_primary",
            "pair": "E05_F05",
            "path": pilot_root
            / "f05_longitudinal"
            / "F05_days_day8_day25_day39_mcherry_metrics.csv",
        },
        "I05": {
            "condition": "PLD3_mCherry_reporter_control",
            "pair": "I05_J05",
            "path": pilot_root
            / "i05_longitudinal"
            / "I05_days_day8_day25_day39_mcherry_metrics.csv",
        },
        "J05": {
            "condition": "PLD3_TMEM106B_mCherry_primary",
            "pair": "I05_J05",
            "path": pilot_root
            / "j05_longitudinal"
            / "J05_days_day8_day25_day39_mcherry_metrics.csv",
        },
        "M05": {
            "condition": "PLD3_mCherry_reporter_control",
            "pair": "M05_N05",
            "path": pilot_root
            / "m05_longitudinal"
            / "M05_days_day8_day25_day39_mcherry_metrics.csv",
        },
        "N05": {
            "condition": "PLD3_TMEM106B_mCherry_primary",
            "pair": "M05_N05",
            "path": pilot_root
            / "n05_longitudinal"
            / "N05_days_day8_day25_day39_mcherry_metrics.csv",
        },
    }

    rows = []
    available_wells = []
    for well, spec in inputs.items():
        path = spec["path"]
        if not path.exists():
            continue
        df = pd.read_csv(path)
        df.insert(0, "well", well)
        df.insert(1, "condition", spec["condition"])
        df.insert(2, "pair", spec["pair"])
        rows.append(df)
        available_wells.append(well)

    combined = pd.concat(rows, ignore_index=True)
    write_outputs(combined, pilot_root, "_".join(available_wells))
    for pair, pair_df in combined.groupby("pair", sort=True):
        write_outputs(pair_df.reset_index(drop=True), pilot_root, pair)
    print(combined.to_string(index=False))


def write_outputs(combined: pd.DataFrame, pilot_root: Path, label: str) -> None:
    out_dir = pilot_root / f"{label.lower()}_longitudinal_comparison"
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / f"{label}_days_day8_day25_day39_comparison_metrics.csv"
    figure_path = out_dir / f"{label}_days_day8_day25_day39_comparison_summary.png"
    combined.to_csv(csv_path, index=False)
    write_comparison_figure(combined, figure_path)
    print(f"Wrote comparison metrics: {csv_path}")
    print(f"Wrote comparison figure: {figure_path}")


def write_comparison_figure(combined: pd.DataFrame, figure_path: Path) -> None:
    fig, axes = plt.subplots(1, 3, figsize=(12, 3.8), constrained_layout=True)
    metrics = [
        ("puncta_count", "Puncta count"),
        ("diffuse_mean", "Diffuse mean"),
        ("rupture_like_score", "Diffuse / punctate mean"),
    ]
    colors = {
        "E05": "#4c78a8",
        "F05": "#f58518",
        "I05": "#54a24b",
        "J05": "#e45756",
        "M05": "#72b7b2",
        "N05": "#b279a2",
    }
    for ax, (column, title) in zip(axes, metrics, strict=True):
        for well, df in combined.groupby("well", sort=True):
            ax.plot(
                df["day"],
                df[column],
                marker="o",
                linewidth=2,
                label=well,
                color=colors.get(well),
            )
        ax.set_title(title)
        ax.set_xlabel("Day")
    axes[-1].legend(title="Well")
    fig.suptitle("Matched reporter-control vs primary mCherry longitudinal pilot")
    figure_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(figure_path, dpi=180)
    plt.close(fig)


if __name__ == "__main__":
    main()
