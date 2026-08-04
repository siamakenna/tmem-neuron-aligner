#!/usr/bin/env python3
"""Generate a 384-well plate layout graphic for biologist verification."""

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from pathlib import Path

ROWS = list("CDEFGHIJKLMN")
COLS = [f"{c:02d}" for c in range(5, 21)]

ROW_CONDITIONS = {
    "C": ("PLD3 only", "no mCherry"),
    "D": ("PLD3 + TMEM106B", "no mCherry"),
    "E": ("PLD3 + mCherry", "reporter control"),
    "F": ("PLD3 + TMEM106B + mCherry", "primary experimental"),
    "G": ("PLD3 only", "no mCherry"),
    "H": ("PLD3 + TMEM106B", "no mCherry"),
    "I": ("PLD3 + mCherry", "reporter control"),
    "J": ("PLD3 + TMEM106B + mCherry", "primary experimental"),
    "K": ("PLD3 only", "no mCherry"),
    "L": ("PLD3 + TMEM106B", "no mCherry"),
    "M": ("PLD3 + mCherry", "reporter control"),
    "N": ("PLD3 + TMEM106B + mCherry", "primary experimental"),
}

CONDITION_COLORS = {
    "PLD3 only":                  "#bfbfbf",  # gray — no reporter
    "PLD3 + TMEM106B":            "#a8c8e8",  # light blue — no reporter
    "PLD3 + mCherry":             "#f5c242",  # gold — mCherry control
    "PLD3 + TMEM106B + mCherry":  "#e05555",  # red — primary experimental
}

PILOT_WELLS = {"E05", "F05", "I05", "J05", "M05", "N05"}

fig, ax = plt.subplots(figsize=(14, 7.5))
fig.patch.set_facecolor("white")

well_radius = 0.38

for r, row in enumerate(ROWS):
    cond_label, _ = ROW_CONDITIONS[row]
    color = CONDITION_COLORS[cond_label]
    for c, col in enumerate(COLS):
        well_id = f"{row}{col}"
        circle = plt.Circle((c, -r), well_radius, facecolor=color,
                             edgecolor="#333333", linewidth=0.8)
        ax.add_patch(circle)

        if well_id in PILOT_WELLS:
            pilot_ring = plt.Circle((c, -r), well_radius + 0.06,
                                     facecolor="none", edgecolor="#1a1a1a",
                                     linewidth=2.5)
            ax.add_patch(pilot_ring)
            ax.text(c, -r, "P", ha="center", va="center",
                    fontsize=7, fontweight="bold", color="#1a1a1a")

# Row labels (left)
for r, row in enumerate(ROWS):
    ax.text(-0.8, -r, row, ha="center", va="center",
            fontsize=11, fontweight="bold", color="#333333")

# Column labels (top)
for c, col in enumerate(COLS):
    ax.text(c, 1.0, col, ha="center", va="center",
            fontsize=9, fontweight="bold", color="#333333")

# Condition annotations (right side) — one per cycle row
cycle_labels = [
    (0, "C", "PLD3 only — no mCherry"),
    (1, "D", "PLD3 + TMEM106B — no mCherry"),
    (2, "E", "PLD3 + mCherry — reporter control"),
    (3, "F", "PLD3 + TMEM106B + mCherry — experimental"),
]
for offset, letter, label in cycle_labels:
    cond = ROW_CONDITIONS[letter][0]
    color = CONDITION_COLORS[cond]
    y = -offset
    ax.plot(len(COLS) + 0.3, y, "s", color=color, markersize=10,
            markeredgecolor="#333333", markeredgewidth=0.8)
    ax.text(len(COLS) + 0.7, y, label, ha="left", va="center",
            fontsize=9, color="#333333")

# Bracket showing the 4-row cycle repeats
for cycle_start in [0, 4, 8]:
    y_top = -cycle_start + 0.5
    y_bot = -(cycle_start + 3) - 0.5
    x = -1.5
    ax.plot([x, x], [y_top, y_bot], color="#888888", linewidth=1.2)
    ax.plot([x, x + 0.15], [y_top, y_top], color="#888888", linewidth=1.2)
    ax.plot([x, x + 0.15], [y_bot, y_bot], color="#888888", linewidth=1.2)
    ax.text(x - 0.15, (y_top + y_bot) / 2, f"replicate {cycle_start // 4 + 1}",
            ha="center", va="center", fontsize=8, color="#888888", rotation=90)

# Title and subtitle
ax.text((len(COLS) - 1) / 2, 2.4,
        "Plate 260213 — well layout",
        ha="center", va="center", fontsize=14, fontweight="bold", color="#1a1a1a")
ax.text((len(COLS) - 1) / 2, 1.8,
        "384-well plate  ·  rows C–N, columns 05–20 (192 active wells)"
        "  ·  4-row condition cycle × 3 replicates",
        ha="center", va="center", fontsize=9.5, color="#555555")

# Pilot well legend
pilot_patch = mpatches.FancyBboxPatch((0, 0), 1, 1, boxstyle="round,pad=0.1",
                                       facecolor="none", edgecolor="#1a1a1a",
                                       linewidth=2.5)
ax.text((len(COLS) - 1) / 2, -12.8,
        "P  = pilot wells (column 05):  E05/F05  ·  I05/J05  ·  M05/N05"
        "   —   3 control/experimental pairs, one per cycle",
        ha="center", va="center", fontsize=9, color="#333333")

# mCherry validity note
ax.text((len(COLS) - 1) / 2, -13.6,
        "mCherry quantification valid only for rows E/F, I/J, M/N (gold + red wells)"
        "  ·  rows C/D, G/H, K/L are registration-only",
        ha="center", va="center", fontsize=8.5, color="#666666", style="italic")

ax.set_xlim(-2.2, len(COLS) + 9.5)
ax.set_ylim(-14.5, 3.2)
ax.set_aspect("equal")
ax.axis("off")

out = Path(__file__).resolve().parent.parent / "outputs" / "plate_layout_verification.png"
out.parent.mkdir(exist_ok=True)
fig.savefig(out, dpi=180, bbox_inches="tight", facecolor="white")
print(f"Saved: {out}")
plt.close()
