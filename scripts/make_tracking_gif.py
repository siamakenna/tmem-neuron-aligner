#!/usr/bin/env python
"""Animate LoG-tracked cells across imaging days as GIFs, with a fading position trail.

Produces up to three GIF layouts from a registered TCYX well stack:
  montage   — one frame per day; grid of per-cell zoom crops (mNeon | mCherry) with trails.
  fullfield — one frame per day; whole mNeon field with every tracked cell's crosshair + trail.
  percell   — one GIF per cell; 2-panel (mNeon | mCherry) zoom flipbook with trail.

The tracking (LoG blob detection + KDTree nearest-neighbour matching across days) mirrors
notebooks/02_neuron_tracking_qc.ipynb. The GIF helpers mirror
scripts/make_mcherry_timeseries_videos.py (repo convention is self-contained scripts).
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
import tifffile as tif  # noqa: E402
from matplotlib.collections import LineCollection  # noqa: E402
from PIL import Image  # noqa: E402
from scipy.spatial import KDTree  # noqa: E402
from skimage.feature import blob_log  # noqa: E402
from skimage.transform import downscale_local_mean  # noqa: E402

DEFAULT_STACK_DIR = Path("reports/260213_pilot_9day/registered_stacks")
DEFAULT_DAYS = [8, 12, 16, 20, 25, 29, 32, 36, 39]


# --- GIF helpers (mirrored from scripts/make_mcherry_timeseries_videos.py) ---
def robust_limits(arr: np.ndarray) -> tuple[float, float]:
    values = arr.astype(np.float32)
    vmin, vmax = np.percentile(values, [0.2, 99.8])
    if vmax <= vmin:
        vmax = vmin + 1
    return float(vmin), float(vmax)


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


# --- tracking (inlined from notebook; not importable from a .ipynb) ---
def _clip_gray(img: np.ndarray) -> np.ndarray:
    """Percentile-clip to [0,1] float for blob detection / display."""
    lo, hi = np.percentile(img, [1, 99])
    return np.clip((img.astype(float) - lo) / (hi - lo + 1e-9), 0, 1)


def segment_log(
    frame: np.ndarray,
    min_sigma: float = 3,
    max_sigma: float = 15,
    num_sigma: int = 10,
    threshold: float = 0.05,
    ds: int = 2,
) -> np.ndarray:
    """LoG blob detection on a 2D frame. Returns (N, 3) array of (y, x, radius).

    Runs on a `ds`x downsampled image for speed; sigmas divided by `ds`, coords scaled back.
    """
    img = downscale_local_mean(_clip_gray(frame), (ds, ds))
    blobs = blob_log(
        img,
        min_sigma=min_sigma / ds,
        max_sigma=max_sigma / ds,
        num_sigma=num_sigma,
        threshold=threshold,
    )
    if len(blobs) == 0:
        return np.empty((0, 3), dtype=float)
    blobs[:, :2] *= ds
    blobs[:, 2] = blobs[:, 2] * ds * np.sqrt(2)
    return blobs


def track_cells(
    stack: np.ndarray, mneon_ch: int, max_dist: float = 50
) -> tuple[dict[int, list], np.ndarray]:
    """Track day-0 blobs across all timepoints via KDTree nearest-neighbour matching.

    Returns (tracked, ref_blobs) where tracked[i] is a list of blob-or-None per day.
    """
    n_t = stack.shape[0]
    all_blobs = [segment_log(stack[t, mneon_ch]) for t in range(n_t)]
    ref_blobs = all_blobs[0]
    tracked = {i: [ref_blobs[i]] for i in range(len(ref_blobs))}

    for t in range(1, n_t):
        blobs_t = all_blobs[t]
        if len(blobs_t) == 0:
            for i in range(len(ref_blobs)):
                tracked[i].append(None)
            continue
        tree = KDTree(blobs_t[:, :2])
        dists, idxs = tree.query(ref_blobs[:, :2])
        for i in range(len(ref_blobs)):
            tracked[i].append(blobs_t[idxs[i]] if dists[i] <= max_dist else None)
    return tracked, ref_blobs


def select_cells(tracked: dict[int, list], n: int) -> list[int]:
    """Indices of cells tracked across ALL days, sorted by day-0 radius desc, top n."""
    full = [i for i, m in tracked.items() if all(x is not None for x in m)]
    full.sort(key=lambda i: tracked[i][0][2], reverse=True)
    return full[:n]


def colors_for(cell_ids: list[int]) -> dict[int, tuple]:
    """Fixed tab20 color per cell (wraps after 20 cells)."""
    n = max(len(cell_ids) - 1, 1)
    return {ref_i: plt.cm.tab20(j / n) for j, ref_i in enumerate(cell_ids)}


def crop_bounds(centroids: list, half: int, h: int, w: int) -> tuple[int, int, int, int]:
    """Fixed crop centered on the MEAN centroid, clamped to image bounds."""
    ys = [c[0] for c in centroids]
    xs = [c[1] for c in centroids]
    cy, cx = int(np.mean(ys)), int(np.mean(xs))
    yr0 = max(0, cy - half)
    yr1 = min(h, cy + half)
    xc0 = max(0, cx - half)
    xc1 = min(w, cx + half)
    return yr0, yr1, xc0, xc1


def draw_trail(
    ax,
    centroids: list,
    t: int,
    color: tuple,
    xoff: int,
    yoff: int,
    trail_length: int = 0,
    no_trail: bool = False,
) -> None:
    """Draw a fading polyline through past centroids (days 0..t) + a '+' at day t.

    Coordinates are converted to crop-local by subtracting (yoff, xoff). `trail_length` <= 0
    means show the whole path so far; otherwise only the last `trail_length` days.
    """
    lo = 0 if (trail_length <= 0 or no_trail) else max(0, t - trail_length)
    xs = np.array([c[1] - xoff for c in centroids[: t + 1]])
    ys = np.array([c[0] - yoff for c in centroids[: t + 1]])
    if not no_trail and t > 0:
        pts = np.column_stack([xs, ys])[lo:]
        if len(pts) >= 2:
            segs = np.stack([pts[:-1], pts[1:]], axis=1)
            rgba = np.tile(np.array([*color[:3], 1.0]), (len(segs), 1))
            rgba[:, 3] = np.linspace(0.15, 1.0, len(segs))
            ax.add_collection(LineCollection(segs, colors=rgba, linewidths=1.6))
    ax.plot(xs[-1], ys[-1], "+", color=color, markersize=14, markeredgewidth=2.0)


def fig_to_pil(fig) -> Image.Image:
    """Render an Agg figure to an RGB PIL image and close it.

    matplotlib 3.11 removed canvas.tostring_rgb — use buffer_rgba() and drop the alpha.
    """
    fig.canvas.draw()
    buf = np.asarray(fig.canvas.buffer_rgba())  # (H, W, 4) uint8
    img = Image.fromarray(buf[..., :3].copy())  # copy detaches from the canvas buffer
    plt.close(fig)
    return img


def _limits_over_days(stack, ch, yr0, yr1, xc0, xc1) -> tuple[float, float]:
    """Fixed display limits for a channel over all days within a crop (no flicker)."""
    crops = [stack[t, ch, yr0:yr1, xc0:xc1] for t in range(stack.shape[0])]
    return robust_limits(np.concatenate([c.ravel() for c in crops]))


def build_montage_frames(stack, tracked, cells, days, colors, args) -> list[Image.Image]:
    h, w = stack.shape[2], stack.shape[3]
    n = len(cells)
    # precompute each cell's crop + fixed per-channel limits
    boxes, mn_lims, mc_lims = [], [], []
    for ref_i in cells:
        box = crop_bounds(tracked[ref_i], args.half, h, w)
        boxes.append(box)
        mn_lims.append(_limits_over_days(stack, args.mneon_channel, *box))
        mc_lims.append(_limits_over_days(stack, args.mcherry_channel, *box))

    frames = []
    for t in range(stack.shape[0]):
        fig, axes = plt.subplots(n, 2, figsize=(4, 2 * n), dpi=100)
        axes = np.atleast_2d(axes)
        for row, ref_i in enumerate(cells):
            yr0, yr1, xc0, xc1 = boxes[row]
            ax_mn, ax_mc = axes[row, 0], axes[row, 1]
            ax_mn.imshow(
                stack[t, args.mneon_channel, yr0:yr1, xc0:xc1],
                cmap="gray",
                vmin=mn_lims[row][0],
                vmax=mn_lims[row][1],
                interpolation="nearest",
            )
            ax_mc.imshow(
                stack[t, args.mcherry_channel, yr0:yr1, xc0:xc1],
                cmap="magma",
                vmin=mc_lims[row][0],
                vmax=mc_lims[row][1],
                interpolation="nearest",
            )
            for ax in (ax_mn, ax_mc):
                draw_trail(
                    ax, tracked[ref_i], t, colors[ref_i], xc0, yr0, args.trail_length, args.no_trail
                )
                ax.axis("off")
                ax.set_xlim(0, xc1 - xc0)
                ax.set_ylim(yr1 - yr0, 0)
            ax_mn.text(
                0.02,
                0.5,
                f"Cell {row + 1}",
                transform=ax_mn.transAxes,
                fontsize=7,
                color="white",
                va="center",
                ha="left",
            )
        fig.suptitle(f"{args.well}  Day {days[t]}", fontsize=10, y=1.0)
        fig.subplots_adjust(left=0.0, right=1.0, top=0.97, bottom=0.0, hspace=0.02, wspace=0.02)
        frames.append(fig_to_pil(fig))
    return ping_pong(frames)


def build_fullfield_frames(stack, tracked, cells, days, colors, args) -> list[Image.Image]:
    h, w = stack.shape[2], stack.shape[3]
    vmin, vmax = robust_limits(stack[:, args.mneon_channel])
    asp = h / w
    frames = []
    for t in range(stack.shape[0]):
        fig, ax = plt.subplots(figsize=(8, 8 * asp), dpi=100)
        ax.imshow(
            stack[t, args.mneon_channel], cmap="gray", vmin=vmin, vmax=vmax, interpolation="nearest"
        )
        for ref_i in cells:
            draw_trail(ax, tracked[ref_i], t, colors[ref_i], 0, 0, args.trail_length, args.no_trail)
        ax.axis("off")
        ax.set_xlim(0, w)
        ax.set_ylim(h, 0)
        fig.suptitle(
            f"{args.well}  Day {days[t]}  ({len(cells)} tracked cells)", fontsize=11, y=1.0
        )
        fig.subplots_adjust(left=0.0, right=1.0, top=0.97, bottom=0.0)
        frames.append(fig_to_pil(fig))
    return ping_pong(frames)


def build_percell_frames(stack, tracked, ref_i, days, color, args) -> list[Image.Image]:
    h, w = stack.shape[2], stack.shape[3]
    box = crop_bounds(tracked[ref_i], args.half, h, w)
    yr0, yr1, xc0, xc1 = box
    mn_lim = _limits_over_days(stack, args.mneon_channel, *box)
    mc_lim = _limits_over_days(stack, args.mcherry_channel, *box)
    frames = []
    for t in range(stack.shape[0]):
        fig, (ax_mn, ax_mc) = plt.subplots(1, 2, figsize=(6, 3), dpi=100)
        ax_mn.imshow(
            stack[t, args.mneon_channel, yr0:yr1, xc0:xc1],
            cmap="gray",
            vmin=mn_lim[0],
            vmax=mn_lim[1],
            interpolation="nearest",
        )
        ax_mc.imshow(
            stack[t, args.mcherry_channel, yr0:yr1, xc0:xc1],
            cmap="magma",
            vmin=mc_lim[0],
            vmax=mc_lim[1],
            interpolation="nearest",
        )
        for ax, name in ((ax_mn, "mNeon"), (ax_mc, "mCherry")):
            draw_trail(ax, tracked[ref_i], t, color, xc0, yr0, args.trail_length, args.no_trail)
            ax.axis("off")
            ax.set_xlim(0, xc1 - xc0)
            ax.set_ylim(yr1 - yr0, 0)
            ax.set_title(name, fontsize=8, pad=2)
        fig.suptitle(f"{args.well}  Day {days[t]}", fontsize=10, y=1.0)
        fig.subplots_adjust(left=0.0, right=1.0, top=0.90, bottom=0.0, wspace=0.02)
        frames.append(fig_to_pil(fig))
    return ping_pong(frames)


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--stack-dir", type=Path, default=DEFAULT_STACK_DIR)
    p.add_argument("--well", default="E05")
    p.add_argument("--days", nargs="+", type=int, default=DEFAULT_DAYS)
    p.add_argument("--mneon-channel", type=int, default=2)
    p.add_argument("--mcherry-channel", type=int, default=1)
    p.add_argument("--output-dir", type=Path, default=Path("outputs/plots/tracking_gifs"))
    p.add_argument("--n-cells", type=int, default=8)
    p.add_argument("--fullfield-cells", type=int, default=20)
    p.add_argument("--max-dist", type=float, default=50.0)
    p.add_argument("--half", type=int, default=200)
    p.add_argument("--duration-ms", type=int, default=700)
    p.add_argument("--trail-length", type=int, default=0, help="0 = whole path so far")
    p.add_argument(
        "--modes",
        nargs="+",
        choices=["montage", "fullfield", "percell"],
        default=["montage", "fullfield", "percell"],
    )
    p.add_argument("--no-trail", action="store_true")
    return p.parse_args(argv), p


def main(argv=None) -> None:
    args, parser = parse_args(argv)

    stack_path = args.stack_dir / f"{args.well}_registered_common_overlap_tcyx.ome.tif"
    if not stack_path.exists():
        parser.error(f"Stack not found: {stack_path}")

    stack = np.asarray(tif.imread(stack_path))
    if stack.ndim == 3:
        stack = stack[np.newaxis]  # single-timepoint TCYX: the T axis is squeezed on read
    if stack.ndim != 4:
        parser.error(f"Expected a TCYX stack, got shape {stack.shape}")
    n_t = stack.shape[0]
    if len(args.days) != n_t:
        parser.error(f"--days has {len(args.days)} entries but stack has {n_t} timepoints")

    tracked, _ = track_cells(stack, args.mneon_channel, args.max_dist)
    need = max(args.n_cells, args.fullfield_cells)
    cells = select_cells(tracked, need)
    if not cells:
        raise SystemExit(
            f"No cells tracked across all {n_t} days for {args.well} (try a higher --max-dist)"
        )
    colors = colors_for(cells)  # cover every selected cell; tab20 wraps after 20

    args.output_dir.mkdir(parents=True, exist_ok=True)
    saved = []

    if "montage" in args.modes:
        frames = build_montage_frames(
            stack, tracked, cells[: args.n_cells], args.days, colors, args
        )
        path = args.output_dir / f"{args.well}_tracking_montage.gif"
        save_gif(frames, path, args.duration_ms)
        saved.append(path)

    if "fullfield" in args.modes:
        frames = build_fullfield_frames(
            stack, tracked, cells[: args.fullfield_cells], args.days, colors, args
        )
        path = args.output_dir / f"{args.well}_tracking_fullfield.gif"
        save_gif(frames, path, args.duration_ms)
        saved.append(path)

    if "percell" in args.modes:
        for rank, ref_i in enumerate(cells[: args.n_cells], start=1):
            color = colors.get(ref_i, plt.cm.tab20(0))
            frames = build_percell_frames(stack, tracked, ref_i, args.days, color, args)
            radius = int(tracked[ref_i][0][2])
            path = args.output_dir / f"{args.well}_cell{rank:02d}_r{radius}.gif"
            save_gif(frames, path, args.duration_ms)
            saved.append(path)

    for path in saved:
        print(f"Saved: {path}")


if __name__ == "__main__":
    main()
