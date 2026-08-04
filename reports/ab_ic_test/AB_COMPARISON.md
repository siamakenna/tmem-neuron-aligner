# A/B: Illumination Correction in the Longitudinal Pilot

**Date:** 2026-07-10 · **Wells:** E05 (control), F05 (primary) · **Days:** 8, 12, 16
**Script:** `scripts/run_260213_longitudinal_pilot.py` with/without `--illumination-correct`
**Arms:** `baseline/` (no IC) vs `ic/` (per-timepoint flatfield, seeded 25% sample, flatfield only — no darkfield/bg)

## Why we tested instead of just turning it on

IC flatfield-corrects the 561/mCherry channel, which changes the actual measurement
(intensities, Otsu threshold, puncta/diffuse ratio). Turning it on blind would (a) alter the
biological readout on an assumption and (b) forfeit the reproduction baseline that matches the
original run to floating point. Two questions to answer with data:

1. Does IC change/stabilize **registration**? (predicted: no — phase cross-correlation works in
   the frequency domain and is robust to smooth low-frequency illumination gradients)
2. Does IC change the **mCherry metrics** in a defensible direction (cross-FOV fairness), and does
   it preserve the E-vs-F effect?

## Results

### Registration — negligible change (as predicted)
Shifts identical to ±0.1 px; post-registration correlation and overlap fraction differ only in the
4th–5th decimal. 6/6 QC pass in both arms. IC provides **no registration benefit** here.

### mCherry metrics — small per-timepoint, but effect size moves
Per-timepoint changes (IC vs baseline): diffuse/punctate ratio within **±3%**, puncta count within
**±2%** (a handful of puncta), diffuse mean intensity within **±5%**.

Headline longitudinal contrast:

| metric | baseline | IC | change |
|---|---|---|---|
| E05 slope (diffuse/punctate per day) | 0.0598 | 0.0712 | **+19%** |
| F05 slope | 0.1455 | 0.1396 | −4% |
| **F05/E05 slope ratio (effect size)** | **2.43** | **1.96** | **−19%** |

The E-vs-F direction is preserved (F05 still ~2× steeper), but IC **compressed the effect size by
~19%**, almost entirely by raising the *control* slope.

## Interpretation

- **Registration:** IC is unnecessary for alignment — leave it out of the registration path.
- **Quantification:** IC is *not free* — it moved the headline control-vs-experimental contrast by
  ~19% from a preprocessing choice alone. The direction (control diffuse signal rising) is
  *consistent with* IC recovering vignetted edge signal, but this pilot has **no ground truth**, so
  we cannot claim IC is more accurate — only that it materially changes the answer.
- **Scope caveat:** this tested flatfield only. Darkfield subtraction (the larger correctness item)
  was **not** exercised by `--illumination-correct` and remains unvalidated.

## Decision

**Keep IC off by default.** Do not fold it into the reproduction baseline. The flag now exists for
opt-in experiments. Before trusting IC's effect on the biology, validate against ground truth
(uniform fluorescent reference / flat-field slide, or a spike-in) — a single-well A/B on real
neurons cannot separate "recovered signal" from "added artifact."

## Reproduce

```bash
DATA=/Users/pmihack/claire/tmem_2026/data/260213_Feb16recopy_HYdiff_landingpadlines_survival_384well1
python scripts/run_260213_longitudinal_pilot.py --data-root "$DATA" \
  --output reports/ab_ic_test/baseline --control-well E05 --experimental-well F05 --max-timepoints 3
python scripts/run_260213_longitudinal_pilot.py --data-root "$DATA" \
  --output reports/ab_ic_test/ic --control-well E05 --experimental-well F05 --max-timepoints 3 \
  --illumination-correct
```

Compare `*/registration_qc.csv` and `*/mcherry_measurements.csv`. IC fields are seeded (`seed=0`),
so the IC arm is reproducible run-to-run.
