from __future__ import annotations

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.collections import LineCollection

from scripts.make_tracking_gif import (
    colors_for,
    crop_bounds,
    draw_trail,
    fig_to_pil,
    ping_pong,
    robust_limits,
    segment_log,
    select_cells,
    track_cells,
)


def _gauss(h, w, centers, sigma=4.0, amp=6000.0):
    """Sum of Gaussian spots on an (h, w) float frame — deterministic, no RNG."""
    y, x = np.mgrid[:h, :w]
    frame = np.zeros((h, w), dtype=np.float32)
    for cy, cx in centers:
        frame += amp * np.exp(-(((y - cy) ** 2 + (x - cx) ** 2) / (2 * sigma**2)))
    return frame


def _stack(centers_per_day, h=128, w=160, mneon_ch=2, n_ch=3):
    """Build a (T, C, H, W) uint16 stack with blobs in the mNeon channel."""
    t = len(centers_per_day)
    stack = np.zeros((t, n_ch, h, w), dtype=np.uint16)
    for i, centers in enumerate(centers_per_day):
        stack[i, mneon_ch] = _gauss(h, w, centers).astype(np.uint16)
    return stack


# --- segment_log ---
def test_segment_log_detects_blobs():
    frame = _gauss(128, 160, [(30, 30), (30, 120), (90, 75)])
    blobs = segment_log(frame)
    assert blobs.shape[1] == 3
    assert len(blobs) >= 2  # 3 well-separated spots, allow one miss/merge
    assert (blobs[:, 2] > 0).all()


def test_segment_log_empty_frame():  # edge
    blobs = segment_log(np.zeros((128, 160), dtype=np.uint16))
    assert blobs.shape == (0, 3)


# --- track_cells / select_cells ---
def test_track_cells_small_shift_matches():
    # one blob drifting 4px/day — well under max_dist
    centers = [[(40, 40)], [(44, 44)], [(48, 48)]]
    tracked, ref = track_cells(_stack(centers), mneon_ch=2, max_dist=50)
    assert len(select_cells(tracked, 10)) >= 1


def test_track_cells_large_jump_breaks():  # edge
    centers = [[(40, 40)], [(40, 130)], [(40, 130)]]  # 90px jump > max_dist
    tracked, _ = track_cells(_stack(centers), mneon_ch=2, max_dist=50)
    assert select_cells(tracked, 10) == []


def test_track_cells_disappearing_blob():  # edge
    centers = [[(40, 40)], [], [(40, 40)]]  # gone on day 1
    tracked, _ = track_cells(_stack(centers), mneon_ch=2, max_dist=50)
    assert select_cells(tracked, 10) == []


def test_select_cells_orders_by_radius():
    tracked = {
        0: [np.array([10, 10, 3.0]), np.array([10, 10, 3.0])],
        1: [np.array([20, 20, 9.0]), np.array([20, 20, 9.0])],
        2: [np.array([30, 30, 6.0]), None],  # dropped: has a None
    }
    assert select_cells(tracked, 10) == [1, 0]


def test_select_cells_n_exceeds_available():  # edge
    tracked = {0: [np.array([1, 1, 5.0])]}
    assert select_cells(tracked, 99) == [0]


# --- crop_bounds ---
def test_crop_bounds_centers_and_clamps():  # edge
    # centroids near the top-left corner
    cents = [np.array([5, 5, 3.0]), np.array([7, 7, 3.0])]
    yr0, yr1, xc0, xc1 = crop_bounds(cents, half=200, h=128, w=160)
    assert yr0 == 0 and xc0 == 0  # clamped, no negatives
    assert yr1 == 128 and xc1 == 160  # clamped to image size


def test_crop_bounds_interior_full_size():
    cents = [np.array([100, 100, 3.0])]
    yr0, yr1, xc0, xc1 = crop_bounds(cents, half=40, h=400, w=400)
    assert (yr1 - yr0, xc1 - xc0) == (80, 80)


# --- robust_limits ---
def test_robust_limits_constant_array():  # edge
    vmin, vmax = robust_limits(np.full((32, 32), 7.0, dtype=np.float32))
    assert vmax > vmin


# --- colors_for ---
def test_colors_for_consistent():
    c = colors_for([3, 7, 11])
    assert c[3] == c[3]
    assert c[3] != c[7] and c[7] != c[11]


# --- fig_to_pil ---
def test_fig_to_pil_rgb_and_size():
    fig = plt.figure(figsize=(2, 2), dpi=100)
    img = fig_to_pil(fig)
    assert img.mode == "RGB"
    assert img.size == (200, 200)  # figsize * dpi


# --- ping_pong ---
def test_ping_pong_lengths():  # edge
    frames = [object() for _ in range(4)]
    assert len(ping_pong(frames)) == 2 * 4 - 2
    two = [object(), object()]
    assert ping_pong(two) == two  # passthrough for < 3


# --- draw_trail ---
def _centroids(n):
    return [np.array([10 + 3 * i, 10 + 2 * i, 3.0]) for i in range(n)]


def test_draw_trail_marker_only_at_t0():  # edge
    fig, ax = plt.subplots()
    draw_trail(ax, _centroids(5), t=0, color=(1, 0, 0, 1), xoff=0, yoff=0)
    assert len(ax.collections) == 0  # no line yet
    assert len(ax.lines) == 1  # just the '+'
    plt.close(fig)


def test_draw_trail_no_trail_flag():  # edge
    fig, ax = plt.subplots()
    draw_trail(ax, _centroids(5), t=4, color=(1, 0, 0, 1), xoff=0, yoff=0, no_trail=True)
    assert len(ax.collections) == 0
    assert len(ax.lines) == 1
    plt.close(fig)


def test_draw_trail_length_limits_segments():  # edge
    fig, ax = plt.subplots()
    draw_trail(ax, _centroids(6), t=5, color=(1, 0, 0, 1), xoff=0, yoff=0, trail_length=2)
    coll = [c for c in ax.collections if isinstance(c, LineCollection)]
    assert len(coll) == 1
    assert len(coll[0].get_segments()) <= 2
    plt.close(fig)


def test_draw_trail_full_path():
    fig, ax = plt.subplots()
    draw_trail(ax, _centroids(5), t=4, color=(0, 1, 0, 1), xoff=0, yoff=0)
    coll = [c for c in ax.collections if isinstance(c, LineCollection)]
    assert len(coll[0].get_segments()) == 4  # 5 points -> 4 segments
    plt.close(fig)
