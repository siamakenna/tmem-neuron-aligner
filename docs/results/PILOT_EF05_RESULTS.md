# E05/F05 mCherry Pilot Results

This pilot is a preliminary image-level screen from one fluorescence frame per well. It is not a stitched whole-well result, not a registered neuron ROI, and not a longitudinal conclusion.

## Inputs

- Raw root: `LOCAL_RAW_DATA`
- Day/acquisition folder: `20260305_171612_406`
- Reporter-control well: `E05`, PLD3 + mCherry
- Primary experimental well: `F05`, PLD3 + TMEM106B + mCherry
- Channel: index `1`, `561nm Binned`
- Read pattern: one indexed `YX` plane per ND2, via lazy Dask-backed ND2 reading

## Local Outputs

These generated image/result files are intentionally outside Git:

```text
LOCAL_INTERIM_OUTPUT/pilot/ef05_mcherry/
  260305_day25_WellE05_ch1_preview.ome.tif
  260305_day25_WellF05_ch1_preview.ome.tif

LOCAL_PROCESSED_OUTPUT/pilot/ef05_mcherry/
  ef05_mcherry_pilot_metrics.csv
  ef05_mcherry_pilot_metadata.json
  ef05_mcherry_pilot_summary.png
```

## Preliminary Metrics

| well | condition | puncta_count | punctate_mean | diffuse_mean | rupture_like_score |
|---|---|---:|---:|---:|---:|
| E05 | PLD3_mCherry_reporter_control | 1110 | 129.961 | 9.127 | 0.070 |
| F05 | PLD3_TMEM106B_mCherry_primary | 1072 | 44.138 | 8.173 | 0.185 |

In this one-frame pilot, F05 has a higher diffuse-to-punctate mean ratio than E05, but this should be treated only as a smoke test of the workflow. The next scientific step is to repeat on matched E/F-phase wells across multiple days after whole-well and neuron ROI registration.

## Reproduce

From the repo root:

```bash
source .venv/bin/activate
python scripts/run_ef05_mcherry_pilot.py
```

Do not run full-dataset conversion. Keep using indexed ND2 reads and small pilot outputs until the channel mapping, well mapping, and ROI strategy are confirmed.
