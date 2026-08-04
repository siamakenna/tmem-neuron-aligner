# 260213 All-Well Batch

Run timestamp: 2026-07-06T12:22:55
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
          registration_qc PLD3_TMEM106B_mCherry_primary   12     48            48     48.0      48.0               0.815637                             NaN                               NaN                NaN
          registration_qc PLD3_TMEM106B_mCherry_primary   16     48            48     48.0      48.0               0.819082                             NaN                               NaN                NaN
          registration_qc PLD3_TMEM106B_mCherry_primary   20     48            48     48.0      48.0               0.775224                             NaN                               NaN                NaN
          registration_qc PLD3_TMEM106B_mCherry_primary   25     48            48     48.0      48.0               0.771315                             NaN                               NaN                NaN
          registration_qc PLD3_TMEM106B_mCherry_primary   29     48            48     48.0      48.0               0.839712                             NaN                               NaN                NaN
          registration_qc PLD3_TMEM106B_mCherry_primary   32     48            48     48.0      48.0               0.736613                             NaN                               NaN                NaN
          registration_qc PLD3_TMEM106B_mCherry_primary   36     48            48     48.0      48.0               0.774293                             NaN                               NaN                NaN
          registration_qc PLD3_TMEM106B_mCherry_primary   39     48            48     48.0      48.0               0.759063                             NaN                               NaN                NaN
          registration_qc      PLD3_TMEM106B_no_mCherry    8     48            48     48.0      48.0               1.000000                             NaN                               NaN                NaN
          registration_qc      PLD3_TMEM106B_no_mCherry   12     48            48     48.0      48.0               0.824531                             NaN                               NaN                NaN
          registration_qc      PLD3_TMEM106B_no_mCherry   16     48            48     48.0      48.0               0.788811                             NaN                               NaN                NaN
          registration_qc      PLD3_TMEM106B_no_mCherry   20     48            48     48.0      48.0               0.802499                             NaN                               NaN                NaN
          registration_qc      PLD3_TMEM106B_no_mCherry   25     48            48     48.0      48.0               0.826047                             NaN                               NaN                NaN
          registration_qc      PLD3_TMEM106B_no_mCherry   29     48            48     48.0      48.0               0.764879                             NaN                               NaN                NaN
          registration_qc      PLD3_TMEM106B_no_mCherry   32     48            48     48.0      48.0               0.786658                             NaN                               NaN                NaN
          registration_qc      PLD3_TMEM106B_no_mCherry   36     48            48     48.0      48.0               0.766755                             NaN                               NaN                NaN
          registration_qc      PLD3_TMEM106B_no_mCherry   39     48            48     48.0      48.0               0.749666                             NaN                               NaN                NaN
          registration_qc PLD3_mCherry_reporter_control    8     48            48     48.0      48.0               1.000000                             NaN                               NaN                NaN
          registration_qc PLD3_mCherry_reporter_control   12     48            48     48.0      48.0               0.824589                             NaN                               NaN                NaN
          registration_qc PLD3_mCherry_reporter_control   16     48            48     48.0      48.0               0.832714                             NaN                               NaN                NaN
          registration_qc PLD3_mCherry_reporter_control   20     48            48     48.0      48.0               0.783906                             NaN                               NaN                NaN
          registration_qc PLD3_mCherry_reporter_control   25     48            48     48.0      48.0               0.784069                             NaN                               NaN                NaN
          registration_qc PLD3_mCherry_reporter_control   29     48            48     48.0      48.0               0.787873                             NaN                               NaN                NaN
          registration_qc PLD3_mCherry_reporter_control   32     48            48     48.0      48.0               0.781023                             NaN                               NaN                NaN
          registration_qc PLD3_mCherry_reporter_control   36     48            48     48.0      48.0               0.794187                             NaN                               NaN                NaN
          registration_qc PLD3_mCherry_reporter_control   39     48            48     47.0      48.0               0.757630                             NaN                               NaN                NaN
          registration_qc          PLD3_only_no_mCherry    8     48            48     48.0      48.0               1.000000                             NaN                               NaN                NaN
          registration_qc          PLD3_only_no_mCherry   12     48            48     48.0      48.0               0.783302                             NaN                               NaN                NaN
          registration_qc          PLD3_only_no_mCherry   16     48            48     48.0      48.0               0.771891                             NaN                               NaN                NaN
          registration_qc          PLD3_only_no_mCherry   20     48            48     47.0      48.0               0.742522                             NaN                               NaN                NaN
          registration_qc          PLD3_only_no_mCherry   25     48            48     48.0      48.0               0.794288                             NaN                               NaN                NaN
          registration_qc          PLD3_only_no_mCherry   29     48            48     48.0      48.0               0.780152                             NaN                               NaN                NaN
          registration_qc          PLD3_only_no_mCherry   32     48            48     48.0      48.0               0.793891                             NaN                               NaN                NaN
          registration_qc          PLD3_only_no_mCherry   36     48            48     48.0      48.0               0.803803                             NaN                               NaN                NaN
          registration_qc          PLD3_only_no_mCherry   39     48            48     48.0      48.0               0.831875                             NaN                               NaN                NaN
mcherry_valid_measurement PLD3_TMEM106B_mCherry_primary    8     48            48      NaN       NaN                    NaN                        3.292434                          3.245657         304.916667
mcherry_valid_measurement PLD3_TMEM106B_mCherry_primary   12     48            48      NaN       NaN                    NaN                        4.310792                          4.210769         290.687500
mcherry_valid_measurement PLD3_TMEM106B_mCherry_primary   16     48            48      NaN       NaN                    NaN                        4.466611                          4.476127         280.958333
mcherry_valid_measurement PLD3_TMEM106B_mCherry_primary   20     48            48      NaN       NaN                    NaN                        4.746171                          4.634731         319.895833
mcherry_valid_measurement PLD3_TMEM106B_mCherry_primary   25     48            48      NaN       NaN                    NaN                        6.806974                          6.703355         290.333333
mcherry_valid_measurement PLD3_TMEM106B_mCherry_primary   29     48            48      NaN       NaN                    NaN                        5.622443                          5.568145         389.291667
mcherry_valid_measurement PLD3_TMEM106B_mCherry_primary   32     48            48      NaN       NaN                    NaN                        5.572404                          5.595269         422.250000
mcherry_valid_measurement PLD3_TMEM106B_mCherry_primary   36     48            48      NaN       NaN                    NaN                        5.429803                          5.363355         428.812500
mcherry_valid_measurement PLD3_TMEM106B_mCherry_primary   39     48            48      NaN       NaN                    NaN                        5.272267                          5.158413         432.395833
mcherry_valid_measurement PLD3_mCherry_reporter_control    8     48            48      NaN       NaN                    NaN                        2.527689                          2.535804         269.875000
mcherry_valid_measurement PLD3_mCherry_reporter_control   12     48            48      NaN       NaN                    NaN                        2.876650                          2.829678         245.770833
mcherry_valid_measurement PLD3_mCherry_reporter_control   16     48            48      NaN       NaN                    NaN                        2.757251                          2.765667         264.687500
mcherry_valid_measurement PLD3_mCherry_reporter_control   20     48            48      NaN       NaN                    NaN                        3.077710                          3.099923         313.333333
mcherry_valid_measurement PLD3_mCherry_reporter_control   25     48            48      NaN       NaN                    NaN                        4.012665                          3.953218         269.708333
mcherry_valid_measurement PLD3_mCherry_reporter_control   29     48            48      NaN       NaN                    NaN                        3.607274                          3.571139         348.479167
mcherry_valid_measurement PLD3_mCherry_reporter_control   32     48            48      NaN       NaN                    NaN                        3.488044                          3.443546         375.229167
mcherry_valid_measurement PLD3_mCherry_reporter_control   36     48            48      NaN       NaN                    NaN                        3.335780                          3.338806         391.375000
mcherry_valid_measurement PLD3_mCherry_reporter_control   39     48            48      NaN       NaN                    NaN                        3.428669                          3.402999         409.291667
```
