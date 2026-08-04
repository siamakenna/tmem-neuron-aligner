# mCherry graphical pilot analysis

This note summarizes the current local graphical analysis of mCherry puncta and diffusion metrics. It uses fluorescence files only, and only wells with mCherry:

- Reporter controls: `E`, `I`, `M` rows (`PLD3 + mCherry`)
- Primary condition: `F`, `J`, `N` rows (`PLD3 + TMEM106B + mCherry`)

Rows without mCherry are excluded from puncta/diffusion interpretation. Missing mCherry in `C/D/G/H/K/L` rows is not treated as zero puncta.

## Current processed subset

The current expanded pilot includes three columns of matched replicate wells:

- Column 05: `E05/F05`, `I05/J05`, `M05/N05`
- Column 06: `E06/F06`, `I06/J06`, `M06/N06`
- Column 07: `E07/F07`, `I07/J07`, `M07/N07`
- Days: `8`, `25`, `39`
- Registration channel: `488nm Binned`, channel index `2`
- mCherry phenotype channel: `561nm Binned`, channel index `1`

This is still a pilot. It is not a full-plate analysis and not proof of lysosomal rupture.

## Graphical outputs

Generated figures and tables are local outputs outside Git:

```text
LOCAL_PROCESSED_OUTPUT/pilot/mcherry_graphical_analysis/
  combined_mcherry_metrics.csv
  condition_day_summary.csv
  condition_day_summary_qc_passing.csv
  paired_primary_minus_control_delta.csv
  paired_primary_minus_control_delta_qc_passing.csv
  mcherry_metric_trajectories.png
  mcherry_metric_trajectories_qc_passing.png
  mcherry_condition_mean_sem.png
  mcherry_condition_mean_sem_qc_passing.png
  mcherry_primary_minus_control_delta.png
  mcherry_primary_minus_control_delta_qc_passing.png
  mcherry_puncta_diffuse_scatter.png
  mcherry_puncta_diffuse_scatter_qc_passing.png
```

The most useful starting figure is:

```text
LOCAL_PROCESSED_OUTPUT/pilot/mcherry_graphical_analysis/mcherry_condition_mean_sem_qc_passing.png
```

The most useful lab-review QC report is:

```text
LOCAL_PROCESSED_OUTPUT/pilot/mcherry_qc_report/mcherry_longitudinal_qc_report.md
```

## Current condition means

Raw mean values across the 9 processed reporter-control wells and 9 processed primary wells:

| Condition | Day | n wells | Puncta count | Punctate mean | Diffuse mean | Diffuse / punctate |
|---|---:|---:|---:|---:|---:|---:|
| PLD3 + mCherry | 8 | 9 | 757.8 | 191.7 | 8.74 | 0.046 |
| PLD3 + mCherry | 25 | 9 | 594.3 | 131.3 | 7.69 | 0.059 |
| PLD3 + mCherry | 39 | 9 | 722.4 | 213.1 | 8.33 | 0.039 |
| PLD3 + TMEM106B + mCherry | 8 | 9 | 865.0 | 136.5 | 8.78 | 0.064 |
| PLD3 + TMEM106B + mCherry | 25 | 9 | 722.7 | 44.8 | 7.43 | 0.166 |
| PLD3 + TMEM106B + mCherry | 39 | 9 | 867.4 | 70.7 | 6.89 | 0.097 |

QC-passing mean values after excluding large-shift observations:

| Condition | Day | n wells | Puncta count | Punctate mean | Diffuse mean | Diffuse / punctate |
|---|---:|---:|---:|---:|---:|---:|
| PLD3 + mCherry | 8 | 9 | 757.8 | 191.7 | 8.74 | 0.046 |
| PLD3 + mCherry | 25 | 6 | 723.3 | 128.8 | 7.62 | 0.059 |
| PLD3 + mCherry | 39 | 5 | 942.0 | 211.2 | 8.23 | 0.039 |
| PLD3 + TMEM106B + mCherry | 8 | 9 | 865.0 | 136.5 | 8.78 | 0.064 |
| PLD3 + TMEM106B + mCherry | 25 | 3 | 935.0 | 43.9 | 6.73 | 0.153 |
| PLD3 + TMEM106B + mCherry | 39 | 7 | 945.0 | 69.0 | 6.52 | 0.095 |

The clearest pilot signal is the Day 25 increase in diffuse/punctate mCherry score in the primary condition. The primary wells also show much lower punctate mean intensity than reporter controls at Day 25 and Day 39.

The QC-filtered Day 25 primary group currently has only 3 passing wells, so it should be treated as a strong pilot signal plus a registration-QC warning, not as a final group statistic.

## Applicable dataset manifest

The filename/size-only manifest is:

```text
LOCAL_PROCESSED_OUTPUT/pilot/dataset_manifest/
  nd2_filename_size_manifest.csv
  mcherry_applicable_nd2_manifest.csv
  mcherry_applicable_summary.csv
```

The valid fluorescence mCherry subset contains 864 ND2 files:

- `432` reporter-control fluorescence ND2 files
- `432` primary fluorescence ND2 files

This is still too much to run as a casual next step. Scale by selected columns and days.

## QC cautions

Registration QC for column 05 is under:

```text
LOCAL_PROCESSED_OUTPUT/pilot/registration_qc/
```

Registration QC for column 06 is under:

```text
LOCAL_PROCESSED_OUTPUT/pilot/registration_qc_column06/
```

Registration QC for column 07 is under:

```text
LOCAL_PROCESSED_OUTPUT/pilot/registration_qc_column07/
```

Large-shift flags occurred in all three processed columns. The graphical analysis now writes QC-passing summaries that exclude flagged well/day observations. Large shifts may represent stage-position differences, FOV mismatch, or registration ambiguity, and can bias whole-frame quantification even when common-overlap cropping is used.

The metadata-only stage prefilter currently passes all `54` processed well/day observations at a `5 um` XY threshold. Z distances are retained but not used for exclusion because the ND2 files mix relative and absolute Z coordinate conventions across days.

See `docs/STAGE_QC_AND_ROI_WORKFLOW.md` for the current stage prefilter, automated QC report, and first-pass ROI-restricted quantification workflow.

## Further optimization and uses

Recommended optimizations:

1. Use the automated QC gate as the primary analysis output for lab-facing summaries.
2. Use stage coordinates to pre-check whether selected days are likely the same field of view before pixel registration.
3. Add neuron or cell-body ROIs so quantification is not dominated by empty well area or field-level drift.
4. Test multiple segmentation thresholds on a small hand-reviewed subset before locking the puncta metric.
5. Keep using the 488nm channel for registration and 561nm for phenotype; do not use mCherry punctation itself as the registration target.
6. For larger viewing outputs, prefer chunked OME-Zarr rather than broad TIFF conversion.
7. Add a lab review notebook that displays the registered stack, QC overlay, metrics, and pass/fail status per well.

Practical uses now:

- Identify wells with strongest diffuse mCherry signal.
- Compare reporter controls against matched TMEM106B+mCherry wells.
- Prioritize wells/days for manual visual review.
- Generate figures for lab discussion.
- Decide which subset is worth converting to a more viewer-friendly time-series format.
- Compare full-frame and foreground-ROI-restricted mCherry diffuse/punctate scores for columns `05-07`.
