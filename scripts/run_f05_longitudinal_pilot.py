#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import tifffile as tif

from tmem_align.nd2_tools import inspect_nd2
from tmem_align.analysis.mcherry_metrics import quantify_mcherry_from_file
from tmem_align.register import apply_shift, register_translation
from tmem_align.stage_qc import (
    DEFAULT_STAGE_XY_THRESHOLD_UM,
    build_stage_prefilter_rows,
    read_nd2_stage_coordinates,
)


DEFAULT_RAW_ROOT = Path(
    "/Users/pmihack/claire/tmem_2026/data/"
    "260213_Feb16recopy_HYdiff_landingpadlines_survival_384well1"
)
DEFAULT_INTERIM_ROOT = Path("/Users/pmihack/claire/tmem_2026/data/TMEM106B_interim")
DEFAULT_PROCESSED_ROOT = Path("/Users/pmihack/claire/tmem_2026/data/TMEM106B_processed")
DEFAULT_DAYS = [8, 25, 39]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Create a tiny same-well longitudinal pilot stack from fluorescence ND2 files. "
            "The output preserves channels and uses a non-mCherry channel for registration."
        )
    )
    parser.add_argument("--raw-root", type=Path, default=DEFAULT_RAW_ROOT)
    parser.add_argument("--interim-root", type=Path, default=DEFAULT_INTERIM_ROOT)
    parser.add_argument("--processed-root", type=Path, default=DEFAULT_PROCESSED_ROOT)
    parser.add_argument("--well", default="F05")
    parser.add_argument("--days", type=int, nargs="+", default=DEFAULT_DAYS)
    parser.add_argument(
        "--alignment-channel", type=int, default=2, help="Default 2 = 488nm Binned."
    )
    parser.add_argument("--mcherry-channel", type=int, default=1, help="Default 1 = 561nm Binned.")
    parser.add_argument("--max-shift-pixels", type=float, default=1200.0)
    parser.add_argument(
        "--stage-xy-threshold-um", type=float, default=DEFAULT_STAGE_XY_THRESHOLD_UM
    )
    parser.add_argument(
        "--allow-stage-prefilter-fail",
        action="store_true",
        help="Continue even if the metadata-only stage-coordinate prefilter fails.",
    )
    parser.add_argument("--max-read-bytes", type=int, default=2 * 1024**3)
    parser.add_argument("--max-output-bytes", type=int, default=5 * 1024**3)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    paths = select_well_paths(args.raw_root, args.well, args.days)
    if not paths:
        raise FileNotFoundError(f"No fluorescence ND2 files found for well {args.well}")

    interim_dir = args.interim_root / "pilot" / f"{args.well.lower()}_longitudinal"
    processed_dir = args.processed_root / "pilot" / f"{args.well.lower()}_longitudinal"
    interim_dir.mkdir(parents=True, exist_ok=True)
    processed_dir.mkdir(parents=True, exist_ok=True)

    frames: list[np.ndarray] = []
    metadata: dict[str, Any] = {
        "analysis_scope": (
            "Preliminary same-well longitudinal fluorescence pilot. Files are one CYX frame per "
            "day in this subset, so this script aligns full frames rather than performing tile "
            "stitching. Not a final neuron ROI or validated lysosomal rupture analysis."
        ),
        "well": args.well,
        "requested_days": args.days,
        "alignment_channel_index": args.alignment_channel,
        "mcherry_channel_index": args.mcherry_channel,
        "stage_xy_threshold_um": args.stage_xy_threshold_um,
        "days": [],
    }

    stage_prefilter = build_stage_prefilter(paths, threshold_um=args.stage_xy_threshold_um)
    metadata["stage_prefilter"] = stage_prefilter
    failed_stage = [row for row in stage_prefilter if not row["stage_prefilter_pass"]]
    if failed_stage and not args.allow_stage_prefilter_fail:
        failed = ", ".join(
            f"day {row['day']} ({row['stage_prefilter_reason']}, "
            f"xy={row['stage_distance_xy_um']:.2f} um)"
            for row in failed_stage
        )
        raise ValueError(
            f"Stage-coordinate prefilter failed for {args.well}: {failed}. "
            "Use --allow-stage-prefilter-fail only after visual review."
        )

    for day, nd2_path in paths:
        info = inspect_nd2(nd2_path)
        if info["axis_order"] != "CYX":
            raise ValueError(f"Expected CYX for pilot file {nd2_path}, got {info['axis_order']}")
        arr = read_cyx_nd2(nd2_path, args.max_read_bytes)
        frames.append(arr)
        metadata["days"].append(
            {
                "day": day,
                "nd2_path": str(nd2_path),
                "nd2_size_bytes": nd2_path.stat().st_size,
                "axis_order": info["axis_order"],
                "sizes": info["sizes"],
                "channels": info["channel_names"],
                "array_shape": list(arr.shape),
                "array_dtype": str(arr.dtype),
                "voxel_size": info["voxel_size"],
                "stage_prefilter": next(
                    row for row in stage_prefilter if int(row["day"]) == int(day)
                ),
            }
        )

    stack = np.stack(frames, axis=0)  # TCYX
    check_output_size(stack, args.max_output_bytes)
    raw_stack_path = interim_dir / f"{args.well}_days_{day_label(paths)}_raw_tcyx.ome.tif"
    write_tcyx(raw_stack_path, stack)

    registered_stack, shifts = register_tcyx_stack(
        stack,
        alignment_channel=args.alignment_channel,
        max_shift_pixels=args.max_shift_pixels,
    )
    registered_stack_path = (
        interim_dir / f"{args.well}_days_{day_label(paths)}_registered_tcyx.ome.tif"
    )
    write_tcyx(registered_stack_path, registered_stack)

    common_stack, common_crop = crop_common_overlap(registered_stack, shifts)
    common_stack_path = (
        interim_dir / f"{args.well}_days_{day_label(paths)}_registered_common_overlap_tcyx.ome.tif"
    )
    write_tcyx(common_stack_path, common_stack)

    metrics_path = processed_dir / f"{args.well}_days_{day_label(paths)}_mcherry_metrics.csv"
    metrics = quantify_registered_mcherry(common_stack, paths, args.mcherry_channel, metrics_path)

    shifts_path = processed_dir / f"{args.well}_days_{day_label(paths)}_registration_shifts.csv"
    pd.DataFrame(
        [{"day": day, "dy": dy, "dx": dx} for (day, _), (dy, dx) in zip(paths, shifts, strict=True)]
    ).to_csv(shifts_path, index=False)

    metadata["outputs"] = {
        "raw_stack": str(raw_stack_path),
        "raw_stack_size_bytes": raw_stack_path.stat().st_size,
        "registered_stack": str(registered_stack_path),
        "registered_stack_size_bytes": registered_stack_path.stat().st_size,
        "registered_common_overlap_stack": str(common_stack_path),
        "registered_common_overlap_stack_size_bytes": common_stack_path.stat().st_size,
        "common_overlap_crop_yx": common_crop,
        "metrics_csv": str(metrics_path),
        "registration_shifts_csv": str(shifts_path),
    }
    metadata_path = processed_dir / f"{args.well}_days_{day_label(paths)}_metadata.json"
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    figure_path = processed_dir / f"{args.well}_days_{day_label(paths)}_mcherry_summary.png"
    write_summary_figure(metrics, figure_path, args.well)

    print(f"Wrote raw stack: {raw_stack_path}")
    print(f"Wrote registered stack: {registered_stack_path}")
    print(f"Wrote common-overlap stack: {common_stack_path}")
    print(f"Wrote metrics: {metrics_path}")
    print(f"Wrote shifts: {shifts_path}")
    print(f"Wrote metadata: {metadata_path}")
    print(f"Wrote figure: {figure_path}")
    print(metrics.to_string(index=False))


def select_well_paths(
    raw_root: Path, well: str, requested_days: list[int]
) -> list[tuple[int, Path]]:
    candidates: dict[int, Path] = {}
    pattern = re.compile(r"day\s*(\d+)", re.IGNORECASE)
    for path in sorted(raw_root.rglob(f"*Well{well}*.nd2")):
        if "brightfield" in path.name.lower():
            continue
        match = pattern.search(path.name)
        if not match:
            continue
        day = int(match.group(1))
        if day in requested_days:
            candidates[day] = path
    return [(day, candidates[day]) for day in requested_days if day in candidates]


def build_stage_prefilter(
    paths: list[tuple[int, Path]],
    *,
    threshold_um: float,
) -> list[dict[str, Any]]:
    observations = []
    for day, path in paths:
        observations.append(
            {
                "day": int(day),
                "well": infer_well(path),
                "nd2_path": str(path),
                **read_nd2_stage_coordinates(path),
            }
        )
    return build_stage_prefilter_rows(
        observations,
        reference_day=int(paths[0][0]),
        threshold_um=threshold_um,
    )


def infer_well(path: Path) -> str:
    match = re.search(r"Well([A-P]\d{2})", path.name, re.IGNORECASE)
    if not match:
        raise ValueError(f"Could not infer well from {path.name}")
    return match.group(1).upper()


def read_cyx_nd2(path: Path, max_read_bytes: int) -> np.ndarray:
    import nd2  # type: ignore

    with nd2.ND2File(path) as image:
        data = image.to_dask()
        estimated_read_bytes = (
            int(np.prod(data.shape, dtype=np.int64)) * np.dtype(data.dtype).itemsize
        )
        if estimated_read_bytes > max_read_bytes:
            raise ValueError(
                f"Requested file read is estimated at {estimated_read_bytes:,} bytes, "
                f"which exceeds max_read_bytes={max_read_bytes:,}."
            )
        return np.asarray(data.compute())


def check_output_size(arr: np.ndarray, max_output_bytes: int) -> None:
    if arr.nbytes > max_output_bytes:
        raise ValueError(
            f"Output stack is {arr.nbytes:,} bytes before TIFF overhead, "
            f"which exceeds max_output_bytes={max_output_bytes:,}."
        )


def register_tcyx_stack(
    stack: np.ndarray,
    *,
    alignment_channel: int,
    max_shift_pixels: float,
) -> tuple[np.ndarray, list[tuple[float, float]]]:
    reference = stack[0, alignment_channel]
    registered = [stack[0]]
    shifts = [(0.0, 0.0)]
    for time_index in range(1, stack.shape[0]):
        # raw stable channel + masked phase correlation (no clip+blur — see docs)
        _, (dy, dx), _ = register_translation(
            reference,
            stack[time_index, alignment_channel],
            max_shift_pixels=max_shift_pixels,
            robust_preprocess=False,
            mask_percentile=20.0,
        )
        registered.append(apply_shift(stack[time_index], dy, dx))
        shifts.append((dy, dx))
    return np.stack(registered, axis=0), shifts


def crop_common_overlap(
    stack: np.ndarray,
    shifts: list[tuple[float, float]],
) -> tuple[np.ndarray, dict[str, int]]:
    height, width = stack.shape[-2:]
    top = max(int(np.ceil(max(dy, 0))) for dy, _ in shifts)
    bottom = min(height + int(np.floor(min(dy, 0))) for dy, _ in shifts)
    left = max(int(np.ceil(max(dx, 0))) for _, dx in shifts)
    right = min(width + int(np.floor(min(dx, 0))) for _, dx in shifts)
    if top >= bottom or left >= right:
        raise ValueError(f"No common overlap remains after shifts: {shifts}")
    crop = {"y_start": top, "y_stop": bottom, "x_start": left, "x_stop": right}
    return stack[:, :, top:bottom, left:right], crop


def quantify_registered_mcherry(
    registered_stack: np.ndarray,
    paths: list[tuple[int, Path]],
    mcherry_channel: int,
    output_csv: Path,
) -> pd.DataFrame:
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    temp_path = output_csv.with_suffix(".mcherry_tmp.ome.tif")
    tif.imwrite(
        temp_path,
        registered_stack[:, mcherry_channel],
        photometric="minisblack",
        metadata={"axes": "TYX"},
        ome=True,
    )
    try:
        metrics = quantify_mcherry_from_file(temp_path)
    finally:
        temp_path.unlink(missing_ok=True)
    metrics.insert(0, "day", [day for day, _ in paths])
    metrics.insert(1, "file_name", [path.name for _, path in paths])
    metrics.insert(2, "channel_index", mcherry_channel)
    metrics.to_csv(output_csv, index=False)
    return metrics


def write_tcyx(path: Path, stack: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tif.imwrite(path, stack, photometric="minisblack", metadata={"axes": "TCYX"}, ome=True)


def write_summary_figure(metrics: pd.DataFrame, figure_path: Path, well: str) -> None:
    fig, axes = plt.subplots(1, 3, figsize=(11, 3.5), constrained_layout=True)
    x = metrics["day"].astype(str)
    for ax, column, title in zip(
        axes,
        ["puncta_count", "diffuse_mean", "rupture_like_score"],
        ["Puncta count", "Diffuse mean", "Diffuse / punctate mean"],
        strict=True,
    ):
        ax.plot(x, metrics[column], marker="o", linewidth=2)
        ax.set_title(title)
        ax.set_xlabel("Day")
    fig.suptitle(f"{well} preliminary registered mCherry time series")
    figure_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(figure_path, dpi=180)
    plt.close(fig)


def day_label(paths: list[tuple[int, Path]]) -> str:
    return "_".join(f"day{day}" for day, _ in paths)


if __name__ == "__main__":
    main()
