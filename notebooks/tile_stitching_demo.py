# %% [markdown]
# # Tile-Based Stitching Demo
# Walks through each step of the new tile stitcher — first on a small synthetic
# 2×2 grid, then on a 3×3 grid carved from a real E05 image.

# %%
import sys
sys.path.insert(0, "../.claude/worktrees/tile-stitching/src")

import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.gridspec import GridSpec

from tmem_align.stitch import (
    build_adjacency,
    refine_shift,
    optimize_positions,
    assemble_edt,
    stitch_tiles,
    _edt_weights,
)

rng = np.random.default_rng(42)

# %% [markdown]
# ## Part 1 — Small scale: 2×2 synthetic grid
#
# We build four tiles from a single smooth image so the overlaps are coherent,
# then add per-tile brightness offsets to simulate illumination variation.

# %%
TILE_H, TILE_W = 256, 256
OVERLAP = 0.15  # 15 % overlap
STEP_Y = int(TILE_H * (1 - OVERLAP))
STEP_X = int(TILE_W * (1 - OVERLAP))

# Source image: smooth gradient + blob
y = np.linspace(0, 1, TILE_H * 2)[:, None]
x = np.linspace(0, 1, TILE_W * 2)[None, :]
source = (np.sin(y * 5) * np.cos(x * 4) * 0.5 + 0.5) * 3000
# add a bright blob to make registration interesting
cy, cx = TILE_H, TILE_W
yy, xx = np.ogrid[:TILE_H * 2, :TILE_W * 2]
blob = 4000 * np.exp(-((yy - cy)**2 + (xx - cx)**2) / (80**2))
source = (source + blob).astype(np.uint16)

# Carve 4 tiles with 15% overlap
offsets_2x2 = {
    0: (0,      0),
    1: (0,      STEP_X),
    2: (STEP_Y, 0),
    3: (STEP_Y, STEP_X),
}
tiles_2x2 = {}
for idx, (oy, ox) in offsets_2x2.items():
    t = source[oy:oy + TILE_H, ox:ox + TILE_W].copy().astype(np.float32)
    t += rng.integers(0, 300, size=t.shape)  # illumination noise
    tiles_2x2[idx] = t.astype(np.uint16)

fig, axes = plt.subplots(2, 2, figsize=(7, 7))
for idx, ax in zip(range(4), axes.flat):
    ax.imshow(tiles_2x2[idx], cmap="gray", vmin=0, vmax=6000)
    ax.set_title(f"Tile {idx}")
    ax.axis("off")
fig.suptitle("Four synthetic tiles (with noise + illumination offset)", fontsize=13)
plt.tight_layout()
plt.show()

# %% [markdown]
# ### Step 1 — Build adjacency from stage positions

# %%
# Positions as if from stage coordinates (pixel units, no jitter yet)
positions_2x2 = {k: (float(oy), float(ox)) for k, (oy, ox) in offsets_2x2.items()}

edges = build_adjacency(positions_2x2, (TILE_H, TILE_W))
print("Detected edges (tile_a, tile_b, relation):")
for a, b, rel in edges:
    direction = "right" if rel == (0, 1) else "down"
    print(f"  {a} → {b}  [{direction}]")

# Visualise adjacency
fig, ax = plt.subplots(figsize=(5, 5))
for idx, (py, px) in positions_2x2.items():
    rect = mpatches.FancyBboxPatch(
        (px, py), TILE_W, TILE_H,
        boxstyle="round,pad=4", linewidth=1.5, edgecolor="steelblue", facecolor="lightsteelblue", alpha=0.5
    )
    ax.add_patch(rect)
    ax.text(px + TILE_W / 2, py + TILE_H / 2, str(idx), ha="center", va="center", fontsize=14)

for a, b, rel in edges:
    ya, xa = positions_2x2[a][0] + TILE_H / 2, positions_2x2[a][1] + TILE_W / 2
    yb, xb = positions_2x2[b][0] + TILE_H / 2, positions_2x2[b][1] + TILE_W / 2
    ax.annotate("", xy=(xb, yb), xytext=(xa, ya),
                arrowprops=dict(arrowstyle="->", color="tomato", lw=2))

ax.set_xlim(-20, TILE_W * 2 + 20)
ax.set_ylim(-20, TILE_H * 2 + 20)
ax.set_aspect("equal")
ax.invert_yaxis()
ax.set_title("Tile adjacency graph")
plt.tight_layout()
plt.show()

# %% [markdown]
# ### Step 2 — Refine shifts with phase cross-correlation
#
# For each adjacent pair we extract the overlap strip and run phase correlation
# to measure the actual pixel offset.

# %%
overlap_px = max(int(round(min(TILE_H, TILE_W) * OVERLAP)), 16)
refined_edges = []

fig, axes = plt.subplots(len(edges), 3, figsize=(10, 3.5 * len(edges)))
if len(edges) == 1:
    axes = axes[None, :]

for row, (a, b, relation) in enumerate(edges):
    ta = tiles_2x2[a].astype(np.float32)
    tb = tiles_2x2[b].astype(np.float32)
    dy, dx = refine_shift(ta, tb, relation, overlap_px)

    ref_dy = positions_2x2[b][0] - positions_2x2[a][0]
    ref_dx = positions_2x2[b][1] - positions_2x2[a][1]

    if relation == (0, 1):
        roi_a = ta[:, -overlap_px:]
        roi_b = tb[:, :overlap_px]
        meas_dy = ref_dy + dy
        meas_dx = (TILE_W - overlap_px) + dx
    else:
        roi_a = ta[-overlap_px:, :]
        roi_b = tb[:overlap_px, :]
        meas_dy = (TILE_H - overlap_px) + dy
        meas_dx = ref_dx + dx

    refined_edges.append((a, b, meas_dy, meas_dx))

    direction = "right" if relation == (0, 1) else "down"
    axes[row, 0].imshow(roi_a, cmap="gray"); axes[row, 0].set_title(f"Tile {a} overlap edge"); axes[row, 0].axis("off")
    axes[row, 1].imshow(roi_b, cmap="gray"); axes[row, 1].set_title(f"Tile {b} overlap edge"); axes[row, 1].axis("off")
    axes[row, 2].axis("off")
    axes[row, 2].text(0.1, 0.7, f"Pair {a}→{b}  ({direction})", fontsize=12, transform=axes[row, 2].transAxes)
    axes[row, 2].text(0.1, 0.5, f"Stage offset: dy={ref_dy:.1f}  dx={ref_dx:.1f}", fontsize=10, transform=axes[row, 2].transAxes)
    axes[row, 2].text(0.1, 0.3, f"Phase-corr:  dy={dy:+.2f}  dx={dx:+.2f}", fontsize=10, transform=axes[row, 2].transAxes, color="tomato")
    axes[row, 2].text(0.1, 0.1, f"Measured:    dy={meas_dy:.2f}  dx={meas_dx:.2f}", fontsize=10, transform=axes[row, 2].transAxes, color="steelblue")

fig.suptitle("Overlap ROIs and refined shifts", fontsize=13)
plt.tight_layout()
plt.show()

# %% [markdown]
# ### Step 3 — Global position optimisation (least-squares)
#
# Pairwise shifts can be inconsistent (tile 0→1, 1→3, 0→2→3 might disagree).
# `optimize_positions` solves all positions jointly via sparse least-squares,
# minimising the sum of squared discrepancies.

# %%
opt_positions = optimize_positions(refined_edges, len(tiles_2x2))

# origin-normalise for display
min_y = min(p[0] for p in opt_positions.values())
min_x = min(p[1] for p in opt_positions.values())
opt_positions_norm = {k: (v[0] - min_y, v[1] - min_x) for k, v in opt_positions.items()}

fig, axes = plt.subplots(1, 2, figsize=(10, 4))
for ax, positions, title in zip(axes, [positions_2x2, opt_positions_norm], ["Stage positions", "Optimised positions"]):
    for idx, (py, px) in positions.items():
        rect = mpatches.FancyBboxPatch(
            (px, py), TILE_W, TILE_H,
            boxstyle="round,pad=4", linewidth=1.5, edgecolor="steelblue", facecolor="lightsteelblue", alpha=0.4
        )
        ax.add_patch(rect)
        ax.text(px + TILE_W / 2, py + TILE_H / 2, str(idx), ha="center", va="center", fontsize=14)
    ax.set_xlim(-20, TILE_W * 2 + 40)
    ax.set_ylim(-20, TILE_H * 2 + 40)
    ax.set_aspect("equal"); ax.invert_yaxis(); ax.set_title(title)

plt.tight_layout()
plt.show()

print("Position deltas (optimised − stage):")
for idx in sorted(positions_2x2):
    dy = opt_positions_norm[idx][0] - positions_2x2[idx][0]
    dx = opt_positions_norm[idx][1] - positions_2x2[idx][1]
    print(f"  Tile {idx}: Δy={dy:+.2f}  Δx={dx:+.2f}")

# %% [markdown]
# ### Step 4 — EDT blending
#
# Each tile is weighted by its distance-transform (pixels near the edge get
# low weight; the centre gets full weight). This smooths seams.

# %%
w = _edt_weights((TILE_H, TILE_W))

fig, axes = plt.subplots(1, 2, figsize=(9, 4))
axes[0].imshow(w, cmap="viridis", vmin=0, vmax=1)
axes[0].set_title("EDT weight map (one tile)")
plt.colorbar(axes[0].images[0], ax=axes[0], fraction=0.046)
axes[0].axis("off")

# show what blended overlap looks like for two horizontally adjacent tiles
canvas_demo = np.zeros((TILE_H, TILE_W * 2), dtype=np.float32)
weight_demo = np.zeros_like(canvas_demo)
for shift in [0, STEP_X]:
    canvas_demo[:, shift:shift + TILE_W] += 3000 * w
    weight_demo[:, shift:shift + TILE_W] += w
weight_demo[weight_demo == 0] = 1
axes[1].imshow(canvas_demo / weight_demo, cmap="viridis")
axes[1].axvline(STEP_X, color="tomato", lw=1.5, ls="--", label="tile boundary")
axes[1].axvline(TILE_W, color="white", lw=1.5, ls="--", label="tile boundary")
axes[1].set_title("Blended overlap region")
axes[1].legend(fontsize=8)
axes[1].axis("off")

plt.tight_layout()
plt.show()

# %% [markdown]
# ### Step 5 — Final assembly: naive grid vs tile stitcher

# %%
naive = stitch_tiles(tiles_2x2, positions_2x2, refine=False, overlap_fraction=OVERLAP)
refined = stitch_tiles(tiles_2x2, positions_2x2, refine=True, overlap_fraction=OVERLAP)
ground_truth = source[:naive.shape[0], :naive.shape[1]]

vmin, vmax = 0, 6000
fig, axes = plt.subplots(1, 3, figsize=(14, 5))
for ax, img, title in zip(axes, [ground_truth, naive, refined], ["Ground truth", "Stage positions only\n(no refinement)", "Phase-corr + global opt"]):
    ax.imshow(img, cmap="gray", vmin=vmin, vmax=vmax)
    ax.set_title(title)
    ax.axis("off")

plt.suptitle("2×2 synthetic comparison", fontsize=13)
plt.tight_layout()
plt.show()

# pixel-level error — shapes may differ by 1 px due to rounding; clip to min
h = min(naive.shape[0], refined.shape[0], ground_truth.shape[0])
w = min(naive.shape[1], refined.shape[1], ground_truth.shape[1])
gt = ground_truth[:h, :w].astype(float)
print(f"Stage-only MAE vs ground truth: {np.mean(np.abs(naive[:h, :w].astype(float) - gt)):.1f}")
print(f"Refined    MAE vs ground truth: {np.mean(np.abs(refined[:h, :w].astype(float) - gt)):.1f}")

# %% [markdown]
# ---
# ## Part 2 — Larger scale: 3×3 grid from a real E05 image
#
# We carve the real stitched E05 (day 8, BFP channel) into a 3×3 grid with
# 10% overlap, add ±8 px random jitter to each tile's position, then stitch
# and compare.

# %%
from tmem_align.io import read_image

E05_PATH = "/Users/pmihack/claire/tmem_2026/data/TMEM106B_interim/pilot/e05_longitudinal/E05_days_day8_day25_day39_raw_tcyx.ome.tif"
stack = read_image(E05_PATH)          # (3, 3, 2868, 2868)  t c y x
real_img = stack[0, 0].astype(np.float32)   # day 8, channel 0 (BFP)
print(f"Source image shape: {real_img.shape}  dtype: {real_img.dtype}")

# %%
GRID = 3
OVL = 0.10
TH = real_img.shape[0] // (GRID - OVL * (GRID - 1))
TH = int(TH); TW = TH
SY = int(TH * (1 - OVL)); SX = int(TW * (1 - OVL))

# Carve tiles, add ±8 px jitter to simulate stage inaccuracy
JITTER = 8
tiles_real = {}
true_positions = {}
jittered_positions = {}

for r in range(GRID):
    for c in range(GRID):
        idx = r * GRID + c
        oy, ox = r * SY, c * SX
        t = real_img[oy:oy + TH, ox:ox + TW]
        if t.shape != (TH, TW):
            continue
        tiles_real[idx] = t.astype(np.uint16)
        true_positions[idx] = (float(oy), float(ox))
        jittered_positions[idx] = (
            float(oy) + rng.integers(-JITTER, JITTER + 1),
            float(ox) + rng.integers(-JITTER, JITTER + 1),
        )

print(f"Tiles carved: {len(tiles_real)}  tile shape: {TH}×{TW}  step: {SY}×{SX}")

# %% [markdown]
# ### 3×3 tile mosaic

# %%
fig, axes = plt.subplots(GRID, GRID, figsize=(10, 10))
p_low, p_high = np.percentile(real_img, [1, 99])
for idx, ax in zip(sorted(tiles_real), axes.flat):
    ax.imshow(tiles_real[idx], cmap="gray", vmin=p_low, vmax=p_high)
    r, c = idx // GRID, idx % GRID
    ax.set_title(f"[{r},{c}]", fontsize=9)
    ax.axis("off")
fig.suptitle("Real E05 carved into 3×3 tiles (day 8, BFP ch)", fontsize=13)
plt.tight_layout()
plt.show()

# %% [markdown]
# ### Adjacency graph on the jittered grid

# %%
edges_real = build_adjacency(jittered_positions, (TH, TW))
print(f"Detected {len(edges_real)} edges from {len(tiles_real)} tiles")

fig, ax = plt.subplots(figsize=(6, 6))
for idx, (py, px) in jittered_positions.items():
    rect = mpatches.FancyBboxPatch(
        (px / SX, py / SY), 1, 1,
        boxstyle="round,pad=0.05", linewidth=1, edgecolor="steelblue", facecolor="lightsteelblue", alpha=0.4
    )
    ax.add_patch(rect)
    ax.text(px / SX + 0.5, py / SY + 0.5, str(idx), ha="center", va="center", fontsize=11)

for a, b, rel in edges_real:
    ya, xa = jittered_positions[a][0] / SY + 0.5, jittered_positions[a][1] / SX + 0.5
    yb, xb = jittered_positions[b][0] / SY + 0.5, jittered_positions[b][1] / SX + 0.5
    ax.annotate("", xy=(xb, yb), xytext=(xa, ya),
                arrowprops=dict(arrowstyle="->", color="tomato", lw=1.5))

ax.set_xlim(-0.2, GRID + 0.2); ax.set_ylim(-0.2, GRID + 0.2)
ax.set_aspect("equal"); ax.invert_yaxis()
ax.set_title(f"Adjacency: {len(edges_real)} edges detected")
plt.tight_layout()
plt.show()

# %% [markdown]
# ### Stitch — naive vs refined
#
# Both use the same jittered input positions.  The refined run adds phase-cross-
# correlation on each overlap pair and then a global least-squares solve.

# %%
naive_real = stitch_tiles(tiles_real, jittered_positions, refine=False, overlap_fraction=OVL)

refined_real = stitch_tiles(
    tiles_real, jittered_positions,
    refine=True, overlap_fraction=OVL,
)

# crop ground truth to same size as assembled output
gt_h = min(naive_real.shape[0], real_img.shape[0])
gt_w = min(naive_real.shape[1], real_img.shape[1])
gt_crop = real_img[:gt_h, :gt_w].astype(np.uint16)

fig, axes = plt.subplots(1, 3, figsize=(16, 6))
for ax, img, title in zip(
    axes,
    [gt_crop, naive_real, refined_real],
    ["Ground truth", "Naive grid stitch\n(no position refinement)", "Tile stitcher\n(phase-corr + global opt)"]
):
    ax.imshow(img, cmap="gray", vmin=p_low, vmax=p_high)
    ax.set_title(title, fontsize=11)
    ax.axis("off")

plt.suptitle("3×3 real E05 comparison (jitter ±8 px)", fontsize=13)
plt.tight_layout()
plt.show()

# %% [markdown]
# ### Seam visibility — zoom into tile junction

# %%
# Zoom into the junction between tiles [0,0], [0,1], [1,0], [1,1]
zoom_y = slice(SY - 40, SY + 40)
zoom_x = slice(SX - 40, SX + 40)

fig, axes = plt.subplots(1, 2, figsize=(10, 4))
for ax, img, title in zip(axes, [naive_real, refined_real], ["Naive", "Refined"]):
    crop = img[zoom_y, zoom_x]
    ax.imshow(crop, cmap="gray", vmin=p_low, vmax=p_high)
    ax.axhline(40, color="tomato", lw=1, ls="--")
    ax.axvline(40, color="tomato", lw=1, ls="--")
    ax.set_title(f"{title} — junction zoom")
    ax.axis("off")

plt.suptitle("Seam at 4-tile junction (red lines = tile edges)", fontsize=12)
plt.tight_layout()
plt.show()

# %% [markdown]
# ### Position correction: stage vs optimised

# %%
# Run the optimisation step in isolation for inspection
overlap_px_real = max(int(round(min(TH, TW) * OVL)), 16)
measured_edges_real = []
for a, b, relation in edges_real:
    ta = tiles_real[a].astype(np.float32)
    tb = tiles_real[b].astype(np.float32)
    ref_dy = jittered_positions[b][0] - jittered_positions[a][0]
    ref_dx = jittered_positions[b][1] - jittered_positions[a][1]
    try:
        local_dy, local_dx = refine_shift(ta, tb, relation, overlap_px_real)
    except Exception:
        measured_edges_real.append((a, b, ref_dy, ref_dx))
        continue
    if relation == (0, 1):
        meas_dy = ref_dy + local_dy
        meas_dx = (TW - overlap_px_real) + local_dx
    else:
        meas_dy = (TH - overlap_px_real) + local_dy
        meas_dx = ref_dx + local_dx
    measured_edges_real.append((a, b, meas_dy, meas_dx))

opt_real = optimize_positions(measured_edges_real, len(tiles_real))
min_y = min(p[0] for p in opt_real.values()); min_x = min(p[1] for p in opt_real.values())
opt_real = {k: (v[0] - min_y, v[1] - min_x) for k, v in opt_real.items()}

fig, axes = plt.subplots(1, 2, figsize=(12, 5))
for ax, positions, title in zip(axes, [true_positions, opt_real], ["True grid positions", "Optimised positions"]):
    for idx, (py, px) in positions.items():
        r, c = idx // GRID, idx % GRID
        rect = mpatches.FancyBboxPatch(
            (px / SX, py / SY), 0.9, 0.9,
            boxstyle="round,pad=0.03", linewidth=1.2, edgecolor="steelblue",
            facecolor=plt.cm.tab10(idx / 9), alpha=0.5
        )
        ax.add_patch(rect)
        ax.text(px / SX + 0.45, py / SY + 0.45, f"{r},{c}", ha="center", va="center", fontsize=9)
    ax.set_xlim(-0.3, GRID + 0.3); ax.set_ylim(-0.3, GRID + 0.3)
    ax.set_aspect("equal"); ax.invert_yaxis(); ax.set_title(title, fontsize=11)

plt.suptitle("Grid positions (normalised to tile steps)", fontsize=12)
plt.tight_layout()
plt.show()

print("Correction applied (optimised − true), px:")
for idx in sorted(true_positions):
    dy = opt_real[idx][0] - true_positions[idx][0]
    dx = opt_real[idx][1] - true_positions[idx][1]
    print(f"  Tile {idx}: Δy={dy:+.1f}  Δx={dx:+.1f}")
