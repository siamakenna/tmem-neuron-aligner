#!/usr/bin/env python
"""Color-coded temporal overlay of a well across days — see how cells move vs day 0.

Each timepoint's stable (morphology) channel is tinted a distinct color and additively
overlaid: where cells sit in the same place every day the colors sum to white; where they
drift you see colored fringes. Shown RAW (physical drift) and AFTER registration (B_pilot
masked path — cells should lock together). A third panel plots each day's estimated shift
relative to day 0 as a colored trajectory (the literal "shift between days").

Reuses the pilot ND2 loaders. Needs the [nd2] extra and the real data.
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

from tmem_align.register import apply_shift, register_translation
from tmem_align.registration_qc import correlation

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_260213_longitudinal_pilot as pilot  # noqa: E402

OUT = Path("reports/alignment_comparison/real_data/day_overlays")


def _masked(ref, mov):
    """Masked phase-correlation (the pilot/B_pilot path). Returns (aligned, (dy, dx))."""
    aligned, (dy, dx), _ = register_translation(
        ref, mov, robust_preprocess=False, mask_percentile=20.0
    )
    return aligned, (dy, dx)


def register_to_first(stable):
    """Register every day to day 0 (current pipeline behavior)."""
    ref = stable[0]
    shifts, post, reg = [(0.0, 0.0)], [1.0], [stable[0]]
    for s in stable[1:]:
        aligned, (dy, dx) = _masked(ref, s)
        shifts.append((dy, dx))
        post.append(correlation(ref, aligned))
        reg.append(aligned)
    return shifts, post, reg


def register_anchored(stable, thresh):
    """Anchored: register to the current anchor; when correlation to it drops below `thresh`,
    re-anchor to the last good frame (never the current one) and re-register. Net shift back to
    day 0 is composed across anchor hops."""
    anchor, anchor_net = stable[0], (0.0, 0.0)
    last_good_img, last_good_net = stable[0], (0.0, 0.0)
    shifts, post, reg, reanchored = [(0.0, 0.0)], [1.0], [stable[0]], [False]
    for t in range(1, len(stable)):
        mov = stable[t]
        aligned, (pdy, pdx) = _masked(anchor, mov)
        p = correlation(anchor, aligned)
        did = False
        if p < thresh and t >= 2:
            anchor, anchor_net = last_good_img, last_good_net
            aligned, (pdy, pdx) = _masked(anchor, mov)
            p = correlation(anchor, aligned)
            did = True
        net = (anchor_net[0] + pdy, anchor_net[1] + pdx)
        shifts.append(net)
        post.append(p)
        reg.append(apply_shift(mov, *net))
        reanchored.append(did)
        if p >= thresh:  # trustworthy → eligible future anchor
            last_good_img, last_good_net = mov, net
    return shifts, post, reg, reanchored


def norm(frame, scale):
    """Percentile-normalize a 2D frame to ~[0,1] with a scale so a few days saturate to white."""
    lo, hi = np.percentile(frame, [1, 99])
    if hi <= lo:
        return np.zeros_like(frame, dtype=np.float32)
    return np.clip(scale * (frame.astype(np.float32) - lo) / (hi - lo), 0, 1)


def composite(frames, colors):
    """Additive RGB overlay: sum(day_image * day_color), clipped."""
    rgb = np.zeros((*frames[0].shape, 3), dtype=np.float32)
    for img, c in zip(frames, colors):
        rgb += img[..., None] * np.asarray(c[:3], dtype=np.float32)
    return np.clip(rgb, 0, 1)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-root", type=Path, required=True)
    ap.add_argument("--wells", nargs="+", default=["E05", "F05"])
    ap.add_argument("--max-timepoints", type=int, default=6)
    ap.add_argument("--max-sites", type=int, default=1)
    ap.add_argument("--max-read-bytes", type=int, default=2 * 1024**3)
    ap.add_argument("--stable-channel", default="488")
    ap.add_argument("--scale", type=float, default=1.4, help="brightness scale for the overlay")
    ap.add_argument("--anchor-corr-thresh", type=float, default=0.10,
                    help="re-anchor when correlation to the current anchor drops below this. "
                         "Calibrated on 260213 real data (good ~0.15, garbage ~0.005): 0.10-0.12 "
                         "recovers all late timepoints to post-corr >=0.19; 0.07 leaves day39 partial.")
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    selected = pilot.select_pilot_files(args.data_root, args.wells, max_timepoints=args.max_timepoints)

    for well, files in selected.items():
        if not files:
            print(f"WARN {well}: no ND2 files — skipping")
            continue
        days = [f["day"] for f in files]
        stable = []
        for f in files:
            loaded = pilot.load_nd2_cyx(f["path"], args.max_sites, args.max_read_bytes)
            idx = pilot.choose_channel_index(loaded["channel_names"], args.stable_channel)
            stable.append(loaded["array"][idx])
        # crop to common shape if needed
        min_y = min(s.shape[0] for s in stable)
        min_x = min(s.shape[1] for s in stable)
        stable = [s[:min_y, :min_x] for s in stable]

        colors = plt.cm.turbo(np.linspace(0.05, 0.95, len(days)))

        sf, pf, regf = register_to_first(stable)
        sa, pa, rega, ra = register_anchored(stable, args.anchor_corr_thresh)

        raw_n = [norm(s, args.scale) for s in stable]
        first_n = [norm(s, args.scale) for s in regf]
        anch_n = [norm(s, args.scale) for s in rega]

        fig, ax = plt.subplots(1, 4, figsize=(22, 5.6), constrained_layout=True)
        ax[0].imshow(composite(raw_n, colors))
        ax[0].set_title(f"{well} — RAW (physical drift)")
        ax[1].imshow(composite(first_n, colors))
        ax[1].set_title(f"{well} — to-first registered")
        ax[2].imshow(composite(anch_n, colors))
        ax[2].set_title(f"{well} — anchored registered")
        for a in ax[:3]:
            a.set_axis_off()

        # trajectory: to-first (circles) vs anchored (squares), colored by day.
        # recovered shift ~= -(applied); negate so arrows point the way cells moved.
        for shifts_set, marker, dashes in ((sf, "o", (None, None)), (sa, "s", (4, 2))):
            xs = [-dx for _, dx in shifts_set]
            ys = [-dy for dy, _ in shifts_set]
            ax[3].plot(xs, ys, color="0.7", lw=0.8, zorder=1, dashes=dashes)
            for i, (x, y) in enumerate(zip(xs, ys)):
                ax[3].scatter(x, y, color=colors[i], s=70, marker=marker, zorder=2,
                              edgecolor="k", linewidth=0.3)
        ax[3].scatter(0, 0, marker="*", s=180, color=colors[0], edgecolor="k", zorder=3)
        ax[3].set_title(f"{well} — shift vs day {days[0]} (o=to-first, □=anchored)")
        ax[3].set_xlabel("x shift (px)")
        ax[3].set_ylabel("y shift (px)")
        ax[3].invert_yaxis()
        ax[3].axhline(0, color="0.9", lw=0.5)
        ax[3].axvline(0, color="0.9", lw=0.5)
        ax[3].grid(True, alpha=0.2)

        sm = plt.cm.ScalarMappable(cmap="turbo", norm=plt.Normalize(days[0], days[-1]))
        fig.colorbar(sm, ax=ax[2], fraction=0.046, pad=0.02, label="day")

        out = OUT / f"{well}_day_overlay.png"
        fig.savefig(out, dpi=130)
        plt.close(fig)

        # per-day comparison table: does anchored recover the late days?
        print(f"\n=== {well} — to-first vs anchored (masked; re-anchor thresh "
              f"{args.anchor_corr_thresh}) ===")
        print(f"{'day':>4} {'first_px':>9} {'first_corr':>10} {'anch_px':>8} "
              f"{'anch_corr':>9} {'reanchored':>10}")
        for i, d in enumerate(days):
            fmag = np.hypot(*sf[i])
            amag = np.hypot(*sa[i])
            print(f"{d:>4} {fmag:>9.0f} {pf[i]:>10.3f} {amag:>8.0f} {pa[i]:>9.3f} "
                  f"{'YES' if ra[i] else '':>10}")
        print(f"net drift day{days[0]}->day{days[-1]}: to-first={np.hypot(*sf[-1]):.0f} px, "
              f"anchored={np.hypot(*sa[-1]):.0f} px -> {out}")


if __name__ == "__main__":
    main()
