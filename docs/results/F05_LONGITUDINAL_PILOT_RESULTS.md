# F05 Longitudinal Pilot Results

This pilot follows the main experimental direction: align the same well across days and preserve channels in a scrollable time stack. It is still preliminary because it uses one well and three days only, and the selected ND2 files expose one `CYX` frame per day rather than a tile-position axis for true stitching.

## Inputs

- Well: `F05`
- Condition: PLD3 + TMEM106B + mCherry
- Days: `8`, `25`, `39`
- Raw root: `LOCAL_RAW_DATA`
- Channels: `405nm Binned`, `561nm Binned`, `488nm Binned`
- Registration channel: index `2`, `488nm Binned`
- Phenotype channel: index `1`, `561nm Binned`
- File axes for these pilot ND2s: `CYX`

## Local Outputs

Generated outputs are intentionally outside Git:

```text
LOCAL_INTERIM_OUTPUT/pilot/f05_longitudinal/
  F05_days_day8_day25_day39_raw_tcyx.ome.tif
  F05_days_day8_day25_day39_registered_tcyx.ome.tif
  F05_days_day8_day25_day39_registered_common_overlap_tcyx.ome.tif

LOCAL_PROCESSED_OUTPUT/pilot/f05_longitudinal/
  F05_days_day8_day25_day39_mcherry_metrics.csv
  F05_days_day8_day25_day39_registration_shifts.csv
  F05_days_day8_day25_day39_metadata.json
  F05_days_day8_day25_day39_mcherry_summary.png
```

The `registered_tcyx.ome.tif` file is the scrollable channel-preserved time stack. The `registered_common_overlap_tcyx.ome.tif` file crops away black registration borders and is used for the pilot quantification.

## Registration Shifts

| day | dy | dx |
|---:|---:|---:|
| 8 | 0.0 | 0.0 |
| 25 | -1.0 | 921.0 |
| 39 | -0.2 | 0.1 |

The Day 25 shift is large, so the shared crop is `y=0:2867`, `x=921:2868`. This should be visually reviewed before scaling to more wells/days.

## Preliminary mCherry Metrics

These metrics are from the common-overlap registered stack, not the full bordered registered stack.

| day | puncta_count | punctate_mean | diffuse_mean | rupture_like_score |
|---:|---:|---:|---:|---:|
| 8 | 868 | 139.287 | 8.751 | 0.063 |
| 25 | 816 | 48.802 | 8.287 | 0.170 |
| 39 | 934 | 71.397 | 6.391 | 0.090 |

The Day 25 frame has the highest diffuse-to-punctate score in this pilot. Treat this as a workflow signal only, not evidence of lysosomal rupture by itself. Stronger rupture validation would require orthogonal markers or controls such as Galectin-3/Galectin-8, LysoTracker loss, LAMP1/LAMP2 changes, p62/LC3 changes, or LLOMe positive controls.

## Reproduce

From the repo root:

```bash
source .venv/bin/activate
python scripts/run_f05_longitudinal_pilot.py
```

The next scale-up should process the same well across adjacent days first, then add matched E/I/M-phase reporter controls and additional F/J/N-phase primary wells.
