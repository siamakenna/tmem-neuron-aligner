#!/usr/bin/env python
from __future__ import annotations

import argparse
import os
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")

import numpy as np
import pandas as pd
import tifffile as tif
from PIL import Image, ImageDraw, ImageFont


DEFAULT_INTERIM_ROOT = Path("/Users/pmihack/claire/tmem_2026/data/TMEM106B_interim")
DEFAULT_PROCESSED_ROOT = Path("/Users/pmihack/claire/tmem_2026/data/TMEM106B_processed")
DEFAULT_WELLS = ["E05", "F05", "M07", "J06"]
DEFAULT_COMPARISON_PAIRS = [("E05", "F05"), ("M07", "J06")]
DEFAULT_DAYS = [8, 25, 39]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create small animated GIF examples from registered mCherry pilot stacks."
    )
    parser.add_argument("--interim-root", type=Path, default=DEFAULT_INTERIM_ROOT)
    parser.add_argument("--processed-root", type=Path, default=DEFAULT_PROCESSED_ROOT)
    parser.add_argument("--wells", nargs="+", default=DEFAULT_WELLS)
    parser.add_argument("--days-label", default="day8_day25_day39")
    parser.add_argument("--mcherry-channel", type=int, default=1)
    parser.add_argument("--alignment-channel", type=int, default=2)
    parser.add_argument("--frame-size", type=int, default=640)
    parser.add_argument("--duration-ms", type=int, default=1100)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_dir = args.processed_root / "pilot" / "mcherry_timeseries_videos"
    output_dir.mkdir(parents=True, exist_ok=True)

    qc = load_qc(args.processed_root / "pilot")
    made = []
    for well in args.wells:
        stack_path = stack_path_for(args.interim_root, well, args.days_label)
        if not stack_path.exists():
            continue
        stack = np.asarray(tif.imread(stack_path))
        metadata = well_metadata(qc, well)
        mcherry_frames = make_well_frames(
            stack,
            well=well,
            channel=args.mcherry_channel,
            days=DEFAULT_DAYS,
            qc=metadata,
            frame_size=args.frame_size,
            title_suffix="561 nm mCherry",
        )
        composite_frames = make_composite_frames(
            stack,
            well=well,
            mCherry_channel=args.mcherry_channel,
            alignment_channel=args.alignment_channel,
            days=DEFAULT_DAYS,
            qc=metadata,
            frame_size=args.frame_size,
        )
        m_path = output_dir / f"{well}_mcherry_timeseries.gif"
        c_path = output_dir / f"{well}_alignment_mcherry_composite.gif"
        save_gif(mcherry_frames, m_path, args.duration_ms)
        save_gif(composite_frames, c_path, args.duration_ms)
        made.extend([m_path, c_path])

    for left, right in DEFAULT_COMPARISON_PAIRS:
        if left not in args.wells or right not in args.wells:
            continue
        left_stack_path = stack_path_for(args.interim_root, left, args.days_label)
        right_stack_path = stack_path_for(args.interim_root, right, args.days_label)
        if not left_stack_path.exists() or not right_stack_path.exists():
            continue
        left_stack = np.asarray(tif.imread(left_stack_path))
        right_stack = np.asarray(tif.imread(right_stack_path))
        frames = make_side_by_side_frames(
            left_stack,
            right_stack,
            left=left,
            right=right,
            channel=args.mcherry_channel,
            days=DEFAULT_DAYS,
            qc_left=well_metadata(qc, left),
            qc_right=well_metadata(qc, right),
            frame_size=args.frame_size,
        )
        path = output_dir / f"{left}_vs_{right}_mcherry_timeseries.gif"
        save_gif(frames, path, args.duration_ms)
        made.append(path)

    manifest = pd.DataFrame(
        [{"path": str(path), "size_bytes": path.stat().st_size} for path in made]
    )
    manifest_path = output_dir / "timeseries_video_manifest.csv"
    manifest.to_csv(manifest_path, index=False)
    print(f"Wrote manifest: {manifest_path}")
    print(manifest.to_string(index=False))


def stack_path_for(interim_root: Path, well: str, days_label: str) -> Path:
    return (
        interim_root
        / "pilot"
        / f"{well.lower()}_longitudinal"
        / f"{well}_days_{days_label}_registered_common_overlap_tcyx.ome.tif"
    )


def load_qc(pilot_root: Path) -> pd.DataFrame:
    path = pilot_root / "mcherry_qc_report" / "mcherry_longitudinal_qc_report.csv"
    if not path.exists():
        return pd.DataFrame()
    qc = pd.read_csv(path)
    qc["well"] = qc["well"].astype(str).str.upper()
    qc["day"] = qc["day"].astype(int)
    return qc


def well_metadata(qc: pd.DataFrame, well: str) -> pd.DataFrame:
    if qc.empty:
        return pd.DataFrame()
    return qc[qc["well"] == well].copy()


def make_well_frames(
    stack: np.ndarray,
    *,
    well: str,
    channel: int,
    days: list[int],
    qc: pd.DataFrame,
    frame_size: int,
    title_suffix: str,
) -> list[Image.Image]:
    channel_stack = stack[:, channel]
    limits = robust_limits(channel_stack)
    frames = []
    for index, day in enumerate(days):
        image = normalize_to_uint8(channel_stack[index], limits)
        pil = resize_gray(image, frame_size)
        frames.append(annotate_frame(pil, well, day, qc_row(qc, day), title_suffix))
    return ping_pong(frames)


def make_composite_frames(
    stack: np.ndarray,
    *,
    well: str,
    mCherry_channel: int,
    alignment_channel: int,
    days: list[int],
    qc: pd.DataFrame,
    frame_size: int,
) -> list[Image.Image]:
    mcherry = stack[:, mCherry_channel]
    alignment = stack[:, alignment_channel]
    red_limits = robust_limits(mcherry)
    green_limits = robust_limits(alignment)
    frames = []
    for index, day in enumerate(days):
        red = normalize_to_uint8(mcherry[index], red_limits)
        green = normalize_to_uint8(alignment[index], green_limits)
        rgb = np.zeros((*red.shape, 3), dtype=np.uint8)
        rgb[..., 0] = red
        rgb[..., 1] = green
        pil = resize_rgb(rgb, frame_size)
        frames.append(annotate_frame(pil, well, day, qc_row(qc, day), "red=mCherry green=488 nm"))
    return ping_pong(frames)


def make_side_by_side_frames(
    left_stack: np.ndarray,
    right_stack: np.ndarray,
    *,
    left: str,
    right: str,
    channel: int,
    days: list[int],
    qc_left: pd.DataFrame,
    qc_right: pd.DataFrame,
    frame_size: int,
) -> list[Image.Image]:
    left_channel = left_stack[:, channel]
    right_channel = right_stack[:, channel]
    limits = robust_limits(np.concatenate([left_channel.ravel(), right_channel.ravel()]))
    frames = []
    for index, day in enumerate(days):
        left_image = resize_gray(normalize_to_uint8(left_channel[index], limits), frame_size)
        right_image = resize_gray(normalize_to_uint8(right_channel[index], limits), frame_size)
        left_image = annotate_frame(left_image, left, day, qc_row(qc_left, day), "561 nm mCherry")
        right_image = annotate_frame(right_image, right, day, qc_row(qc_right, day), "561 nm mCherry")
        canvas = Image.new("RGB", (left_image.width + right_image.width, left_image.height), "black")
        canvas.paste(left_image.convert("RGB"), (0, 0))
        canvas.paste(right_image.convert("RGB"), (left_image.width, 0))
        frames.append(canvas)
    return ping_pong(frames)


def robust_limits(arr: np.ndarray) -> tuple[float, float]:
    values = arr.astype(np.float32)
    vmin, vmax = np.percentile(values, [0.2, 99.8])
    if vmax <= vmin:
        vmax = vmin + 1
    return float(vmin), float(vmax)


def normalize_to_uint8(frame: np.ndarray, limits: tuple[float, float]) -> np.ndarray:
    vmin, vmax = limits
    scaled = np.clip((frame.astype(np.float32) - vmin) / (vmax - vmin), 0, 1)
    return (scaled * 255).astype(np.uint8)


def resize_gray(frame: np.ndarray, frame_size: int) -> Image.Image:
    pil = Image.fromarray(frame, mode="L")
    return resize_pil(pil, frame_size).convert("RGB")


def resize_rgb(frame: np.ndarray, frame_size: int) -> Image.Image:
    return resize_pil(Image.fromarray(frame, mode="RGB"), frame_size).convert("RGB")


def resize_pil(pil: Image.Image, frame_size: int) -> Image.Image:
    pil.thumbnail((frame_size, frame_size), Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", (frame_size, frame_size), "black")
    canvas.paste(pil, ((frame_size - pil.width) // 2, (frame_size - pil.height) // 2))
    return canvas


def annotate_frame(
    image: Image.Image,
    well: str,
    day: int,
    qc: dict[str, object],
    subtitle: str,
) -> Image.Image:
    canvas = image.copy().convert("RGB")
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default()
    included = bool(qc.get("include_in_qc_filtered_analysis", True))
    reason = str(qc.get("exclusion_reason", "included"))
    condition = str(qc.get("condition", ""))
    score = qc.get("rupture_like_score", "")
    label = f"{well}  Day {day}  {subtitle}"
    status = "QC PASS" if included else f"QC FLAG: {reason}"
    score_text = f"score={float(score):.3f}" if score != "" and not pd.isna(score) else ""
    text_lines = [label, condition, f"{status} {score_text}".strip()]
    pad = 8
    line_height = 14
    box_height = pad * 2 + line_height * len(text_lines)
    draw.rectangle((0, 0, canvas.width, box_height), fill=(0, 0, 0))
    for i, text in enumerate(text_lines):
        color = (255, 210, 90) if (i == 2 and not included) else (255, 255, 255)
        draw.text((pad, pad + i * line_height), text, fill=color, font=font)
    return canvas


def qc_row(qc: pd.DataFrame, day: int) -> dict[str, object]:
    if qc.empty:
        return {}
    matches = qc[qc["day"] == day]
    if matches.empty:
        return {}
    return matches.iloc[0].to_dict()


def ping_pong(frames: list[Image.Image]) -> list[Image.Image]:
    if len(frames) < 3:
        return frames
    return frames + frames[-2:0:-1]


def save_gif(frames: list[Image.Image], path: Path, duration_ms: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(
        path,
        save_all=True,
        append_images=frames[1:],
        duration=duration_ms,
        loop=0,
        optimize=True,
    )


if __name__ == "__main__":
    main()
