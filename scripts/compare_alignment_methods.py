#!/usr/bin/env python
"""Synthetic head-to-head of the two registration paths, over a random sample of wells.

Both paths call the same engine (register.register_translation); they differ only in how
they drive it. We reproduce each path's *settings* and sweep them on synthetic fixtures with
KNOWN ground-truth shifts, so accuracy is an objective number (|estimated - true|), not a
proxy. Each experiment is now run over N randomly-generated "wells" (randomized morphology,
shifts, illumination, noise) so results aggregate across a sample instead of one hand-tuned
frame. See ALIGNMENT_COMPARISON_PLAN.md.

Ground truth is always the STABLE-morphology shift — what registration is supposed to
recover. In E3 the stable channel is static (truth = 0) while mCherry moves, so any nonzero
estimate = the method chasing the phenotype channel.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from tmem_align.register import apply_shift, register_translation
from tmem_align.registration_qc import (
    classify_registration_qc,
    common_overlap_crop,
    correlation,
    overlap_fraction,
)

OUT = Path("reports/alignment_comparison")
N = 192  # frame size
PASS_PX = 2.0  # a well "passes" a method if mean shift error < this

# The three methods = one knob-ablation of the shared engine.
#   A_cli           reproduces the CLI  (register_file_to_reference): max-projects all
#                   channels (io.normalize_to_2d), clip+blur, subpixel upsample=10.
#   B_pilot         reproduces the pilot (register_stack): stable channel only, masked
#                   phase-corr on raw signal, integer-pixel.
#   stable_subpixel ablation control: stable channel, no preprocessing, subpixel.
METHODS = {
    "A_cli": dict(reduce="maxproj", kwargs=dict(robust_preprocess=True, upsample_factor=10)),
    "B_pilot": dict(reduce="stable", kwargs=dict(robust_preprocess=False, mask_percentile=20.0)),
    "stable_subpixel": dict(
        reduce="stable", kwargs=dict(robust_preprocess=False, upsample_factor=20)
    ),
}
# NOTE: stable_subpixel looks best on the synthetic fixtures E1-E5, but real-data validation
# (validate_alignment_real.py on C05/E05/F05) REFUTES that: without masking it fails like A_cli
# (post-corr ~0.004 vs B_pilot ~0.16). The masking is the essential ingredient. E1-E5 are too
# clean to expose this; E6 (decorrelation) is the only synthetic fixture that hints at it.

# Anchored-mode sweep: fixed-stride re-anchoring (corr trigger disabled via -1) and
# correlation-triggered re-anchoring (stride disabled via 0). See Anchored Registration Mode Plan.
ANCHOR_CONFIGS = [
    ("stride2", dict(anchor_stride=2, anchor_corr_thresh=-1.0)),
    ("stride3", dict(anchor_stride=3, anchor_corr_thresh=-1.0)),
    ("stride4", dict(anchor_stride=4, anchor_corr_thresh=-1.0)),
    ("corr0.3", dict(anchor_stride=0, anchor_corr_thresh=0.3)),
    ("corr0.5", dict(anchor_stride=0, anchor_corr_thresh=0.5)),
    ("corr0.7", dict(anchor_stride=0, anchor_corr_thresh=0.7)),
]


def blob(y, x, cy, cx, amp, sigma):
    return amp * np.exp(-(((y - cy) ** 2 + (x - cx) ** 2) / (2.0 * sigma**2)))


def _grid():
    return np.mgrid[:N, :N]


def _random_shifts(rng, n_t, scale):
    return [(0.0, 0.0)] + [
        (float(rng.uniform(-scale, scale)), float(rng.uniform(-scale, scale)))
        for _ in range(n_t - 1)
    ]


def _drift_shifts(rng, n_t):
    """Roughly monotonic stage drift with jitter."""
    shifts = [(0.0, 0.0)]
    dy = dx = 0.0
    for _ in range(1, n_t):
        dy += float(rng.uniform(2.0, 4.5))
        dx -= float(rng.uniform(1.5, 3.5))
        shifts.append((dy, dx))
    return shifts


# --- fixtures: each returns (stack[T,2,Y,X], stable_shifts) for one randomized well --------


def make_e1_baseline(rng, n_t):
    """Dense-ish morphology, random subpixel-ish shifts. Tests subpixel accuracy."""
    y, x = _grid()
    stable = np.zeros((N, N), np.float32)
    for _ in range(rng.integers(3, 6)):
        stable += blob(y, x, rng.uniform(40, 152), rng.uniform(40, 152), rng.uniform(0.7, 1.0),
                       rng.uniform(10, 17))
    stable += 0.06 * rng.normal(size=stable.shape)
    shifts = _random_shifts(rng, n_t, scale=8.0)
    return _apply_same(stable, stable * 0.15, shifts), shifts


def make_e2_sparse(rng, n_t):
    """Sparse point-like neurons MOVING under a STATIC illumination field — the faithful
    axis-lock case (vignette is fixed to the scope, not the sample). clip+blur can lock onto
    the static illumination and under-report the shift; masked-on-raw tracks the points."""
    y, x = _grid()
    illum = (rng.uniform(0.5, 0.8) * (x / N) + rng.uniform(0.2, 0.4) * (y / N)).astype(np.float32)
    pts = [(rng.uniform(40, 152), rng.uniform(40, 152)) for _ in range(rng.integers(3, 6))]
    shifts = _random_shifts(rng, n_t, scale=8.0)
    frames = []
    for dy, dx in shifts:
        signal = np.zeros((N, N), np.float32)
        for cy, cx in pts:
            signal += blob(y, x, cy + dy, cx + dx, 0.6, 2.0)
        stable = illum + signal + 0.02 * rng.normal(size=illum.shape)
        frames.append(np.stack([stable, signal * 0.3], axis=0))
    return np.stack(frames, axis=0), shifts


def make_e3_mcherry(rng, n_t):
    """Stable channel STATIC; mCherry blobs MOVE (random walk). Decisive test of the
    'never register on mCherry' rule. Ground-truth stable shift = 0 at every t."""
    y, x = _grid()
    stable = np.zeros((N, N), np.float32)
    for _ in range(rng.integers(2, 4)):
        stable += blob(y, x, rng.uniform(50, 142), rng.uniform(50, 142), 0.4, rng.uniform(15, 20))
    pts = [(rng.uniform(50, 142), rng.uniform(50, 142)) for _ in range(rng.integers(2, 4))]
    mch_shifts = _random_shifts(rng, n_t, scale=8.0)
    frames = []
    for dy, dx in mch_shifts:
        mch = np.zeros((N, N), np.float32)
        for cy, cx in pts:
            mch += blob(y, x, cy + dy, cx + dx, 1.0, 3.0)
        frames.append(np.stack([stable, mch], axis=0))
    return np.stack(frames, axis=0), [(0.0, 0.0)] * n_t


def make_e4_gradient(rng, n_t):
    """Weak reference signal under a strong (shifting-with-sample) illumination gradient."""
    y, x = _grid()
    gradient = rng.uniform(0.4, 0.7) * ((x + y) / (2 * N))
    stable = gradient.astype(np.float32).copy()
    for _ in range(rng.integers(2, 4)):
        stable += blob(y, x, rng.uniform(50, 142), rng.uniform(50, 142), 0.35, rng.uniform(5, 8))
    stable += 0.04 * rng.normal(size=stable.shape)
    shifts = _random_shifts(rng, n_t, scale=6.0)
    return _apply_same(stable, stable * 0.2, shifts), shifts


def make_e5_drift(rng, n_t):
    """Cumulative multi-timepoint drift. Feeds the common-overlap-crop analysis."""
    y, x = _grid()
    stable = np.zeros((N, N), np.float32)
    for _ in range(rng.integers(3, 6)):
        stable += blob(y, x, rng.uniform(40, 152), rng.uniform(40, 152), rng.uniform(0.7, 1.0),
                       rng.uniform(10, 15))
    stable += 0.05 * rng.normal(size=stable.shape)
    shifts = _drift_shifts(rng, n_t)
    return _apply_same(stable, stable * 0.15, shifts), shifts


def make_e6_decorrelation(rng, n_t):
    """Large drift + PROGRESSIVE morphology change — the realistic month-long case where t0
    and t9 look different (features drift, brighten/fade, turn over) even though adjacent
    days stay similar. This is the regime where sequential (to-previous) registration is
    hypothesized to help. Ground truth = the applied global rigid drift; the evolving
    morphology is decorrelation on top of it."""
    y, x = _grid()
    blobs = [[rng.uniform(50, 142), rng.uniform(50, 142), rng.uniform(0.6, 1.0), rng.uniform(9, 14)]
             for _ in range(4)]
    shifts = _drift_shifts(rng, n_t)
    frames = []
    for t, (dy, dx) in enumerate(shifts):
        if t > 0:  # evolve the morphology one step
            for b in blobs:
                b[0] += rng.normal(0, 2.0)
                b[1] += rng.normal(0, 2.0)
                b[2] *= rng.uniform(0.9, 1.05)
            if rng.random() < 0.4:  # occasional feature turnover
                blobs.append([rng.uniform(50, 142), rng.uniform(50, 142),
                              rng.uniform(0.4, 0.8), rng.uniform(8, 12)])
        stable = np.zeros((N, N), np.float32)
        for cy, cx, amp, s in blobs:
            stable += blob(y, x, cy, cx, amp, s)
        stable += 0.05 * rng.normal(size=stable.shape)
        frames.append(apply_shift(np.stack([stable, stable * 0.15], axis=0), dy, dx))
    return np.stack(frames, axis=0), shifts


def _apply_same(stable2d, mcherry2d, shifts):
    frames = [apply_shift(np.stack([stable2d, mcherry2d], axis=0), dy, dx) for dy, dx in shifts]
    return np.stack(frames, axis=0)


def reduce_frame(frame_cyx, mode):
    return frame_cyx.max(axis=0) if mode == "maxproj" else frame_cyx[0]


EXPERIMENTS = {
    "E1_baseline": make_e1_baseline,
    "E2_sparse": make_e2_sparse,
    "E3_mcherry": make_e3_mcherry,
    "E4_gradient": make_e4_gradient,
    "E5_drift": make_e5_drift,
    "E6_decorrelation": make_e6_decorrelation,
}


# --- runner -------------------------------------------------------------------------------


def run_method(stack, stable_shifts, method_name, ref_mode="to_first",
               anchor_corr_thresh=0.5, anchor_stride=0):
    """ref_mode:
      'to_first'    register every t to t0 (independent, no accumulation).
      'to_previous' register t to t-1, compose to net-shift-to-t0 (accumulates error).
      'anchored'    register t to the current anchor; when correlation to the anchor drops
                    below anchor_corr_thresh (or every anchor_stride frames), promote the last
                    good frame to be the new anchor. Bounds accumulation to a few hops while
                    keeping the reference similar. Never anchors on the current frame."""
    spec = METHODS[method_name]
    ref0 = reduce_frame(stack[0], spec["reduce"])
    prev = ref0                    # to_previous: reduce(stack[t-1])
    net_dy = net_dx = 0.0          # to_previous: running net
    anchor_img = ref0              # anchored: current reference
    anchor_net = (0.0, 0.0)        # anchored: net shift of the anchor back to t0
    last_good_img = ref0           # anchored: most recent frame that passed (eligible anchor)
    last_good_net = (0.0, 0.0)
    last_anchor_t = 0
    rows = []
    for t in range(stack.shape[0]):
        true_dy, true_dx = stable_shifts[t]
        if t == 0:
            dy = dx = 0.0
            err = 0.0
            post = 1.0
        elif ref_mode == "to_first":
            mov = reduce_frame(stack[t], spec["reduce"])
            aligned, (dy, dx), err = register_translation(ref0, mov, **spec["kwargs"])
            post = correlation(ref0, aligned)
        elif ref_mode == "to_previous":  # compose pairwise shifts into a net shift-to-t0
            mov = reduce_frame(stack[t], spec["reduce"])
            _, (pdy, pdx), err = register_translation(prev, mov, **spec["kwargs"])
            net_dy += pdy
            net_dx += pdx
            dy, dx = net_dy, net_dx
            post = correlation(ref0, apply_shift(mov, dy, dx))
            prev = mov
        else:  # anchored
            mov = reduce_frame(stack[t], spec["reduce"])
            aligned, (pdy, pdx), err = register_translation(anchor_img, mov, **spec["kwargs"])
            post = correlation(anchor_img, aligned)
            reanchor = (post < anchor_corr_thresh) or (
                anchor_stride and (t - last_anchor_t) >= anchor_stride)
            if reanchor and t >= 2:  # promote the last GOOD frame — never the current one
                anchor_img, anchor_net = last_good_img, last_good_net
                last_anchor_t = t
                aligned, (pdy, pdx), err = register_translation(anchor_img, mov, **spec["kwargs"])
                post = correlation(anchor_img, aligned)
            dy = anchor_net[0] + pdy
            dx = anchor_net[1] + pdx
            if post >= anchor_corr_thresh:  # trustworthy → eligible as a future anchor
                last_good_img, last_good_net = mov, (dy, dx)
        overlap = overlap_fraction(ref0.shape, (dy, dx))
        qc = classify_registration_qc(
            overlap, dy, dx, ref0.shape[0], ref0.shape[1], post_correlation=post
        )
        rows.append(
            {
                "method": method_name,
                "ref_mode": ref_mode,
                "timepoint": t,
                "true_dy": true_dy,
                "true_dx": true_dx,
                "est_dy": dy,
                "est_dx": dx,
                "abs_err_px": float(np.hypot(dy + true_dy, dx + true_dx)),  # est ~= -true
                "post_corr": post,
                "reg_error": float(err),
                "overlap": overlap,
                "qc_pass": bool(qc["qc_pass"]),
            }
        )
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--n-wells", type=int, default=10, help="number of randomly-drawn wells")
    ap.add_argument("--n-timepoints", type=int, default=9, help="timepoints per well")
    ap.add_argument("--seed", type=int, default=2026, help="master seed for the well sample")
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "montages").mkdir(exist_ok=True)

    master = np.random.default_rng(args.seed)
    well_seeds = master.integers(0, 2**31 - 1, size=args.n_wells)
    print(f"Randomly selected {args.n_wells} wells (seed={args.seed}, {args.n_timepoints} timepoints)")

    all_rows = []
    crop_rows = []
    e3_example = e5_example = None
    for w, wseed in enumerate(well_seeds):
        for exp_name, gen in EXPERIMENTS.items():
            stack, shifts = gen(np.random.default_rng(int(wseed)), args.n_timepoints)
            for method in METHODS:
                for ref_mode in ("to_first", "to_previous"):
                    method_rows = run_method(stack, shifts, method, ref_mode)
                    for r in method_rows:
                        all_rows.append({"experiment": exp_name, "well": w, **r})
                    # E5: common-overlap crop from Path B's to_first shifts, per well.
                    if exp_name == "E5_drift" and method == "B_pilot" and ref_mode == "to_first":
                        b_shifts = [(r["est_dy"], r["est_dx"]) for r in method_rows]
                        crop = common_overlap_crop(stack.shape[-2:], b_shifts, robust=True)
                        area = ((crop["y_stop"] - crop["y_start"])
                                * (crop["x_stop"] - crop["x_start"]) / (N * N))
                        crop_rows.append({"well": w, **crop, "area_retained": area})
                        if w == 0:
                            e5_example = (stack, crop)
            if exp_name == "E3_mcherry" and w == 0:
                e3_example = stack

    df = pd.DataFrame(all_rows)
    df.to_csv(OUT / "synthetic_accuracy.csv", index=False)
    pd.DataFrame(crop_rows).to_csv(OUT / "e5_common_overlap_crop.csv", index=False)

    # Anchored-mode sweep (Anchored Registration Mode Plan). Deterministic well seeds → same
    # stacks as above, so anchored is compared on identical data.
    anchor_rows = []
    for w, wseed in enumerate(well_seeds):
        for exp_name, gen in EXPERIMENTS.items():
            stack, shifts = gen(np.random.default_rng(int(wseed)), args.n_timepoints)
            for method in METHODS:
                for cfg_name, cfg in ANCHOR_CONFIGS:
                    for r in run_method(stack, shifts, method, "anchored", **cfg):
                        anchor_rows.append(
                            {"experiment": exp_name, "well": w, "config": cfg_name, **r}
                        )
    adf = pd.DataFrame(anchor_rows)
    adf.to_csv(OUT / "anchored_mode_sweep.csv", index=False)

    _summary_table(df)
    print(f"\nE5 common-overlap crop: mean area retained = "
          f"{np.mean([r['area_retained'] for r in crop_rows]):.3f} across {len(crop_rows)} wells")
    _mode_comparison(df)
    _anchored_report(df, adf)
    _decisive_figures(e3_example, e5_example, df)
    _self_check(df, adf)
    print(f"\nWrote {OUT}/synthetic_accuracy.csv and figures under {OUT}/montages/")


def _per_well_err(df, ref_mode="to_first"):
    """Mean abs error per (experiment, well, method) over registered timepoints (t>0),
    for one reference mode (default to_first — the mode both shipped paths use)."""
    d = df[(df.timepoint > 0) & (df.ref_mode == ref_mode)]
    return d.groupby(["experiment", "well", "method"])["abs_err_px"].mean()


def _anchored_median(adf):
    """Median-across-wells err per (experiment, config, method)."""
    return (
        adf[adf.timepoint > 0]
        .groupby(["experiment", "config", "well", "method"])["abs_err_px"]
        .mean()
        .groupby(level=["experiment", "config", "method"])
        .median()
    )


def _anchored_report(df, adf):
    """Compare anchored configs against the to_first baseline on the regimes that matter:
    E1 (no-harm), E5 (drift), E6 (decorrelation). Success = beats to_first on E6 without
    hurting E1/E5. Writes a tidy delta CSV and prints the verdict per method."""
    base = _per_well_err(df, "to_first").groupby(level=["experiment", "method"]).median()
    anc = _anchored_median(adf)
    print("\n=== Anchored sweep — median err (px) vs to_first (Anchored Registration Mode Plan) ===")
    delta_rows = []
    for exp in ("E1_baseline", "E5_drift", "E6_decorrelation"):
        print(f"\n{exp}:")
        for method in METHODS:
            b = base[exp, method]
            best_cfg = min(ANCHOR_CONFIGS, key=lambda c: anc[exp, c[0], method])[0]
            best = anc[exp, best_cfg, method]
            cfgs = "  ".join(f"{c}={anc[exp, c, method]:.2f}" for c, _ in ANCHOR_CONFIGS)
            flag = "  <-- beats to_first" if best < b - 0.3 else ""
            print(f"  {method:16s} to_first={b:.2f} | {cfgs} | best={best_cfg}{flag}")
            for c, _ in ANCHOR_CONFIGS:
                delta_rows.append({"experiment": exp, "method": method, "config": c,
                                   "to_first": round(float(b), 3),
                                   "anchored": round(float(anc[exp, c, method]), 3),
                                   "delta_anchored_minus_first": round(float(anc[exp, c, method] - b), 3)})
    pd.DataFrame(delta_rows).to_csv(OUT / "anchored_vs_first.csv", index=False)


def _mode_comparison(df):
    """to_first vs to_previous, median across wells. delta>0 => to_previous is WORSE."""
    pw = (
        df[df.timepoint > 0]
        .groupby(["experiment", "ref_mode", "well", "method"])["abs_err_px"]
        .mean()
        .reset_index()
    )
    med = (
        pw.groupby(["experiment", "method", "ref_mode"])["abs_err_px"]
        .median()
        .unstack("ref_mode")
    )
    med["delta_prev_minus_first"] = med["to_previous"] - med["to_first"]
    print("\nReference mode — median err (px). delta>0 = to_previous WORSE than to_first:")
    print(med.round(3).to_string())
    med.round(4).to_csv(OUT / "reference_mode_comparison.csv")


def _summary_table(df):
    pw = _per_well_err(df).reset_index()
    agg = pw.groupby(["experiment", "method"]).agg(
        median_err=("abs_err_px", "median"),
        p90_err=("abs_err_px", lambda s: float(np.percentile(s, 90))),
        pass_rate=("abs_err_px", lambda s: float((s < PASS_PX).mean())),
    )
    print("\nAcross wells — median shift error (px) [lower better]:")
    print(agg["median_err"].unstack("method").round(3).to_string())
    print("\nAcross wells — fraction of wells passing (mean err < "
          f"{PASS_PX}px) [higher better]:")
    print(agg["pass_rate"].unstack("method").round(2).to_string())
    agg.round(4).to_csv(OUT / "synthetic_accuracy_summary.csv")


def _decisive_figures(e3_stack, e5_example, df):
    if e3_stack is not None:
        fig, ax = plt.subplots(1, 3, figsize=(11, 4), constrained_layout=True)
        ax[0].imshow(e3_stack[1, 0], cmap="gray")
        ax[0].set_title("Stable channel (static)\nwhat B_pilot sees")
        ax[1].imshow(e3_stack[1].max(axis=0), cmap="gray")
        ax[1].set_title("max-projection\nwhat A_cli sees (mCherry leaks in)")
        ax[2].imshow(e3_stack[1, 1], cmap="magma")
        ax[2].set_title("mCherry (moved)")
        e3 = _per_well_err(df).reset_index()
        e3 = e3[e3.experiment == "E3_mcherry"].groupby("method")["abs_err_px"].median()
        fig.suptitle("E3 — stable static; nonzero shift = chasing mCherry.  median err: "
                     + ", ".join(f"{m}={e3[m]:.1f}px" for m in METHODS))
        for a in ax:
            a.set_axis_off()
        fig.savefig(OUT / "montages" / "e3_mcherry_leak.png", dpi=150)
        plt.close(fig)

    if e5_example is not None:
        stack, crop = e5_example
        fig, ax = plt.subplots(1, 1, figsize=(5, 5))
        ax.imshow(stack[-1, 0], cmap="gray")
        ax.add_patch(plt.Rectangle(
            (crop["x_start"], crop["y_start"]),
            crop["x_stop"] - crop["x_start"], crop["y_stop"] - crop["y_start"],
            edgecolor="cyan", facecolor="none", lw=2))
        ax.set_title("E5 common-overlap crop (Path B only)")
        ax.set_axis_off()
        fig.savefig(OUT / "montages" / "e5_overlap_crop.png", dpi=150)
        plt.close(fig)


def _self_check(df, adf=None):
    """Encode the plan's hypotheses as runnable asserts, using medians across wells so one
    unlucky random well can't flip the result. Data is already written first."""
    med = _per_well_err(df).groupby(level=["experiment", "method"]).median()

    assert med["E1_baseline", "stable_subpixel"] < med["E1_baseline", "B_pilot"], (
        "E1: expected subpixel to beat integer-pixel masked path"
    )
    a3, b3 = med["E3_mcherry", "A_cli"], med["E3_mcherry", "B_pilot"]
    assert a3 > b3 + 2.0, f"E3: expected A_cli to chase mCherry (A={a3:.2f} vs B={b3:.2f})"
    assert b3 < 1.5, f"E3: expected B_pilot to ignore mCherry (err={b3:.2f})"
    a2, b2 = med["E2_sparse", "A_cli"], med["E2_sparse", "B_pilot"]
    assert a2 > b2 + 2.0, f"E2: expected A_cli to lock onto static illumination (A={a2:.2f})"

    # Sequential (to-previous) accumulates pairwise error → worse than to-first on plain drift.
    mode = df[df.timepoint > 0].groupby(
        ["experiment", "ref_mode", "method"]
    )["abs_err_px"].median()
    assert mode["E5_drift", "to_previous", "B_pilot"] > mode["E5_drift", "to_first", "B_pilot"], (
        "expected sequential accumulation to hurt on E5 drift"
    )

    if adf is not None:
        anc = _anchored_median(adf)
        # Anchored earns its place ONLY if it beats to_first on E6 for the masked path...
        base6 = med["E6_decorrelation", "B_pilot"]
        best6 = min(anc["E6_decorrelation", c, "B_pilot"] for c, _ in ANCHOR_CONFIGS)
        assert best6 < base6 - 0.3, (
            f"anchored should beat to_first on E6 masked path (got {best6:.2f} vs {base6:.2f})"
        )
        # ...without hurting the clean baseline.
        base1 = med["E1_baseline", "B_pilot"]
        best1 = min(anc["E1_baseline", c, "B_pilot"] for c, _ in ANCHOR_CONFIGS)
        assert best1 <= base1 + 0.05, (
            f"anchored should not hurt E1 baseline (got {best1:.2f} vs {base1:.2f})"
        )
    print("\nself-check: PASS (subpixel tradeoff + mCherry leak + illumination lock + "
          "sequential accumulation + anchored-helps-masked-on-decorrelation reproduced)")


if __name__ == "__main__":
    main()
