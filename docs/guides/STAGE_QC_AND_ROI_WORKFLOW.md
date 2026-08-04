# Stage QC and ROI workflow

This workflow adds three safeguards before scaling the mCherry longitudinal analysis:

1. Metadata-only XY stage-coordinate prefiltering before pixel registration.
2. A combined automated QC report for stage and registration checks.
3. First-pass ROI-restricted mCherry quantification for columns `05-07`.

It uses fluorescence mCherry-valid wells only. Rows `C/D/G/H/K/L` are not interpreted for mCherry puncta/diffusion because they lack mCherry by design.

## Stage prefilter

Future longitudinal runs now check ND2 stage coordinates before loading pixel arrays. The runner uses XY distance by default and keeps Z only as review metadata because these ND2s mix relative and absolute Z conventions across acquisition days.

Run the standalone prefilter on already processed pilot wells:

```bash
python scripts/build_mcherry_stage_prefilter.py
```

Local outputs:

```text
LOCAL_PROCESSED_OUTPUT/pilot/stage_prefilter/
  mcherry_stage_prefilter.csv
  mcherry_stage_prefilter_summary.csv
```

Current result: all `54` current well/day observations pass the `5 um` XY stage threshold. Stage targeting therefore does not explain the large registration shifts seen in some days.

## Automated QC report

Run:

```bash
python scripts/build_mcherry_qc_report.py
```

Local outputs:

```text
LOCAL_PROCESSED_OUTPUT/pilot/mcherry_qc_report/
  mcherry_longitudinal_qc_report.csv
  mcherry_longitudinal_qc_report.md
```

Current result:

- Observations reviewed: `54`
- Included observations: `39`
- Excluded observations: `15`
- Exclusion reason: `registration_large_shift`

The QC report includes condition, well, column, day, registration shift, stage XY distance, included/excluded status, and exclusion reason.

After writing the QC report, regenerate plots from the passing observations:

```bash
python scripts/plot_mcherry_pilot_analysis.py
```

The plotting script uses `mcherry_longitudinal_qc_report.csv` when present, so its QC-filtered figures match the report.

## ROI-restricted mCherry quantification

Run:

```bash
python scripts/run_mcherry_roi_pilot.py --columns 05 06 07
```

This reads existing registered common-overlap pilot stacks one at a time. It does not read or convert the full ND2 dataset.

Local outputs:

```text
LOCAL_PROCESSED_OUTPUT/pilot/mcherry_roi_quantification/
  mcherry_full_frame_vs_roi_metrics.csv
  mcherry_full_frame_vs_roi_condition_summary.csv
  mcherry_full_frame_vs_roi_condition_summary_qc_passing.csv
  mcherry_full_frame_vs_roi_score_scatter.png
  mcherry_full_frame_vs_roi_condition_summary.png
  mcherry_roi_minus_full_frame_delta.png
  mcherry_roi_interpretation.md
```

The ROI mask is a conservative thresholded 561 nm foreground mask. It is useful as a first-pass way to reduce empty-background influence, but it is not a validated neuron or lysosome segmentation.

QC-passing Day 25 summary:

| Condition | n wells | Full-frame diffuse/punctate | ROI diffuse/punctate | ROI area fraction |
|---|---:|---:|---:|---:|
| PLD3 + mCherry | 6 | 0.059 | 0.135 | 0.072 |
| PLD3 + TMEM106B + mCherry | 3 | 0.153 | 0.237 | 0.064 |

The ROI-restricted score remains higher in the primary condition at Day 25. This is a preliminary image-analysis signal only and does not establish lysosomal rupture.

## Scaling guidance

- Do not run new columns until the stage prefilter and QC report are generated for the current pilot.
- Treat registration-large-shift observations as excluded until visual review says otherwise.
- Continue using 488 nm for registration and 561 nm for mCherry phenotype quantification.
- Keep outputs outside Git. Do not commit ND2, TIFF, PNG, Zarr, or generated microscopy outputs.
