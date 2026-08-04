#!/usr/bin/env python
"""Render mCherry segmentation mask overlays on pilot registered stacks (E05/F05, days 8/12/16)."""
from __future__ import annotations

import os
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")

import matplotlib.pyplot as plt
import numpy as np
import tifffile as tif
from matplotlib.patches import Patch

from tmem_align.analysis.mcherry_metrics import background_subtract, detect_puncta, foreground_mask

STACKS_DIR = Path("reports/260213_pilot_reproduced/registered_stacks")
OUT = Path("reports/260213_pilot_reproduced/figures/mask_segmentation_overlays.png")

WELLS = ["E05", "F05"]
WELL_LABELS = {"E05": "E05 (mCherry control)", "F05": "F05 (TMEM106B + mCherry)"}
DAYS = [8, 12, 16]
MCHERRY_CH = 1
STABLE_CH = 2


def _overlay_rgb(img: np.ndarray, fg: np.ndarray, puncta: np.ndarray) -> np.ndarray:
    """Gray image with green diffuse foreground and red puncta tint."""
    vmin, vmax = np.percentile(img, [2, 98])
    normed = np.clip((img.astype(float) - vmin) / (vmax - vmin + 1e-9), 0, 1)
    rgb = np.stack([normed, normed, normed], axis=-1)
    diffuse = fg & ~puncta
    rgb[diffuse] = rgb[diffuse] * 0.4 + np.array([0.0, 0.5, 0.0])
    rgb[puncta] = rgb[puncta] * 0.4 + np.array([0.6, 0.0, 0.0])
    return np.clip(rgb, 0, 1)


def main() -> None:
    fig, axes = plt.subplots(len(WELLS), len(DAYS), figsize=(13, 9))

    for row_i, well in enumerate(WELLS):
        stack = np.asarray(tif.imread(STACKS_DIR / f"{well}_registered_common_overlap_tcyx.ome.tif"))
        n_time = stack.shape[0]

        for col_j, (day, t) in enumerate(zip(DAYS, range(n_time))):
            mcherry = stack[t, MCHERRY_CH].astype(np.float32)
            stable = stack[t, STABLE_CH].astype(np.float32)

            corrected = background_subtract(mcherry)
            fg = foreground_mask(stable)
            puncta = detect_puncta(corrected, fg)

            rgb = _overlay_rgb(corrected, fg, puncta)
            ax = axes[row_i, col_j]
            ax.imshow(rgb, interpolation="nearest")
            ax.set_title(f"{WELL_LABELS[well]}\nday {day}", fontsize=8)
            ax.axis("off")

    legend_handles = [
        Patch(facecolor=(0.0, 0.5, 0.0), label="diffuse foreground"),
        Patch(facecolor=(0.6, 0.0, 0.0), label="puncta"),
        Patch(facecolor=(0.5, 0.5, 0.5), label="background"),
    ]
    fig.legend(handles=legend_handles, loc="lower center", ncol=3, fontsize=9, bbox_to_anchor=(0.5, 0))
    fig.suptitle("mCherry segmentation masks — pilot wells (days 8, 12, 16)", fontsize=12)
    fig.tight_layout(rect=[0, 0.06, 1, 1])

    OUT.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT, dpi=150)
    print(f"Saved: {OUT}")


if __name__ == "__main__":
    main()
