#!/usr/bin/env python
"""Diagnose per-well registration drift from a registration_qc.csv.

Answers two questions from the already-saved registration shift vectors (no recompute):
  1. Per well: steady high drift, one bad day, or clean? (classification + trajectory plot)
  2. Is the drift common-mode across wells (a plate-wide stage event, shareable) or
     per-well/random (not shareable)? — the test for "estimate drift from other wells
     and apply it everywhere".

Reads the columns written by the registration pipeline: well, timepoint_day,
estimated_y_shift, estimated_x_shift, overlap_fraction.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

DEFAULT_QC = Path("reports/260213_all_wells_all_days/all_wells_registration_qc.csv")


def load_shifts(qc_csv: Path) -> pd.DataFrame:
    df = pd.read_csv(qc_csv)
    required = {"well", "timepoint_day", "estimated_y_shift", "estimated_x_shift"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"{qc_csv} is missing columns: {sorted(missing)}")
    df = df.copy()
    df["shift_mag"] = np.hypot(df["estimated_y_shift"], df["estimated_x_shift"])
    if "overlap_fraction" not in df.columns:
        df["overlap_fraction"] = np.nan
    return df


def well_summary(df: pd.DataFrame, large_thresh: float) -> pd.DataFrame:
    """Per-well drift summary + a one-bad-day vs high-drift classification."""
    rows = []
    for well, g in df.groupby("well"):
        mags = g["shift_mag"].to_numpy()
        n_large = int((mags > large_thresh).sum())
        if n_large == 0:
            cls = "clean"
        elif n_large == 1:
            cls = "one_bad_day"
        else:
            cls = "high_drift_or_erratic"
        rows.append(
            {
                "well": well,
                "n_days": len(g),
                "n_large_shifts": n_large,
                "max_shift_px": float(mags.max()),
                "median_shift_px": float(np.median(mags)),
                "min_overlap_fraction": float(g["overlap_fraction"].min()),
                "classification": cls,
            }
        )
    return (
        pd.DataFrame(rows)
        .sort_values(["n_large_shifts", "max_shift_px"], ascending=False)
        .reset_index(drop=True)
    )


def common_mode_by_day(df: pd.DataFrame) -> pd.DataFrame:
    """Per day, is the shift shared across wells (common-mode) or random (cancels)?

    coherence = |median shift vector| / median(|per-well shift vectors|).
    ~1 => wells drift together (shareable). ~0 => random per-well (not shareable).
    """
    rows = []
    for day, g in df.groupby("timepoint_day"):
        dy = g["estimated_y_shift"].to_numpy()
        dx = g["estimated_x_shift"].to_numpy()
        med_vec = np.hypot(np.median(dy), np.median(dx))
        med_mag = float(np.median(np.hypot(dy, dx)))
        coherence = med_vec / med_mag if med_mag > 1e-9 else 0.0
        rows.append(
            {
                "timepoint_day": day,
                "n_wells": len(g),
                "median_dy": float(np.median(dy)),
                "median_dx": float(np.median(dx)),
                "median_shift_mag_px": med_mag,
                "coherence": float(coherence),
            }
        )
    return pd.DataFrame(rows).sort_values("timepoint_day").reset_index(drop=True)


def plot_trajectories(df, wells, out_path) -> None:
    fig, (ax_m, ax_c) = plt.subplots(1, 2, figsize=(13, 5))
    for well in wells:
        g = df[df["well"] == well].sort_values("timepoint_day")
        if g.empty:
            continue
        days = g["timepoint_day"].to_numpy()
        ax_m.plot(days, g["shift_mag"], marker="o", label=well)
        ax_c.plot(days, g["estimated_y_shift"], marker="o", label=f"{well} dy")
        ax_c.plot(days, g["estimated_x_shift"], marker="s", ls="--", label=f"{well} dx")
    ax_m.set(xlabel="Imaging day", ylabel="Shift magnitude (px)", title="Shift magnitude vs day")
    ax_m.grid(alpha=0.3)
    ax_m.legend(fontsize=8)
    ax_c.axhline(0, color="k", lw=0.5)
    ax_c.set(
        xlabel="Imaging day",
        ylabel="Signed shift (px)",
        title="Y / X components (axis-locked = suspicious)",
    )
    ax_c.grid(alpha=0.3)
    ax_c.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def plot_heatmap(df, value, title, out_path, cmap) -> None:
    pivot = df.pivot_table(index="well", columns="timepoint_day", values=value)
    fig, ax = plt.subplots(figsize=(10, max(6, len(pivot) * 0.06)))
    im = ax.imshow(pivot.to_numpy(), aspect="auto", cmap=cmap, interpolation="nearest")
    ax.set_xticks(range(len(pivot.columns)))
    ax.set_xticklabels(pivot.columns)
    ax.set_yticks([])  # 192 wells — ticks unreadable; row order is alphabetical
    ax.set(xlabel="Imaging day", ylabel=f"wells (n={len(pivot)}, alphabetical)", title=title)
    fig.colorbar(im, ax=ax, label=value)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--qc-csv", type=Path, default=DEFAULT_QC)
    p.add_argument("--output-dir", type=Path, default=Path("outputs/plots/registration_drift"))
    p.add_argument("--highlight", nargs="+", default=["E05", "F05"])
    p.add_argument(
        "--large-shift-thresh",
        type=float,
        default=100.0,
        help="shift magnitude (px) above which a day counts as a large shift",
    )
    return p.parse_args(argv), p


def main(argv=None) -> None:
    args, parser = parse_args(argv)
    if not args.qc_csv.exists():
        parser.error(f"QC csv not found: {args.qc_csv}")

    df = load_shifts(args.qc_csv)
    summary = well_summary(df, args.large_shift_thresh)
    common = common_mode_by_day(df)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = args.output_dir / "well_drift_summary.csv"
    common_path = args.output_dir / "common_mode_by_day.csv"
    summary.to_csv(summary_path, index=False)
    common.to_csv(common_path, index=False)

    plot_trajectories(df, args.highlight, args.output_dir / "highlight_trajectories.png")
    plot_heatmap(
        df,
        "shift_mag",
        "Registration shift magnitude (px)",
        args.output_dir / "shift_magnitude_heatmap.png",
        "magma",
    )
    plot_heatmap(
        df,
        "overlap_fraction",
        "Overlap fraction (drives common-overlap crop)",
        args.output_dir / "overlap_fraction_heatmap.png",
        "viridis",
    )

    # --- printed findings ---
    print(f"Wells: {df['well'].nunique()}  Days: {sorted(df['timepoint_day'].unique())}\n")
    print("Worst-offender wells:")
    print(summary.head(8).to_string(index=False))
    for well in args.highlight:
        row = summary[summary["well"] == well]
        if not row.empty:
            r = row.iloc[0]
            print(
                f"\n{well}: {r['classification']} — {r['n_large_shifts']} large-shift day(s), "
                f"max {r['max_shift_px']:.0f}px, min overlap {r['min_overlap_fraction']:.2f}"
            )
    print(
        "\nCommon-mode by day (coherence ~1 = wells drift together/shareable, "
        "~0 = random per-well):"
    )
    print(common.to_string(index=False))

    for path in (
        summary_path,
        common_path,
        args.output_dir / "highlight_trajectories.png",
        args.output_dir / "shift_magnitude_heatmap.png",
        args.output_dir / "overlap_fraction_heatmap.png",
    ):
        print(f"Saved: {path}")


if __name__ == "__main__":
    main()
