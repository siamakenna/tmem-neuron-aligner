# E05/F05 Longitudinal Comparison

This comparison combines two same-well longitudinal pilots:

- `E05`: PLD3 + mCherry reporter-control well
- `F05`: PLD3 + TMEM106B + mCherry primary experimental well

Both wells use Day 8, Day 25, and Day 39 fluorescence ND2 files. Each well is aligned to its own Day 8 reference before mCherry metrics are compared. The wells are not registered to each other.

## Local Outputs

Generated comparison outputs are intentionally outside Git:

```text
LOCAL_PROCESSED_OUTPUT/pilot/ef05_longitudinal_comparison/
  E05_F05_days_day8_day25_day39_comparison_metrics.csv
  E05_F05_days_day8_day25_day39_comparison_summary.png
```

## Preliminary Comparison

| well | condition | day | puncta_count | punctate_mean | diffuse_mean | rupture_like_score |
|---|---|---:|---:|---:|---:|---:|
| E05 | PLD3 + mCherry | 8 | 1305 | 193.578 | 8.816 | 0.046 |
| E05 | PLD3 + mCherry | 25 | 1048 | 126.674 | 5.922 | 0.047 |
| E05 | PLD3 + mCherry | 39 | 1037 | 213.505 | 7.278 | 0.034 |
| F05 | PLD3 + TMEM106B + mCherry | 8 | 868 | 139.287 | 8.751 | 0.063 |
| F05 | PLD3 + TMEM106B + mCherry | 25 | 816 | 48.802 | 8.287 | 0.170 |
| F05 | PLD3 + TMEM106B + mCherry | 39 | 934 | 71.397 | 6.391 | 0.090 |

In this pilot, the E05 reporter-control well remains low on the diffuse-to-punctate score across the three days. F05 has a higher score at Day 25 and remains above E05 at Day 39. This is a useful workflow signal, but not proof of lysosomal rupture or causality.

## Registration QC

E05 registration shifts were subpixel across the selected days. F05 Day 25 required a large horizontal shift (`dx=921 px`), so F05 Day 25 must be visually reviewed in the registered stack before scaling this workflow.

## Reproduce

From the repo root:

```bash
source .venv/bin/activate
python scripts/run_f05_longitudinal_pilot.py --well E05
python scripts/run_f05_longitudinal_pilot.py --well F05
python scripts/compare_ef05_longitudinal.py
```

Next, repeat this matched same-well workflow for more E/I/M reporter-control wells and F/J/N primary wells, then move to neuron ROI selection inside the registered stacks.
