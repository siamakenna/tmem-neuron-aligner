#!/usr/bin/env python
"""Box plots of shift magnitude, overlap fraction, and correlation across all imaging days."""
from __future__ import annotations

import os
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

QC_CSV = Path("reports/260213_all_wells_all_days/all_wells_registration_qc.csv")
OUT = Path("reports/260213_all_wells_all_days/figures/alignment_accuracy_over_time.png")


def main() -> None:
    df = pd.read_csv(QC_CSV)
    df = df[df["qc_note"] != "reference_timepoint"].copy()
    df["shift_magnitude"] = np.sqrt(df["estimated_y_shift"] ** 2 + df["estimated_x_shift"] ** 2)

    days = sorted(df["timepoint_day"].unique())
    groups = {d: df[df["timepoint_day"] == d] for d in days}

    fig, axes = plt.subplots(3, 1, figsize=(10, 10), sharex=True)

    axes[0].boxplot([g["shift_magnitude"].values for g in groups.values()], tick_labels=days, showfliers=False)
    axes[0].set_ylabel("Shift magnitude (px)")
    axes[0].set_title("Stage correction applied (larger = more drift)")

    axes[1].boxplot([g["overlap_fraction"].values for g in groups.values()], tick_labels=days, showfliers=False)
    axes[1].set_ylabel("Overlap fraction")
    axes[1].set_ylim(0, 1.05)
    axes[1].set_title("Post-registration overlap fraction (lower = large shift)")

    axes[2].boxplot(
        [g["post_registration_correlation"].values for g in groups.values()], tick_labels=days, showfliers=False
    )
    axes[2].set_ylabel("Correlation (post-registration)")
    axes[2].set_xlabel("Day")
    axes[2].set_title("Channel correlation after registration")

    fig.suptitle("Alignment accuracy across all 192 wells over time", fontsize=12)
    fig.tight_layout()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT, dpi=150)
    print(f"Saved: {OUT}")


if __name__ == "__main__":
    main()
