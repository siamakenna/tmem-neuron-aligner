#!/usr/bin/env python
from __future__ import annotations

import os
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import tifffile as tif
from scipy.ndimage import gaussian_filter

from tmem_align.analysis.mcherry_metrics import quantify_mcherry_timeseries
from tmem_align.register import apply_shift, register_translation


def main() -> None:
    output = Path("reports/synthetic_smoketest")
    output.mkdir(parents=True, exist_ok=True)
    figures = output / "figures"
    figures.mkdir(exist_ok=True)

    stack, known_shifts = make_synthetic_stack()
    registered = [stack[0]]
    rows = []
    for time_index in range(stack.shape[0]):
        if time_index == 0:
            recovered = (0.0, 0.0)
        else:
            _, recovered, _ = register_translation(stack[0, 0], stack[time_index, 0], upsample_factor=20)
            registered.append(apply_shift(stack[time_index], *recovered))
        rows.append(
            {
                "time_index": time_index,
                "known_dy": known_shifts[time_index][0],
                "known_dx": known_shifts[time_index][1],
                "recovered_dy": recovered[0],
                "recovered_dx": recovered[1],
                "shift_error_pixels": float(
                    np.hypot(recovered[0] + known_shifts[time_index][0], recovered[1] + known_shifts[time_index][1])
                ),
            }
        )
    registered_stack = np.stack(registered, axis=0)
    metrics = quantify_mcherry_timeseries(
        registered_stack[:, 1],
        mask_stack=registered_stack[:, 0],
        metadata_rows=[{"timepoint": f"synthetic_day_{i + 1}"} for i in range(registered_stack.shape[0])],
    )
    pd.DataFrame(rows).to_csv(output / "registration_recovery.csv", index=False)
    metrics.to_csv(output / "synthetic_mcherry_metrics.csv", index=False)
    tif.imwrite(output / "synthetic_registered_tcyx.ome.tif", registered_stack.astype(np.float32), metadata={"axes": "TCYX"}, ome=True)
    write_montage(stack, registered_stack, figures / "synthetic_alignment_montage.png")
    print(f"Wrote synthetic smoke test outputs under {output}")
    print(pd.DataFrame(rows).to_string(index=False))


def make_synthetic_stack() -> tuple[np.ndarray, list[tuple[float, float]]]:
    rng = np.random.default_rng(7)
    y, x = np.mgrid[:160, :160]
    stable = np.zeros((160, 160), dtype=np.float32)
    for cy, cx, amp, sigma in [(48, 52, 1.0, 11), (92, 110, 0.9, 14), (120, 48, 0.7, 9)]:
        stable += amp * np.exp(-(((y - cy) ** 2 + (x - cx) ** 2) / (2 * sigma**2)))
    stable += 0.08 * rng.normal(size=stable.shape)
    stable = gaussian_filter(stable, 0.8)

    shifts = [(0.0, 0.0), (4.3, -6.2), (-5.8, 7.5)]
    frames = []
    for t, shift in enumerate(shifts):
        mcherry = 0.12 * stable + (0.05 + 0.08 * t)
        puncta_amp = 1.0 - 0.28 * t
        for cy, cx in [(46, 55), (94, 105), (118, 50), (78, 70)]:
            mcherry += puncta_amp * np.exp(-(((y - cy) ** 2 + (x - cx) ** 2) / (2 * 2.2**2)))
        mcherry += 0.03 * rng.normal(size=mcherry.shape)
        cyx = np.stack([stable, mcherry], axis=0)
        frames.append(apply_shift(cyx, *shift))
    return np.stack(frames, axis=0), shifts


def write_montage(raw: np.ndarray, registered: np.ndarray, path: Path) -> None:
    fig, axes = plt.subplots(2, raw.shape[0], figsize=(9, 5), constrained_layout=True)
    for idx in range(raw.shape[0]):
        axes[0, idx].imshow(raw[idx, 0], cmap="gray")
        axes[0, idx].set_title(f"Raw t{idx}")
        axes[1, idx].imshow(registered[idx, 1], cmap="magma")
        axes[1, idx].set_title(f"Aligned mCherry t{idx}")
    for ax in axes.ravel():
        ax.set_axis_off()
    fig.savefig(path, dpi=180)
    plt.close(fig)


if __name__ == "__main__":
    main()

