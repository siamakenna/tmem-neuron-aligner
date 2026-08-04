# Alignment method comparison — how to reproduce

Evidence for which registration path in this pipeline to trust. Full writeup lives in Obsidian:
`03_contexts/2026_tmem/Alignment Investigation Report.md` and `Alignment Method Comparison.md`.
Branch: `feat/alignment-method-comparison`.

## Environment

From the repo root:

```bash
source .venv/bin/activate     # .venv has the [nd2,dev] extras
```

The synthetic step needs only numpy/scipy/skimage/matplotlib/pandas. The real-data step also
needs the `[nd2]` extra and access to the ND2 images.

## 1. Synthetic experiments (self-contained — no image data needed)

```bash
python scripts/compare_alignment_methods.py                 # 10 wells x 9 timepoints, seed 2026
python scripts/compare_alignment_methods.py --n-wells 20 --seed 7 --n-timepoints 9   # resample
```

Deterministic (fixed master seed → fixed well sample). It compares three engine configs
(`A_cli`, `B_pilot`, `stable_subpixel`) across six fixtures (E1–E6), sweeps reference mode
(`to_first` / `to_previous` / `anchored`), and prints median error + pass-rate tables. The
built-in `_self_check` asserts the headline findings — a **non-zero exit means a finding
regressed**. Writes to `reports/alignment_comparison/` (see Outputs).

## 2. Real-data validation (needs the ND2 data)

```bash
python scripts/validate_alignment_real.py \
  --data-root /Users/pmihack/claire/tmem_2026/data/260213_Feb16recopy_HYdiff_landingpadlines_survival_384well1 \
  --wells C05 E05 F05 --max-timepoints 3
```

`--data-root` is the experiment folder holding the ND2 timepoint subfolders. Include a
no-mCherry well (C/D/G/K rows) as an A==B control alongside mCherry wells (E/F/I/J/M/N). No
ground truth on real images — it reports shift, post-registration correlation, A-vs-B
disagreement, and before/after montages to judge by eye. Reuses the loaders in
`scripts/run_260213_longitudinal_pilot.py`. Writes to `reports/alignment_comparison/real_data/`.

## Outputs

| File | Contents |
|------|----------|
| `synthetic_accuracy.csv` | Per-timepoint error, all wells/methods/ref-modes |
| `synthetic_accuracy_summary.csv` | Median error + pass-rate by experiment/method |
| `reference_mode_comparison.csv` | to_first vs to_previous |
| `anchored_mode_sweep.csv` / `anchored_vs_first.csv` | Anchored stride/corr sweep + deltas |
| `e5_common_overlap_crop.csv` | Common-overlap crop area retained |
| `montages/e3_mcherry_leak.png`, `montages/e5_overlap_crop.png` | Synthetic diagnostics |
| `real_data/real_registration_shifts.csv` | Real per-timepoint shifts + post-corr, both paths |
| `real_data/real_ab_disagreement.csv` | A-vs-B disagreement per well |
| `real_data/{C05,E05,F05}_montage.png` | Raw vs A_cli-aligned vs B_pilot-aligned |

## Headline result

`A_cli` (the CLI path) axis-locks to 500–1400 px garbage on real data (post-corr ~0.005);
`B_pilot` (the pilot masked path) gives coherent drift (post-corr ~0.16). **Use the pilot
masked path.** See the linked notes for the full findings and next steps.
```
