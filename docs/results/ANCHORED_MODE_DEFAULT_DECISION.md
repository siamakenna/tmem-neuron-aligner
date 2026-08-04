# Anchored Mode Default Decision

**Date:** 2026-07-22  
**Branch:** `feat/alignment-method-comparison`  
**Commit:** `e32b251`

## Decision

**Option A: flip default to `anchored`, keep `--plate-correct` opt-in.**

- `scripts/run_260213_all_wells_batch.py` `parse_args()` `--ref-mode` default changed from `to_first` → `anchored`
- `--plate-correct` remains opt-in (doubles runtime, no QC improvement over anchored alone at plate scale)

## Evidence

### Run A — anchored only

192 wells × 9 days. **192/192 QC pass** at all timepoints (vs `to_first`: 2 failures at days 20 and 39).

Output: `reports/260213_all_wells_anchored/`

### Run B — anchored + plate-correct

Same plate, same days, with `--plate-correct` (Kabsch fit pre-pass).

Output: `reports/260213_all_wells_plate_corrected/`

Plate events detected at days 25/32/36/39, but rms = 9–133 px at late days (wells do not move as a clean rigid body at full plate scale). No QC-pass improvement over Run A. Plate correction **reduces** day 25+ D:P ratios by ~26% — likely overcorrection from a poor rigid fit. Anchored re-anchors per-well and handles the plate remount without the spurious global prior.

### Canonical anchored run

192 wells × 9 days, `--ref-mode anchored`.

Output: `reports/260213_all_wells_anchored_final/`

### Biology impact vs committed `to_first` results (`reports/260213_all_wells_all_days/`)

| Days | Change | Interpretation |
|------|--------|---------------|
| 8–29 | ±7% | Unchanged conclusions |
| 32 | primary +4%, delta 2.21 vs 2.08 | Marginal improvement |
| 36 | primary +8%, delta 2.33 vs 2.09 | Modest improvement |
| **39** | **primary +23.4%, delta 2.82 vs 1.84** | **Anchored strengthens TMEM signal — `to_first` was underestimating due to registration failures at high-drift wells** |

## Conclusion

Anchored mode is strictly better: 192/192 QC pass vs 190/192, and late-timepoint mCherry ratios are more accurate (higher, not lower — `to_first` was failing silently on high-drift wells and underreporting the TMEM effect). The day-39 TMEM excess delta increases from 1.84 to 2.82 (+53%).

Plate correction adds complexity and runtime without benefit at this plate scale. Keep opt-in for cases where a known remount must be corrected and per-well anchoring is insufficient.
