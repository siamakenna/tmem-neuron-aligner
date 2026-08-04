#!/usr/bin/env python
from __future__ import annotations

import argparse
import os
import re
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")

import matplotlib.pyplot as plt
import imageio.v2 as imageio
import numpy as np
import pandas as pd
import tifffile as tif
from tmem_align.analysis.mcherry_metrics import quantify_mcherry_timeseries
from tmem_align.io import find_images
from tmem_align.preprocess import apply_ic_field, calculate_ic_field
from tmem_align.register import apply_shift, register_translation
from tmem_align.registration_qc import (
    classify_registration_qc,
    common_overlap_crop,
    correlation,
    crop_tcyx,
    overlap_fraction,
    robust_registration_image,
)


CONDITIONS = {
    "E": "PLD3_mCherry_reporter_control",
    "F": "PLD3_TMEM106B_mCherry_primary",
    "I": "PLD3_mCherry_reporter_control",
    "J": "PLD3_TMEM106B_mCherry_primary",
    "M": "PLD3_mCherry_reporter_control",
    "N": "PLD3_TMEM106B_mCherry_primary",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a tiny E/F mCherry longitudinal registration and measurement pilot."
    )
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=Path("configs/260213_Feb15recopy.yaml"))
    parser.add_argument("--control-well", default="E05")
    parser.add_argument("--experimental-well", default="F05")
    parser.add_argument("--channels", nargs="+", default=["488", "561"])
    parser.add_argument("--max-timepoints", type=int, default=3)
    parser.add_argument("--max-sites", type=int, default=1)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--max-read-bytes", type=int, default=2 * 1024**3)
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Parallel workers for per-well processing (default 1 = sequential).",
    )
    parser.add_argument(
        "--exclude-days",
        nargs="+",
        type=int,
        default=[],
        metavar="DAY",
        help="Drop specific imaging days before registration (e.g. --exclude-days 25 for F05).",
    )
    parser.add_argument(
        "--robust-crop",
        action="store_true",
        default=True,
        help="Use robust common-overlap crop (clips shift outliers at 90th percentile). On by default.",
    )
    parser.add_argument(
        "--no-robust-crop",
        dest="robust_crop",
        action="store_false",
        help="Disable robust crop — use strict intersection of all shifts (old behaviour).",
    )
    parser.add_argument(
        "--ref-mode",
        choices=["to_first", "anchored"],
        default="to_first",
        help="Temporal registration mode: 'to_first' (register every day to day 0, default) or "
        "'anchored' (re-anchor to the last good frame when correlation drops).",
    )
    parser.add_argument(
        "--anchor-corr-thresh",
        type=float,
        default=0.10,
        help="Anchored mode: re-anchor when post-corr to the current anchor drops below this "
        "(calibrated on 260213 real data). Ignored for --ref-mode to_first.",
    )
    parser.add_argument(
        "--min-post-correlation",
        type=float,
        default=0.07,
        help="QC gate: a timepoint fails when its post-registration correlation is below this.",
    )
    parser.add_argument(
        "--illumination-correct",
        action="store_true",
        help="Apply per-timepoint illumination correction (flatfield) to each frame before "
        "registration and quantification. Off by default so the baseline reproduction is unchanged.",
    )
    parser.add_argument(
        "--ic-sample-fraction",
        type=float,
        default=0.25,
        help="Fraction of each timepoint's images sampled (seeded) to build the IC field.",
    )
    return parser.parse_args()


def _process_one_well_pilot(args_tuple: tuple) -> dict[str, Any]:
    (
        well,
        rows,
        channels,
        max_sites,
        max_read_bytes,
        robust_crop,
        ref_mode,
        anchor_corr_thresh,
        min_post_correlation,
        ic_fields,
    ) = args_tuple
    loaded = [load_nd2_cyx(row["path"], max_sites, max_read_bytes) for row in rows]
    if ic_fields:
        # Flatfield-correct each day's frame by its timepoint's IC field (keyed by parent dir).
        for item, row in zip(loaded, rows, strict=True):
            item["array"] = apply_ic_field(item["array"], ic_fields[row["path"].parent.name])
    channel_names = loaded[0]["channel_names"]
    alignment_index = choose_channel_index(channel_names, channels[0])
    mcherry_index = choose_channel_index(channel_names, channels[1])
    raw_stack = np.stack([item["array"] for item in loaded], axis=0)
    registered, qc_rows, common_crop = register_stack(
        raw_stack,
        well=well,
        rows=rows,
        alignment_channel_index=alignment_index,
        alignment_channel_label=channel_names[alignment_index],
        robust_crop=robust_crop,
        ref_mode=ref_mode,
        anchor_corr_thresh=anchor_corr_thresh,
        min_post_correlation=min_post_correlation,
    )
    common = crop_tcyx(registered, common_crop)
    metadata_rows = [
        {
            "well": well,
            "condition": condition_for_well(well),
            "site_fov": "site0",
            "timepoint_day": row["day"],
            "file_name": row["path"].name,
            "mcherry_channel": channel_names[mcherry_index],
            "registration_channel": channel_names[alignment_index],
            "illumination_corrected": bool(ic_fields),
        }
        for row in rows
    ]
    metrics = quantify_mcherry_timeseries(
        common[:, mcherry_index],
        mask_stack=common[:, alignment_index],
        metadata_rows=metadata_rows,
    )
    return {"well": well, "common": common, "crop": common_crop, "qc": qc_rows, "metrics": metrics}


def main() -> None:
    args = parse_args()
    output = args.output.expanduser().resolve()
    figures = output / "figures"
    registered_dir = output / "registered_stacks"
    figures.mkdir(parents=True, exist_ok=True)
    registered_dir.mkdir(parents=True, exist_ok=True)

    started = datetime.now().isoformat(timespec="seconds")
    data_root = args.data_root.expanduser().resolve()
    wells = [args.control_well.upper(), args.experimental_well.upper()]
    selected = select_pilot_files(
        data_root,
        wells,
        max_timepoints=args.max_timepoints,
        exclude_days=set(args.exclude_days),
    )
    if not selected:
        raise FileNotFoundError(f"No pilot files found under {data_root} for {wells}")

    inventory = build_selected_inventory(selected)
    inventory_path = output / (
        "selected_pilot_files.csv"
        if (output / "dataset_inventory.csv").exists()
        else "dataset_inventory.csv"
    )
    inventory.to_csv(inventory_path, index=False)

    if args.dry_run:
        write_run_log(output, args, selected, started, extra=["Dry run: no pixels loaded."])
        print(inventory.to_string(index=False))
        print(f"Dry run wrote inventory: {inventory_path}")
        return

    all_qc: list[dict[str, Any]] = []
    all_metrics: list[pd.DataFrame] = []
    stacks: dict[str, np.ndarray] = {}
    crops: dict[str, dict[str, int]] = {}

    ic_fields: dict[str, np.ndarray] = {}
    if args.illumination_correct:
        tp_dirs = sorted(
            {row["path"].parent for rows in selected.values() for row in rows},
            key=lambda p: p.name,
        )
        for d in tp_dirs:
            imgs = find_images(d)
            ic_fields[d.name] = calculate_ic_field(
                imgs, sample_fraction=args.ic_sample_fraction, seed=0
            )
            print(f"IC field for {d.name}: {len(imgs)} images -> shape {ic_fields[d.name].shape}")

    well_args = [
        (
            well,
            selected[well],
            args.channels,
            args.max_sites,
            args.max_read_bytes,
            args.robust_crop,
            args.ref_mode,
            args.anchor_corr_thresh,
            args.min_post_correlation,
            ic_fields,
        )
        for well in wells
    ]

    if args.workers > 1 and len(wells) > 1:
        with ProcessPoolExecutor(max_workers=min(args.workers, len(wells))) as pool:
            results = list(pool.map(_process_one_well_pilot, well_args))
    else:
        results = [_process_one_well_pilot(wa) for wa in well_args]

    for result in results:
        well = result["well"]
        stacks[well] = result["common"]
        crops[well] = result["crop"]
        all_qc.extend(result["qc"])
        all_metrics.append(result["metrics"])
        tif.imwrite(
            registered_dir / f"{well}_registered_common_overlap_tcyx.ome.tif",
            result["common"],
            photometric="minisblack",
            metadata={"axes": "TCYX"},
            ome=True,
        )

    qc = pd.DataFrame(all_qc)
    qc_path = output / "registration_qc.csv"
    qc.to_csv(qc_path, index=False)

    measurements = pd.concat(all_metrics, ignore_index=True)
    measurements_path = output / "mcherry_measurements.csv"
    measurements.to_csv(measurements_path, index=False)

    summary = build_summary_stats(measurements, qc)
    summary_path = output / "summary_stats.csv"
    summary.to_csv(summary_path, index=False)

    write_registration_figure(stacks, selected, figures / "registration_before_after.png")
    write_mcherry_timeseries_figure(stacks, selected, figures / "aligned_timeseries_mcherry.png")
    write_mcherry_timeseries_gifs(stacks, figures)
    write_metric_figure(measurements, figures / "mcherry_metric_over_time.png")
    write_pi_readme(
        output, data_root, args, inventory, qc, measurements, summary, selected, started
    )
    write_methods(output, args, selected)
    write_run_log(
        output,
        args,
        selected,
        started,
        extra=[f"Completed at {datetime.now().isoformat(timespec='seconds')}"],
    )

    print_terminal_summary(output, data_root, selected, qc, measurements)


def select_pilot_files(
    data_root: Path,
    wells: list[str],
    *,
    max_timepoints: int,
    exclude_days: set[int] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    _exclude = exclude_days or set()
    selected: dict[str, list[dict[str, Any]]] = {}
    for well in wells:
        candidates = []
        for path in sorted(data_root.rglob(f"*Well{well}*.nd2")):
            if "brightfield" in path.name.lower():
                continue
            day = infer_day(path.name)
            if day is None or day in _exclude:
                continue
            candidates.append({"well": well, "day": day, "path": path})
        candidates.sort(key=lambda row: (row["day"], str(row["path"])))
        selected[well] = candidates[:max_timepoints]
    return selected


def build_selected_inventory(selected: dict[str, list[dict[str, Any]]]) -> pd.DataFrame:
    rows = []
    for well, items in selected.items():
        for item in items:
            path = item["path"]
            rows.append(
                {
                    "path": str(path),
                    "filename": path.name,
                    "extension": ".nd2",
                    "file_size_bytes": path.stat().st_size,
                    "modified_time": datetime.fromtimestamp(path.stat().st_mtime).isoformat(
                        timespec="seconds"
                    ),
                    "inferred_well": well,
                    "inferred_day_timepoint": item["day"],
                    "inferred_channel": infer_channel_string(path.name),
                    "inferred_site_fov_tile": infer_sequence(path.name),
                    "parse_confidence": "high",
                }
            )
    return pd.DataFrame(rows)


def load_nd2_cyx(path: Path, max_sites: int, max_read_bytes: int) -> dict[str, Any]:
    import nd2  # type: ignore

    with nd2.ND2File(path) as image:
        data = image.to_dask()
        axis_order = list(image.sizes.keys())
        selection: list[Any] = []
        remaining_axes: list[str] = []
        for axis in axis_order:
            if axis == "P" and max_sites == 1:
                selection.append(0)
            elif axis == "T":
                selection.append(0)
            else:
                selection.append(slice(None))
                remaining_axes.append(axis)
        selected = data[tuple(selection)]
        read_bytes = (
            int(np.prod(selected.shape, dtype=np.int64)) * np.dtype(selected.dtype).itemsize
        )
        if read_bytes > max_read_bytes:
            raise ValueError(
                f"{path} selected read is {read_bytes:,} bytes, above {max_read_bytes:,}"
            )
        arr = np.asarray(selected.compute())

        channels = []
        try:
            for index, channel in enumerate(image.metadata.channels):
                name = getattr(getattr(channel, "channel", channel), "name", None)
                channels.append(str(name) if name else f"Channel{index}")
        except Exception:
            channels = infer_channel_string(path.name).split("|")

    arr, axes = standardize_to_cyx(arr, "".join(remaining_axes))
    if not channels or len(channels) != arr.shape[0]:
        channels = infer_channel_string(path.name).split("|")
    return {"array": arr, "axes": axes, "channel_names": channels}


def standardize_to_cyx(arr: np.ndarray, axes: str) -> tuple[np.ndarray, str]:
    image = np.squeeze(arr)
    axes_list = [axis for axis, size in zip(axes, np.asarray(arr).shape, strict=False) if size != 1]
    axes = "".join(axes_list)
    if image.ndim == 2:
        return image[np.newaxis, :, :], "CYX"
    if axes == "CYX":
        return image, "CYX"
    if set("YX").issubset(axes):
        if "Z" in axes:
            z_axis = axes.index("Z")
            image = image.max(axis=z_axis)
            axes = axes.replace("Z", "")
        if "C" not in axes:
            image = image[np.newaxis, :, :]
            axes = "CYX"
        order = [axes.index(axis) for axis in "CYX"]
        return np.transpose(image, order), "CYX"
    raise ValueError(f"Cannot standardize shape {arr.shape} with axes {axes} to CYX")


def _plate_offset(plate_offsets: dict | None, day: Any) -> tuple[float, float]:
    """Plate-remount prior (dy, dx) for a timepoint, or (0, 0) when absent (default = off)."""
    if not plate_offsets:
        return (0.0, 0.0)
    dy, dx = plate_offsets.get(day, (0.0, 0.0))
    return (float(dy), float(dx))


def _anchored_shifts(
    stable_frames: np.ndarray,
    thresh: float,
    plate_shifts: list[tuple[float, float]] | None = None,
) -> tuple[list[tuple[float, float]], list[float], list[bool]]:
    """Per-timepoint net (dy, dx)-to-t0, post-corr, and reanchored flag. Single source of the
    anchor math; mirrors scripts/plot_day_shift_overlay.register_anchored on the masked engine:
    register to the current anchor; if post-corr < thresh and t>=2 re-anchor to the LAST GOOD
    frame (never the current one) and re-register; compose net = anchor_net + pairwise; only
    frames with post >= thresh become eligible future anchors. No image application.

    ``plate_shifts`` (default None = byte-identical): per-timepoint plate-remount prior (dy, dx).
    When given, each frame is pre-shifted by its prior so registration sees only the residual
    drift, and the prior is added back into the returned net (plate-first, then per-well residual)."""
    if plate_shifts is not None:
        stable_frames = [
            frame if (pdy == 0.0 and pdx == 0.0) else apply_shift(frame, pdy, pdx)
            for frame, (pdy, pdx) in zip(stable_frames, plate_shifts, strict=True)
        ]
    anchor, anchor_net = stable_frames[0], (0.0, 0.0)
    last_good_img, last_good_net = stable_frames[0], (0.0, 0.0)
    shifts: list[tuple[float, float]] = [(0.0, 0.0)]
    post: list[float] = [1.0]
    reanchored: list[bool] = [False]
    for time_index in range(1, len(stable_frames)):
        moving = stable_frames[time_index]
        aligned, (pdy, pdx), _ = register_translation(
            anchor, moving, robust_preprocess=False, mask_percentile=20.0
        )
        p = correlation(anchor, aligned)
        did = False
        if p < thresh and time_index >= 2:
            anchor, anchor_net = last_good_img, last_good_net
            aligned, (pdy, pdx), _ = register_translation(
                anchor, moving, robust_preprocess=False, mask_percentile=20.0
            )
            p = correlation(anchor, aligned)
            did = True
        net = (anchor_net[0] + pdy, anchor_net[1] + pdx)
        shifts.append(net)
        post.append(p)
        reanchored.append(did)
        if p >= thresh:  # trustworthy → eligible future anchor
            last_good_img, last_good_net = moving, net
    if plate_shifts is not None:  # net = plate prior + residual (total, for apply_shift + crop)
        shifts = [
            (net[0] + pdy, net[1] + pdx)
            for net, (pdy, pdx) in zip(shifts, plate_shifts, strict=True)
        ]
    return shifts, post, reanchored


def register_stack(
    stack: np.ndarray,
    *,
    well: str,
    rows: list[dict[str, Any]],
    alignment_channel_index: int,
    alignment_channel_label: str,
    robust_crop: bool = True,
    ref_mode: str = "to_first",
    anchor_corr_thresh: float = 0.10,
    min_post_correlation: float = 0.07,
    plate_offsets: dict | None = None,
) -> tuple[np.ndarray, list[dict[str, Any]], dict[str, int]]:
    # Register on the RAW stable channel with masked phase correlation (ignore background
    # below p20). Do NOT clip+blur here: it smears the sparse neuron signal and makes the
    # peak lock onto image edges, producing axis-locked 500-1400 px garbage shifts (see docs).
    reference = stack[0, alignment_channel_index]

    # Plate-remount prior per timepoint (default None → all-zero → byte-identical to no correction).
    # Composed plate-first: the moving frame is pre-shifted by its prior so registration measures
    # only the per-well residual; net = prior + residual feeds both apply_shift and the crop.
    plate_shifts = (
        [_plate_offset(plate_offsets, row["day"]) for row in rows] if plate_offsets else None
    )

    if ref_mode == "anchored":
        return _register_stack_anchored(
            stack,
            reference=reference,
            well=well,
            rows=rows,
            alignment_channel_index=alignment_channel_index,
            alignment_channel_label=alignment_channel_label,
            robust_crop=robust_crop,
            anchor_corr_thresh=anchor_corr_thresh,
            min_post_correlation=min_post_correlation,
            plate_shifts=plate_shifts,
        )

    registered = [stack[0]]
    shifts = [(0.0, 0.0)]
    qc_rows = [
        {
            "well": well,
            "condition": condition_for_well(well),
            "timepoint_day": rows[0]["day"],
            "registration_channel": alignment_channel_label,
            "estimated_y_shift": 0.0,
            "estimated_x_shift": 0.0,
            "pre_registration_correlation": 1.0,
            "post_registration_correlation": 1.0,
            "overlap_fraction": 1.0,
            "registration_error": 0.0,
            "qc_pass": True,
            "qc_note": "reference_timepoint",
        }
    ]

    for time_index in range(1, stack.shape[0]):
        moving = stack[time_index, alignment_channel_index]
        pdy, pdx = plate_shifts[time_index] if plate_shifts else (0.0, 0.0)
        reg_moving = moving if (pdy == 0.0 and pdx == 0.0) else apply_shift(moving, pdy, pdx)
        _, (rdy, rdx), error = register_translation(
            reference,
            reg_moving,
            robust_preprocess=False,
            mask_percentile=20.0,
        )
        dy, dx = pdy + rdy, pdx + rdx  # net = plate prior + per-well residual
        shifted_channel = apply_shift(moving, dy, dx)
        registered.append(apply_shift(stack[time_index], dy, dx))
        shifts.append((dy, dx))
        overlap = overlap_fraction(stack.shape[-2:], (dy, dx))
        post_corr = correlation(reference, shifted_channel)
        qc_rows.append(
            {
                "well": well,
                "condition": condition_for_well(well),
                "timepoint_day": rows[time_index]["day"],
                "registration_channel": alignment_channel_label,
                "estimated_y_shift": dy,
                "estimated_x_shift": dx,
                "pre_registration_correlation": correlation(reference, moving),
                "post_registration_correlation": post_corr,
                "overlap_fraction": overlap,
                "registration_error": float(error),
                **classify_registration_qc(
                    overlap,
                    dy,
                    dx,
                    stack.shape[-2],
                    stack.shape[-1],
                    post_correlation=post_corr,
                ),
                "qc_note": "masked_phase_cross_correlation_on_raw_stable_channel",
            }
        )

    registered_stack = np.stack(registered, axis=0)
    return (
        registered_stack,
        qc_rows,
        common_overlap_crop(stack.shape[-2:], shifts, robust=robust_crop),
    )


def _register_stack_anchored(
    stack: np.ndarray,
    *,
    reference: np.ndarray,
    well: str,
    rows: list[dict[str, Any]],
    alignment_channel_index: int,
    alignment_channel_label: str,
    robust_crop: bool,
    anchor_corr_thresh: float,
    min_post_correlation: float,
    plate_shifts: list[tuple[float, float]] | None = None,
) -> tuple[np.ndarray, list[dict[str, Any]], dict[str, int]]:
    """Anchored/masked temporal registration. Net shifts come from _anchored_shifts (the single
    source of anchor math); we apply each net shift to ALL channels and feed the net shifts to
    the common-overlap crop, exactly like the to_first path."""
    stable_frames = stack[:, alignment_channel_index]
    net_shifts, post_corrs, reanchored_flags = _anchored_shifts(
        stable_frames, anchor_corr_thresh, plate_shifts=plate_shifts
    )

    # Reconstruct which frame served as the anchor per timepoint (for auditable anchor_ref_day):
    # anchor is day0 until a re-anchor promotes the last good frame; last-good tracks post>=thresh.
    anchor_ref_days = [rows[0]["day"]]
    last_good_index = 0
    anchor_index = 0
    for time_index in range(1, stack.shape[0]):
        if reanchored_flags[time_index]:
            anchor_index = last_good_index
        anchor_ref_days.append(rows[anchor_index]["day"])
        if post_corrs[time_index] >= anchor_corr_thresh:
            last_good_index = time_index

    # Per-well churn verdict (§2.6): fail if re-anchoring more than every other frame, or any
    # timepoint still below the QC gate after its retry.
    n_timepoints = stack.shape[0]
    n_reanchors = int(sum(reanchored_flags))
    anchor_churn = n_reanchors / (n_timepoints - 1) if n_timepoints > 1 else 0.0
    any_below_gate = any(p < min_post_correlation for p in post_corrs[1:])
    well_registration_qc_pass = not (anchor_churn > 0.5 or any_below_gate)

    registered = [stack[0]]
    qc_rows = [
        {
            "well": well,
            "condition": condition_for_well(well),
            "timepoint_day": rows[0]["day"],
            "registration_channel": alignment_channel_label,
            "estimated_y_shift": 0.0,
            "estimated_x_shift": 0.0,
            "pre_registration_correlation": 1.0,
            "post_registration_correlation": 1.0,
            "overlap_fraction": 1.0,
            "registration_error": float("nan"),
            "qc_pass": True,
            "large_shift": False,
            "reanchored": False,
            "anchor_ref_day": anchor_ref_days[0],
            "n_reanchors": n_reanchors,
            "anchor_churn": anchor_churn,
            "well_registration_qc_pass": well_registration_qc_pass,
            "qc_note": "anchored_masked_phase_cross_correlation",
        }
    ]

    for time_index in range(1, stack.shape[0]):
        dy, dx = net_shifts[time_index]
        post = post_corrs[time_index]
        moving = stable_frames[time_index]
        registered.append(apply_shift(stack[time_index], dy, dx))
        overlap = overlap_fraction(stack.shape[-2:], (dy, dx))
        qc_rows.append(
            {
                "well": well,
                "condition": condition_for_well(well),
                "timepoint_day": rows[time_index]["day"],
                "registration_channel": alignment_channel_label,
                "estimated_y_shift": dy,
                "estimated_x_shift": dx,
                "pre_registration_correlation": correlation(reference, moving),
                "post_registration_correlation": post,
                "overlap_fraction": overlap,
                "registration_error": float("nan"),
                **classify_registration_qc(
                    overlap,
                    dy,
                    dx,
                    stack.shape[-2],
                    stack.shape[-1],
                    post_correlation=post,
                    min_post_correlation=min_post_correlation,
                ),
                "reanchored": bool(reanchored_flags[time_index]),
                "anchor_ref_day": anchor_ref_days[time_index],
                "n_reanchors": n_reanchors,
                "anchor_churn": anchor_churn,
                "well_registration_qc_pass": well_registration_qc_pass,
                "qc_note": "anchored_masked_phase_cross_correlation",
            }
        )

    registered_stack = np.stack(registered, axis=0)
    return (
        registered_stack,
        qc_rows,
        common_overlap_crop(stack.shape[-2:], net_shifts, robust=robust_crop),
    )


def build_summary_stats(measurements: pd.DataFrame, qc: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (well, condition), df in measurements.groupby(["well", "condition"], sort=True):
        ordered = df.sort_values("timepoint_day")
        days = ordered["timepoint_day"].to_numpy(dtype=float)
        ratios = ordered["diffuse_to_punctate_ratio"].to_numpy(dtype=float)
        slope = float(np.polyfit(days, ratios, 1)[0]) if len(days) >= 2 else np.nan
        rows.append(
            {
                "well": well,
                "condition": condition,
                "n_timepoints": len(ordered),
                "first_day": int(days[0]),
                "last_day": int(days[-1]),
                "first_diffuse_to_punctate_ratio": float(ratios[0]),
                "last_diffuse_to_punctate_ratio": float(ratios[-1]),
                "diffuse_to_punctate_slope_per_day": slope,
                "mean_puncta_count": float(ordered["puncta_count"].mean()),
                "registration_qc_pass_count": int(qc[qc["well"] == well]["qc_pass"].sum()),
                "registration_qc_total_count": int((qc["well"] == well).sum()),
                "statistics_note": "tiny pilot; not enough independent replicates for inferential statistics",
            }
        )
    return pd.DataFrame(rows)


def write_registration_figure(
    stacks: dict[str, np.ndarray], selected: dict[str, list[dict[str, Any]]], path: Path
) -> None:
    fig, axes = plt.subplots(
        len(stacks), 3, figsize=(10, 3.5 * len(stacks)), constrained_layout=True
    )
    axes = np.atleast_2d(axes)
    for row_index, (well, stack) in enumerate(stacks.items()):
        ref = robust_registration_image(stack[0, 2 if stack.shape[1] > 2 else 0])
        last = robust_registration_image(stack[-1, 2 if stack.shape[1] > 2 else 0])
        overlay = np.zeros((*ref.shape, 3), dtype=np.float32)
        overlay[..., 0] = ref
        overlay[..., 1] = last
        for col, image, title in [
            (0, ref, f"{well} Day {selected[well][0]['day']} 488"),
            (1, last, f"{well} Day {selected[well][-1]['day']} aligned 488"),
            (2, overlay, f"{well} red=ref green=aligned"),
        ]:
            axes[row_index, col].imshow(image, cmap="gray" if col < 2 else None)
            axes[row_index, col].set_title(title)
            axes[row_index, col].set_axis_off()
    fig.savefig(path, dpi=180)
    plt.close(fig)


def write_mcherry_timeseries_figure(
    stacks: dict[str, np.ndarray], selected: dict[str, list[dict[str, Any]]], path: Path
) -> None:
    ncols = max(stack.shape[0] for stack in stacks.values())
    fig, axes = plt.subplots(
        len(stacks), ncols, figsize=(3.2 * ncols, 3.4 * len(stacks)), constrained_layout=True
    )
    axes = np.atleast_2d(axes)
    for row_index, (well, stack) in enumerate(stacks.items()):
        mcherry_index = 1 if stack.shape[1] > 1 else 0
        vmax = np.percentile(stack[:, mcherry_index], 99.5)
        for time_index in range(ncols):
            ax = axes[row_index, time_index]
            if time_index < stack.shape[0]:
                ax.imshow(stack[time_index, mcherry_index], cmap="magma", vmax=vmax)
                ax.set_title(f"{well} Day {selected[well][time_index]['day']}")
            ax.set_axis_off()
    fig.savefig(path, dpi=180)
    plt.close(fig)


def write_mcherry_timeseries_gifs(stacks: dict[str, np.ndarray], figures: Path) -> None:
    for well, stack in stacks.items():
        mcherry_index = 1 if stack.shape[1] > 1 else 0
        vmax = float(np.percentile(stack[:, mcherry_index], 99.5))
        frames = []
        for time_index in range(stack.shape[0]):
            frame = stack[time_index, mcherry_index].astype(np.float32)
            normalized = np.clip(frame / max(vmax, 1.0), 0, 1)
            rgb = plt.get_cmap("magma")(normalized)[..., :3]
            frames.append((rgb * 255).astype(np.uint8))
        imageio.mimsave(
            figures / f"{well}_aligned_mcherry_timeseries.gif", frames, duration=900, loop=0
        )


def write_metric_figure(measurements: pd.DataFrame, path: Path) -> None:
    fig, axes = plt.subplots(1, 3, figsize=(12, 3.8), constrained_layout=True)
    specs = [
        ("diffuse_to_punctate_ratio", "Diffuse / punctate"),
        ("puncta_count", "Puncta count"),
        ("diffuse_mcherry_mean_intensity", "Diffuse mean"),
    ]
    colors = {"E05": "#2f6f9f", "F05": "#b84a39"}
    for ax, (column, title) in zip(axes, specs, strict=True):
        for well, df in measurements.groupby("well", sort=True):
            ax.plot(
                df["timepoint_day"],
                df[column],
                marker="o",
                linewidth=2,
                label=well,
                color=colors.get(well),
            )
        ax.set_title(title)
        ax.set_xlabel("Day")
    axes[-1].legend(title="Well")
    fig.savefig(path, dpi=180)
    plt.close(fig)


def write_pi_readme(
    output: Path,
    data_root: Path,
    args: argparse.Namespace,
    inventory: pd.DataFrame,
    qc: pd.DataFrame,
    measurements: pd.DataFrame,
    summary: pd.DataFrame,
    selected: dict[str, list[dict[str, Any]]],
    started: str,
) -> None:
    exact_feb15_missing = "Feb15recopy" not in data_root.name
    trend_text = summarize_trend(summary)
    content = f"""# 260213 E05/F05 Longitudinal Pilot

Run started: {started}

## What Was Analyzed

This is a tiny real-data pilot from `{data_root}`. The requested folder prefix was
`260213_Feb15recopy`; the local folder found and used was `{data_root.name}`.
{"This naming mismatch should be verified with the acquisition/copy notes before presentation." if exact_feb15_missing else ""}

Wells analyzed:
- `{args.control_well.upper()}`: PLD3 + mCherry reporter control.
- `{args.experimental_well.upper()}`: PLD3 + TMEM106B + mCherry primary experimental well.

Timepoints: {", ".join(str(row["day"]) for row in selected[args.control_well.upper()])}

Channels: registration used 488, measurement used 561/mCherry. The mCherry channel was not used
as the primary registration reference because mCherry redistribution is the phenotype being
screened.

## What The Aligner Did

For each well, the script loaded the first {args.max_timepoints} fluorescence ND2 timepoints,
estimated X/Y drift with phase cross-correlation on the stable 488 channel, applied the same
transform to the 561/mCherry channel, cropped to common overlap, and measured mCherry punctate
versus diffuse signal inside a foreground mask.

## Outputs

- `dataset_inventory.csv`: dataset-wide inventory, when created before this pilot command.
- `selected_pilot_files.csv`: the six files loaded for this E05/F05 pilot when a full
  `dataset_inventory.csv` was already present.
- `registration_qc.csv`: shifts, correlations, overlap, and pass/fail flags.
- `mcherry_measurements.csv`: per-well/timepoint mCherry measurements.
- `summary_stats.csv`: pilot slopes and QC counts.
- `figures/registration_before_after.png`: 488-channel registration QC.
- `figures/aligned_timeseries_mcherry.png`: aligned mCherry time series.
- `figures/*_aligned_mcherry_timeseries.gif`: animated aligned mCherry examples.
- `figures/mcherry_metric_over_time.png`: mCherry metrics over time.
- `registered_stacks/`: small registered OME-TIFF stacks for review.

## Pilot Result

{trend_text}

This is real local microscopy data, but it is still a small screening pilot. The metric is a
longitudinal punctate-to-diffuse reporter redistribution score. It is not proof of lysosomal
rupture by itself.

## How This Helps The TMEM106B Paper

This workflow converts raw longitudinal imaging into same-well quantitative trajectories. It can
test whether PLD3+TMEM106B+mCherry shows progressive punctate-to-diffuse reporter behavior
relative to mCherry reporter controls, giving a light-microscopy bridge to the paper's model of
lysosomal TMEM106B fibril accumulation and rupture-like phenotypes. It also helps prioritize
wells, timepoints, and neurons for cryo-CLEM, immunostaining, and lysosome assays.

## Limitations And Next Steps

- Add orthogonal rupture markers: Galectin-3/Galectin-8 recruitment, LAMP1/LAMP2 morphology,
  LysoTracker loss, p62/LC3, or LLOMe positive control.
- Expand to more wells, sites, cells, and replicate pairs before inferential statistics.
- Validate segmentation/tracking manually for same-neuron claims.
- Tighten registration QC thresholds after reviewing failed or large-shift alignments.
- The current pilot has {int(qc["qc_pass"].sum())}/{len(qc)} registration QC rows passing.
- Not enough independent replicates for mixed-effects or inferential statistics.
"""
    (output / "PI_README.md").write_text(content, encoding="utf-8")


def write_methods(
    output: Path, args: argparse.Namespace, selected: dict[str, list[dict[str, Any]]]
) -> None:
    content = f"""# Methods Draft

## Dataset Organization

Raw ND2 files were read in place from the 260213 recopy dataset folder and were not modified.
The pilot selected wells {args.control_well.upper()} and {args.experimental_well.upper()} and the
earliest available fluorescence timepoints: {", ".join(str(row["day"]) for row in selected[args.control_well.upper()])}.

## Image Loading

ND2 files were opened lazily with the Python `nd2` package. For this pilot, the first site/position
was selected when a position axis was present, and arrays were standardized to `CYX`. Supported
axis patterns include `YX`, `CYX`, `ZCYX`, and common time/position variants after selecting a
single time/position and max-projecting Z when present.

## Channel Selection

The 488 channel was used for registration as a stable non-phenotype channel. The 561 channel was
used for mCherry phenotype measurement. Emergency mCherry-based registration was not used in this
pilot.

## Well/Day Registration

The earliest selected day was used as the reference. Later days were robustly normalized by
background percentile clipping and light Gaussian smoothing, then registered to the reference with
`skimage.registration.phase_cross_correlation` using subpixel upsampling. The resulting X/Y shift
was applied to all channels with linear interpolation, and stacks were cropped to their common
overlap.

## Neuron/ROI Measurement

This pilot uses a whole-field foreground mask rather than validated single-neuron tracking. The
foreground mask is derived from the aligned 488 channel and used to restrict 561/mCherry
measurement.

## Puncta/Diffuse mCherry Quantification

mCherry images were background-subtracted with a low percentile estimate. Puncta candidates were
detected with a Difference-of-Gaussian image and robust median/MAD plus high-percentile threshold.
Connected components were size-filtered. Diffuse intensity was measured as foreground signal
outside puncta. The reported rupture-like score is diffuse integrated intensity divided by
punctate integrated intensity plus epsilon.

## QC And Exclusion Criteria

Registration QC includes estimated shifts, pre/post registration correlation, overlap fraction,
registration error, and a pilot pass/fail flag. Alignments should be manually reviewed before
biological interpretation.

## Statistical Analysis

For this tiny pilot, per-timepoint values and per-well slopes are reported. There are not enough
independent wells/sites/cells for inferential statistics or mixed-effects modeling.

## Software Versions

Core packages: numpy, pandas, scipy, scikit-image, tifffile, matplotlib, and optional nd2. Exact
versions should be captured from the analysis environment for a manuscript supplement.
"""
    (output / "METHODS_DRAFT.md").write_text(content, encoding="utf-8")


def write_run_log(
    output: Path,
    args: argparse.Namespace,
    selected: dict[str, list[dict[str, Any]]],
    started: str,
    extra: list[str],
) -> None:
    lines = [
        "# Codex Run Log",
        "",
        f"Started: {started}",
        f"Data root: {args.data_root}",
        f"Config requested: {args.config}",
        f"Control well: {args.control_well}",
        f"Experimental well: {args.experimental_well}",
        f"Channels requested: {args.channels}",
        f"Illumination correction: {args.illumination_correct} (ic_sample_fraction={args.ic_sample_fraction})",
        f"Max timepoints: {args.max_timepoints}",
        f"Max sites: {args.max_sites}",
        "",
        "Selected files:",
    ]
    for well, items in selected.items():
        for row in items:
            lines.append(f"- {well} Day {row['day']}: {row['path']}")
    lines.extend(["", *extra])
    (output / "codex_run_log.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def print_terminal_summary(
    output: Path,
    data_root: Path,
    selected: dict[str, list[dict[str, Any]]],
    qc: pd.DataFrame,
    measurements: pd.DataFrame,
) -> None:
    print(f"Output folder: {output}")
    print(f"Dataset path used: {data_root}")
    print("Wells used: " + ", ".join(selected))
    days = sorted({row["day"] for rows in selected.values() for row in rows})
    print("Timepoints used: " + ", ".join(map(str, days)))
    print("Channels used: 488 registration, 561 mCherry measurement")
    print(f"Registration QC pass/total: {int(qc['qc_pass'].sum())}/{len(qc)}")
    for well, df in measurements.groupby("well", sort=True):
        ordered = df.sort_values("timepoint_day")
        trend = (
            ordered["diffuse_to_punctate_ratio"].iloc[-1]
            - ordered["diffuse_to_punctate_ratio"].iloc[0]
        )
        print(f"{well} diffuse/punctate change: {trend:.4g}")
    print("Open PI_README.md and figures/ for the PI-ready summary.")


def summarize_trend(summary: pd.DataFrame) -> str:
    if summary.empty:
        return "No mCherry measurements were produced."
    lines = []
    for _, row in summary.iterrows():
        direction = "increased" if row["diffuse_to_punctate_slope_per_day"] > 0 else "decreased"
        lines.append(
            f"{row['well']} ({row['condition']}) {direction} from "
            f"{row['first_diffuse_to_punctate_ratio']:.4g} to {row['last_diffuse_to_punctate_ratio']:.4g} "
            f"(slope {row['diffuse_to_punctate_slope_per_day']:.4g} per day)."
        )
    return " ".join(lines)


def choose_channel_index(channel_names: list[str], target: str) -> int:
    target_norm = re.sub(r"\D", "", target)
    for index, name in enumerate(channel_names):
        if target_norm and target_norm in re.sub(r"\D", "", name):
            return index
    if target_norm == "561" and len(channel_names) > 1:
        return 1
    if target_norm == "488" and len(channel_names) > 2:
        return 2
    return 0


def infer_day(name: str) -> int | None:
    match = re.search(r"day\s*[_-]?(\d+)", name, re.IGNORECASE)
    return int(match.group(1)) if match else None


def infer_channel_string(name: str) -> str:
    match = re.search(r"Channel(.+?)(?:_Seq|\.nd2)", name, re.IGNORECASE)
    return match.group(1).replace(",", "|").strip() if match else ""


def infer_sequence(name: str) -> str:
    match = re.search(r"Seq(\d+)", name, re.IGNORECASE)
    return f"Seq{match.group(1)}" if match else ""


def condition_for_well(well: str) -> str:
    return CONDITIONS.get(well[0].upper(), "unknown")


if __name__ == "__main__":
    main()
