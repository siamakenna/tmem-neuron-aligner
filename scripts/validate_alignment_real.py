#!/usr/bin/env python
"""Real-data validation of the two registration paths — judge alignment by eye.

There is no ground-truth shift on real images, so this does NOT report accuracy. It runs
both paths on the same real wells and reports what CAN be checked objectively — the shift
each path estimates, the post-registration correlation, and side-by-side before/after
montages — plus where the two paths DISAGREE (the mCherry-leak / illumination-lock signature
found synthetically). Use a no-mCherry well (e.g. C05) as a control: the paths should agree
there; on mCherry wells (E05/F05) A_cli may chase the phenotype channel. See
ALIGNMENT_COMPARISON_PLAN.md and the Alignment Method Comparison note.

Reuses the pilot's ND2 loaders (scripts/run_260213_longitudinal_pilot.py). Needs the [nd2]
extra and the real data root.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from tmem_align.register import apply_shift, register_translation
from tmem_align.registration_qc import correlation, overlap_fraction

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_260213_longitudinal_pilot as pilot  # noqa: E402  (reuse loaders)

OUT = Path("reports/alignment_comparison/real_data")

# The two shipped paths + the ablation control, driven on real multi-channel stacks.
METHODS = {
    "A_cli": dict(reduce="maxproj", kwargs=dict(robust_preprocess=True, upsample_factor=10)),
    "B_pilot": dict(reduce="stable", kwargs=dict(robust_preprocess=False, mask_percentile=20.0)),
    # ablation: stable channel + subpixel, NO clip/blur, NO mask — does it hold up on real data?
    "stable_subpixel": dict(reduce="stable", kwargs=dict(robust_preprocess=False, upsample_factor=20)),
}


def build_stack(files, max_sites, max_read_bytes):
    """Stack a well's timepoints into TCYX; return (stack, channel_names, days)."""
    frames, days, channel_names = [], [], None
    for item in files:
        loaded = pilot.load_nd2_cyx(item["path"], max_sites, max_read_bytes)
        frames.append(loaded["array"])
        channel_names = loaded["channel_names"]
        days.append(item["day"])
    shapes = {f.shape for f in frames}
    if len(shapes) > 1:  # crop to common Y/X if a timepoint differs (rare)
        min_y = min(f.shape[-2] for f in frames)
        min_x = min(f.shape[-1] for f in frames)
        frames = [f[..., :min_y, :min_x] for f in frames]
    return np.stack(frames, axis=0), channel_names, days


def reduce_real(frame_cyx, mode, stable_idx):
    return frame_cyx.max(axis=0) if mode == "maxproj" else frame_cyx[stable_idx]


def run(stack, stable_idx, method):
    spec = METHODS[method]
    ref = reduce_real(stack[0], spec["reduce"], stable_idx)
    rows, shifts = [], []
    for t in range(stack.shape[0]):
        if t == 0:
            dy = dx = 0.0
            post = 1.0
        else:
            mov = reduce_real(stack[t], spec["reduce"], stable_idx)
            aligned, (dy, dx), _ = register_translation(ref, mov, **spec["kwargs"])
            post = correlation(ref, aligned)
        shifts.append((dy, dx))
        rows.append(
            {"method": method, "t": t, "dy": dy, "dx": dx, "post_corr": post,
             "overlap": overlap_fraction(ref.shape, (dy, dx))}
        )
    return rows, shifts


def montage(stack, stable_idx, shifts_by_method, well, days, path):
    """Rows: raw stable | A_cli-aligned stable | B_pilot-aligned stable. Cols: timepoints."""
    t_n = stack.shape[0]
    methods = list(shifts_by_method)
    fig, ax = plt.subplots(1 + len(methods), t_n, figsize=(2.2 * t_n, 2.2 * (1 + len(methods))),
                           constrained_layout=True, squeeze=False)
    vmax = np.percentile(stack[:, stable_idx], 99)
    for t in range(t_n):
        ax[0, t].imshow(stack[t, stable_idx], cmap="gray", vmax=vmax)
        ax[0, t].set_title(f"raw d{days[t]}", fontsize=8)
    for r, method in enumerate(methods, start=1):
        for t in range(t_n):
            dy, dx = shifts_by_method[method][t]
            aligned = apply_shift(stack[t, stable_idx], dy, dx)
            ax[r, t].imshow(aligned, cmap="gray", vmax=vmax)
            ax[r, t].set_title(f"{method} ({dy:.1f},{dx:.1f})", fontsize=8)
    for a in ax.ravel():
        a.set_axis_off()
    fig.suptitle(f"Well {well} — stable channel, raw vs aligned (eyeball drift/centering)")
    fig.savefig(path, dpi=110)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-root", type=Path, required=True,
                    help="the experiment folder containing the ND2 timepoint subfolders")
    ap.add_argument("--wells", nargs="+", default=["C05", "E05", "F05"],
                    help="include a no-mCherry well (C/D/G...) as an A==B control")
    ap.add_argument("--max-timepoints", type=int, default=4)
    ap.add_argument("--max-sites", type=int, default=1)
    ap.add_argument("--max-read-bytes", type=int, default=2 * 1024**3)
    ap.add_argument("--stable-channel", default="488", help="reference (morphology) channel")
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    selected = pilot.select_pilot_files(args.data_root, args.wells, max_timepoints=args.max_timepoints)

    all_rows, disagree = [], []
    for well, files in selected.items():
        if not files:
            print(f"WARN {well}: no ND2 files found — skipping")
            continue
        stack, channel_names, days = build_stack(files, args.max_sites, args.max_read_bytes)
        stable_idx = pilot.choose_channel_index(channel_names, args.stable_channel)
        has_mcherry = pilot.condition_for_well(well)
        print(f"{well} ({has_mcherry}): {stack.shape[0]} timepoints, channels={channel_names}, "
              f"stable_idx={stable_idx}")
        shifts_by_method = {}
        for method in METHODS:
            rows, shifts = run(stack, stable_idx, method)
            shifts_by_method[method] = shifts
            for r in rows:
                all_rows.append({"well": well, "condition": has_mcherry, "day": days[r["t"]], **r})
        # A-vs-B disagreement per timepoint = the leak/lock signature.
        for t in range(stack.shape[0]):
            ad, bd = shifts_by_method["A_cli"][t], shifts_by_method["B_pilot"][t]
            disagree.append({"well": well, "condition": has_mcherry, "day": days[t],
                             "shift_disagreement_px": float(np.hypot(ad[0] - bd[0], ad[1] - bd[1]))})
        montage(stack, stable_idx, shifts_by_method, well, days, OUT / f"{well}_montage.png")

    df = pd.DataFrame(all_rows)
    dis = pd.DataFrame(disagree)
    df.to_csv(OUT / "real_registration_shifts.csv", index=False)
    dis.to_csv(OUT / "real_ab_disagreement.csv", index=False)

    print("\n=== A_cli vs B_pilot shift disagreement (px) — high on mCherry wells = leak ===")
    print(dis.groupby(["well", "condition"])["shift_disagreement_px"].max().round(1).to_string())
    print("\n=== post-registration correlation by method (real values → calibrate QC threshold) ===")
    print(df[df.t > 0].groupby("method")["post_corr"].describe()[["min", "50%", "max"]].round(4).to_string())
    print(f"\nWrote CSVs + montages under {OUT}/  — review the montages by eye.")


if __name__ == "__main__":
    main()
