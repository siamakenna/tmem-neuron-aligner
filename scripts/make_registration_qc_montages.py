#!/usr/bin/env python
from __future__ import annotations

import argparse
import os
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import tifffile as tif

from tmem_align.registration_qc import classify_registration_qc, correlation


DEFAULT_INTERIM_ROOT = Path("/Users/pmihack/claire/tmem_2026/data/TMEM106B_interim")
DEFAULT_PROCESSED_ROOT = Path("/Users/pmihack/claire/tmem_2026/data/TMEM106B_processed")
DEFAULT_WELLS = ["E05", "F05", "I05", "J05", "M05", "N05"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create visual QC montages for registered same-well longitudinal pilot stacks."
    )
    parser.add_argument("--interim-root", type=Path, default=DEFAULT_INTERIM_ROOT)
    parser.add_argument("--processed-root", type=Path, default=DEFAULT_PROCESSED_ROOT)
    parser.add_argument("--wells", nargs="+", default=DEFAULT_WELLS)
    parser.add_argument("--days-label", default="day8_day25_day39")
    parser.add_argument("--output-subdir", default="registration_qc")
    parser.add_argument("--alignment-channel", type=int, default=2)
    parser.add_argument("--mcherry-channel", type=int, default=1)
    parser.add_argument("--large-shift-threshold", type=float, default=500.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    out_dir = args.processed_root / "pilot" / args.output_subdir
    out_dir.mkdir(parents=True, exist_ok=True)

    summary_rows = []
    for well in args.wells:
        stack_path = (
            args.interim_root
            / "pilot"
            / f"{well.lower()}_longitudinal"
            / f"{well}_days_{args.days_label}_registered_tcyx.ome.tif"
        )
        overlap_path = (
            args.interim_root
            / "pilot"
            / f"{well.lower()}_longitudinal"
            / f"{well}_days_{args.days_label}_registered_common_overlap_tcyx.ome.tif"
        )
        shifts_path = (
            args.processed_root
            / "pilot"
            / f"{well.lower()}_longitudinal"
            / f"{well}_days_{args.days_label}_registration_shifts.csv"
        )
        if not stack_path.exists():
            raise FileNotFoundError(stack_path)
        if not overlap_path.exists():
            raise FileNotFoundError(overlap_path)
        if not shifts_path.exists():
            raise FileNotFoundError(shifts_path)

        stack = np.asarray(tif.imread(stack_path))
        overlap_stack = np.asarray(tif.imread(overlap_path))
        shifts = pd.read_csv(shifts_path)
        days = shifts["day"].tolist()

        alignment_png = out_dir / f"{well}_{args.days_label}_registered_alignment_ch{args.alignment_channel}_montage.png"
        mcherry_png = out_dir / f"{well}_{args.days_label}_registered_mcherry_ch{args.mcherry_channel}_montage.png"
        overlay_png = out_dir / f"{well}_{args.days_label}_alignment_day_overlay.png"
        overlap_png = out_dir / f"{well}_{args.days_label}_common_overlap_mcherry_ch{args.mcherry_channel}_montage.png"

        write_channel_montage(
            stack[:, args.alignment_channel],
            days,
            shifts,
            alignment_png,
            title=f"{well} registered alignment channel {args.alignment_channel}",
        )
        write_channel_montage(
            stack[:, args.mcherry_channel],
            days,
            shifts,
            mcherry_png,
            title=f"{well} registered mCherry channel {args.mcherry_channel}",
        )
        write_channel_montage(
            overlap_stack[:, args.mcherry_channel],
            days,
            shifts,
            overlap_png,
            title=f"{well} common-overlap mCherry channel {args.mcherry_channel}",
        )
        write_day_overlay(stack[:, args.alignment_channel], days, overlay_png, title=f"{well} alignment-channel day overlay")

        for row in shifts.to_dict("records"):
            day_index = days.index(int(row["day"]))
            dy = float(row["dy"])
            dx = float(row["dx"])
            summary_rows.append(
                {
                    "well": well,
                    "day": int(row["day"]),
                    "dy": dy,
                    "dx": dx,
                    "alignment_corr_to_day8_common_overlap": correlation(
                        overlap_stack[0, args.alignment_channel],
                        overlap_stack[day_index, args.alignment_channel],
                    ),
                    "mcherry_corr_to_day8_common_overlap": correlation(
                        overlap_stack[0, args.mcherry_channel],
                        overlap_stack[day_index, args.mcherry_channel],
                    ),
                    **classify_registration_qc(
                        overlap=1.0, dy=dy, dx=dx,
                        height=overlap_stack.shape[-2], width=overlap_stack.shape[-1],
                        large_shift_px=args.large_shift_threshold,
                    ),
                    "registered_alignment_montage": str(alignment_png),
                    "registered_mcherry_montage": str(mcherry_png),
                    "common_overlap_mcherry_montage": str(overlap_png),
                    "alignment_overlay": str(overlay_png),
                }
            )

    summary = pd.DataFrame(summary_rows)
    summary_path = out_dir / "registration_qc_shift_summary.csv"
    summary.to_csv(summary_path, index=False)
    print(f"Wrote QC summary: {summary_path}")
    print(summary.to_string(index=False))


def write_channel_montage(
    frames: np.ndarray,
    days: list[int],
    shifts: pd.DataFrame,
    output_path: Path,
    *,
    title: str,
) -> None:
    fig, axes = plt.subplots(1, frames.shape[0], figsize=(4 * frames.shape[0], 4), constrained_layout=True)
    if frames.shape[0] == 1:
        axes = [axes]
    vmin, vmax = robust_limits(frames)
    for index, ax in enumerate(axes):
        ax.imshow(frames[index], cmap="gray", vmin=vmin, vmax=vmax)
        dy = float(shifts.loc[index, "dy"])
        dx = float(shifts.loc[index, "dx"])
        ax.set_title(f"Day {days[index]}\ndy={dy:.1f}, dx={dx:.1f}")
        ax.axis("off")
    fig.suptitle(title)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=180)
    plt.close(fig)


def write_day_overlay(frames: np.ndarray, days: list[int], output_path: Path, *, title: str) -> None:
    if frames.shape[0] < 3:
        return
    red = normalize_frame(frames[0])
    green = normalize_frame(frames[1])
    blue = normalize_frame(frames[2])
    rgb = np.stack([red, green, blue], axis=-1)
    fig, ax = plt.subplots(figsize=(6, 6), constrained_layout=True)
    ax.imshow(rgb)
    ax.set_title(f"{title}\nRGB = Day {days[0]}, Day {days[1]}, Day {days[2]}")
    ax.axis("off")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=180)
    plt.close(fig)


def robust_limits(frames: np.ndarray) -> tuple[float, float]:
    vmin, vmax = np.percentile(frames, [0.5, 99.5])
    if vmax <= vmin:
        vmax = vmin + 1
    return float(vmin), float(vmax)


def normalize_frame(frame: np.ndarray) -> np.ndarray:
    vmin, vmax = robust_limits(frame)
    return np.clip((frame.astype(np.float32) - vmin) / (vmax - vmin), 0, 1)


if __name__ == "__main__":
    main()
