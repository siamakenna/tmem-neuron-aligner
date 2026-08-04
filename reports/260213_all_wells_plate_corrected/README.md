# 260213 All-Well Batch

Run timestamp: 2026-07-21T23:56:36
Data root: `/Users/pmihack/claire/tmem_2026/data/260213_Feb16recopy_HYdiff_landingpadlines_survival_384well1`
Days requested: `8, 12, 16, 20, 25, 29, 32, 36, 39`
Wells selected: `192`
mCherry-valid wells measured: `96`

Why this is broader than the E05/F05 pilot: the first run was a tiny proof-of-pipeline
using the first reporter-control/experimental pair. This run includes every well with
the requested days present.

Important interpretation rule: rows without mCherry reporter are included for registration
QC and plate coverage, but they are not treated as zero-mCherry puncta samples.

Outputs:
- `all_wells_selected_files.csv`
- `all_wells_registration_qc.csv`
- `all_wells_mcherry_measurements.csv` for E/F/I/J/M/N rows only
- `all_wells_summary_stats.csv`
- `all_wells_failures.csv`
- `figures/all_wells_registration_qc_pass_fraction.png`
- `figures/all_wells_mcherry_ratio_slope_heatmap.png`
- `figures/all_wells_mcherry_condition_summary.png`

## Summary

```text
             summary_type                     condition  day  wells  observations  qc_pass  qc_total  mean_overlap_fraction  mean_diffuse_to_punctate_ratio  median_diffuse_to_punctate_ratio  mean_puncta_count
          registration_qc PLD3_TMEM106B_mCherry_primary    8     48            48     48.0      48.0               1.000000                             NaN                               NaN                NaN
          registration_qc PLD3_TMEM106B_mCherry_primary   12     48            48     48.0      48.0               0.938001                             NaN                               NaN                NaN
          registration_qc PLD3_TMEM106B_mCherry_primary   16     48            48     48.0      48.0               0.974562                             NaN                               NaN                NaN
          registration_qc PLD3_TMEM106B_mCherry_primary   20     48            48     48.0      48.0               0.940462                             NaN                               NaN                NaN
          registration_qc PLD3_TMEM106B_mCherry_primary   25     48            48     48.0      48.0               0.967988                             NaN                               NaN                NaN
          registration_qc PLD3_TMEM106B_mCherry_primary   29     48            48     48.0      48.0               0.975118                             NaN                               NaN                NaN
          registration_qc PLD3_TMEM106B_mCherry_primary   32     48            48     48.0      48.0               0.828181                             NaN                               NaN                NaN
          registration_qc PLD3_TMEM106B_mCherry_primary   36     48            48     48.0      48.0               0.920723                             NaN                               NaN                NaN
          registration_qc PLD3_TMEM106B_mCherry_primary   39     48            48     48.0      48.0               0.735685                             NaN                               NaN                NaN
          registration_qc      PLD3_TMEM106B_no_mCherry    8     48            48     48.0      48.0               1.000000                             NaN                               NaN                NaN
          registration_qc      PLD3_TMEM106B_no_mCherry   12     48            48     48.0      48.0               0.931918                             NaN                               NaN                NaN
          registration_qc      PLD3_TMEM106B_no_mCherry   16     48            48     48.0      48.0               0.972912                             NaN                               NaN                NaN
          registration_qc      PLD3_TMEM106B_no_mCherry   20     48            48     48.0      48.0               0.932575                             NaN                               NaN                NaN
          registration_qc      PLD3_TMEM106B_no_mCherry   25     48            48     48.0      48.0               0.967961                             NaN                               NaN                NaN
          registration_qc      PLD3_TMEM106B_no_mCherry   29     48            48     48.0      48.0               0.974789                             NaN                               NaN                NaN
          registration_qc      PLD3_TMEM106B_no_mCherry   32     48            48     48.0      48.0               0.820674                             NaN                               NaN                NaN
          registration_qc      PLD3_TMEM106B_no_mCherry   36     48            48     48.0      48.0               0.913750                             NaN                               NaN                NaN
          registration_qc      PLD3_TMEM106B_no_mCherry   39     48            48     48.0      48.0               0.736254                             NaN                               NaN                NaN
          registration_qc PLD3_mCherry_reporter_control    8     48            48     48.0      48.0               1.000000                             NaN                               NaN                NaN
          registration_qc PLD3_mCherry_reporter_control   12     48            48     48.0      48.0               0.934931                             NaN                               NaN                NaN
          registration_qc PLD3_mCherry_reporter_control   16     48            48     48.0      48.0               0.973616                             NaN                               NaN                NaN
          registration_qc PLD3_mCherry_reporter_control   20     48            48     48.0      48.0               0.936444                             NaN                               NaN                NaN
          registration_qc PLD3_mCherry_reporter_control   25     48            48     48.0      48.0               0.967718                             NaN                               NaN                NaN
          registration_qc PLD3_mCherry_reporter_control   29     48            48     48.0      48.0               0.974699                             NaN                               NaN                NaN
          registration_qc PLD3_mCherry_reporter_control   32     48            48     48.0      48.0               0.824179                             NaN                               NaN                NaN
          registration_qc PLD3_mCherry_reporter_control   36     48            48     48.0      48.0               0.917265                             NaN                               NaN                NaN
          registration_qc PLD3_mCherry_reporter_control   39     48            48     48.0      48.0               0.737640                             NaN                               NaN                NaN
          registration_qc          PLD3_only_no_mCherry    8     48            48     48.0      48.0               1.000000                             NaN                               NaN                NaN
          registration_qc          PLD3_only_no_mCherry   12     48            48     48.0      48.0               0.929005                             NaN                               NaN                NaN
          registration_qc          PLD3_only_no_mCherry   16     48            48     48.0      48.0               0.972214                             NaN                               NaN                NaN
          registration_qc          PLD3_only_no_mCherry   20     48            48     48.0      48.0               0.928873                             NaN                               NaN                NaN
          registration_qc          PLD3_only_no_mCherry   25     48            48     48.0      48.0               0.968178                             NaN                               NaN                NaN
          registration_qc          PLD3_only_no_mCherry   29     48            48     48.0      48.0               0.975030                             NaN                               NaN                NaN
          registration_qc          PLD3_only_no_mCherry   32     48            48     48.0      48.0               0.817034                             NaN                               NaN                NaN
          registration_qc          PLD3_only_no_mCherry   36     48            48     48.0      48.0               0.910228                             NaN                               NaN                NaN
          registration_qc          PLD3_only_no_mCherry   39     48            48     48.0      48.0               0.733751                             NaN                               NaN                NaN
mcherry_valid_measurement PLD3_TMEM106B_mCherry_primary    8     48            48      NaN       NaN                    NaN                        3.160532                          3.142383         837.229167
mcherry_valid_measurement PLD3_TMEM106B_mCherry_primary   12     48            48      NaN       NaN                    NaN                        4.598535                          4.588763         750.291667
mcherry_valid_measurement PLD3_TMEM106B_mCherry_primary   16     48            48      NaN       NaN                    NaN                        4.652630                          4.643820         755.083333
mcherry_valid_measurement PLD3_TMEM106B_mCherry_primary   20     48            48      NaN       NaN                    NaN                        5.009219                          5.024190         839.645833
mcherry_valid_measurement PLD3_TMEM106B_mCherry_primary   25     48            48      NaN       NaN                    NaN                        5.525596                          5.547509         806.479167
mcherry_valid_measurement PLD3_TMEM106B_mCherry_primary   29     48            48      NaN       NaN                    NaN                        4.985888                          4.952692        1119.000000
mcherry_valid_measurement PLD3_TMEM106B_mCherry_primary   32     48            48      NaN       NaN                    NaN                        4.916764                          4.939696        1189.729167
mcherry_valid_measurement PLD3_TMEM106B_mCherry_primary   36     48            48      NaN       NaN                    NaN                        4.942881                          4.847932        1255.812500
mcherry_valid_measurement PLD3_TMEM106B_mCherry_primary   39     48            48      NaN       NaN                    NaN                        5.375658                          5.351663        1191.208333
mcherry_valid_measurement PLD3_mCherry_reporter_control    8     48            48      NaN       NaN                    NaN                        2.478831                          2.476255         825.000000
mcherry_valid_measurement PLD3_mCherry_reporter_control   12     48            48      NaN       NaN                    NaN                        3.031694                          3.026615         720.166667
mcherry_valid_measurement PLD3_mCherry_reporter_control   16     48            48      NaN       NaN                    NaN                        2.967325                          2.996384         777.020833
mcherry_valid_measurement PLD3_mCherry_reporter_control   20     48            48      NaN       NaN                    NaN                        3.298147                          3.335977         922.062500
mcherry_valid_measurement PLD3_mCherry_reporter_control   25     48            48      NaN       NaN                    NaN                        3.658643                          3.669444         846.854167
mcherry_valid_measurement PLD3_mCherry_reporter_control   29     48            48      NaN       NaN                    NaN                        3.408958                          3.466310        1116.770833
mcherry_valid_measurement PLD3_mCherry_reporter_control   32     48            48      NaN       NaN                    NaN                        3.229735                          3.228503        1174.750000
mcherry_valid_measurement PLD3_mCherry_reporter_control   36     48            48      NaN       NaN                    NaN                        3.154882                          3.138468        1249.354167
mcherry_valid_measurement PLD3_mCherry_reporter_control   39     48            48      NaN       NaN                    NaN                        3.271333                          3.239481        1170.979167
```
