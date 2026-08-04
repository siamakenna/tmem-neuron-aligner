# 260213 All-Well Batch

Run timestamp: 2026-07-22T00:15:36
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
          registration_qc PLD3_TMEM106B_mCherry_primary   25     48            48     48.0      48.0               0.967997                             NaN                               NaN                NaN
          registration_qc PLD3_TMEM106B_mCherry_primary   29     48            48     48.0      48.0               0.975078                             NaN                               NaN                NaN
          registration_qc PLD3_TMEM106B_mCherry_primary   32     48            48     48.0      48.0               0.828214                             NaN                               NaN                NaN
          registration_qc PLD3_TMEM106B_mCherry_primary   36     48            48     48.0      48.0               0.920832                             NaN                               NaN                NaN
          registration_qc PLD3_TMEM106B_mCherry_primary   39     48            48     48.0      48.0               0.735360                             NaN                               NaN                NaN
          registration_qc      PLD3_TMEM106B_no_mCherry    8     48            48     48.0      48.0               1.000000                             NaN                               NaN                NaN
          registration_qc      PLD3_TMEM106B_no_mCherry   12     48            48     48.0      48.0               0.931918                             NaN                               NaN                NaN
          registration_qc      PLD3_TMEM106B_no_mCherry   16     48            48     48.0      48.0               0.972912                             NaN                               NaN                NaN
          registration_qc      PLD3_TMEM106B_no_mCherry   20     48            48     48.0      48.0               0.932575                             NaN                               NaN                NaN
          registration_qc      PLD3_TMEM106B_no_mCherry   25     48            48     48.0      48.0               0.967927                             NaN                               NaN                NaN
          registration_qc      PLD3_TMEM106B_no_mCherry   29     48            48     48.0      48.0               0.974762                             NaN                               NaN                NaN
          registration_qc      PLD3_TMEM106B_no_mCherry   32     48            48     48.0      48.0               0.820662                             NaN                               NaN                NaN
          registration_qc      PLD3_TMEM106B_no_mCherry   36     48            48     48.0      48.0               0.913781                             NaN                               NaN                NaN
          registration_qc      PLD3_TMEM106B_no_mCherry   39     48            48     48.0      48.0               0.736157                             NaN                               NaN                NaN
          registration_qc PLD3_mCherry_reporter_control    8     48            48     48.0      48.0               1.000000                             NaN                               NaN                NaN
          registration_qc PLD3_mCherry_reporter_control   12     48            48     48.0      48.0               0.934931                             NaN                               NaN                NaN
          registration_qc PLD3_mCherry_reporter_control   16     48            48     48.0      48.0               0.973616                             NaN                               NaN                NaN
          registration_qc PLD3_mCherry_reporter_control   20     48            48     48.0      48.0               0.936444                             NaN                               NaN                NaN
          registration_qc PLD3_mCherry_reporter_control   25     48            48     48.0      48.0               0.967757                             NaN                               NaN                NaN
          registration_qc PLD3_mCherry_reporter_control   29     48            48     48.0      48.0               0.974712                             NaN                               NaN                NaN
          registration_qc PLD3_mCherry_reporter_control   32     48            48     48.0      48.0               0.824277                             NaN                               NaN                NaN
          registration_qc PLD3_mCherry_reporter_control   36     48            48     48.0      48.0               0.917219                             NaN                               NaN                NaN
          registration_qc PLD3_mCherry_reporter_control   39     48            48     48.0      48.0               0.737581                             NaN                               NaN                NaN
          registration_qc          PLD3_only_no_mCherry    8     48            48     48.0      48.0               1.000000                             NaN                               NaN                NaN
          registration_qc          PLD3_only_no_mCherry   12     48            48     48.0      48.0               0.929005                             NaN                               NaN                NaN
          registration_qc          PLD3_only_no_mCherry   16     48            48     48.0      48.0               0.972214                             NaN                               NaN                NaN
          registration_qc          PLD3_only_no_mCherry   20     48            48     48.0      48.0               0.928873                             NaN                               NaN                NaN
          registration_qc          PLD3_only_no_mCherry   25     48            48     48.0      48.0               0.968155                             NaN                               NaN                NaN
          registration_qc          PLD3_only_no_mCherry   29     48            48     48.0      48.0               0.975048                             NaN                               NaN                NaN
          registration_qc          PLD3_only_no_mCherry   32     48            48     48.0      48.0               0.817045                             NaN                               NaN                NaN
          registration_qc          PLD3_only_no_mCherry   36     48            48     48.0      48.0               0.910234                             NaN                               NaN                NaN
          registration_qc          PLD3_only_no_mCherry   39     48            48     48.0      48.0               0.733751                             NaN                               NaN                NaN
mcherry_valid_measurement PLD3_TMEM106B_mCherry_primary    8     48            48      NaN       NaN                    NaN                        3.160865                          3.141677         837.708333
mcherry_valid_measurement PLD3_TMEM106B_mCherry_primary   12     48            48      NaN       NaN                    NaN                        4.602995                          4.586889         751.333333
mcherry_valid_measurement PLD3_TMEM106B_mCherry_primary   16     48            48      NaN       NaN                    NaN                        4.653300                          4.648801         755.479167
mcherry_valid_measurement PLD3_TMEM106B_mCherry_primary   20     48            48      NaN       NaN                    NaN                        5.009878                          5.024978         840.104167
mcherry_valid_measurement PLD3_TMEM106B_mCherry_primary   25     48            48      NaN       NaN                    NaN                        6.763549                          6.778156         718.562500
mcherry_valid_measurement PLD3_TMEM106B_mCherry_primary   29     48            48      NaN       NaN                    NaN                        5.913353                          5.885021        1024.208333
mcherry_valid_measurement PLD3_TMEM106B_mCherry_primary   32     48            48      NaN       NaN                    NaN                        5.797363                          5.778360        1088.937500
mcherry_valid_measurement PLD3_TMEM106B_mCherry_primary   36     48            48      NaN       NaN                    NaN                        5.865826                          5.843674        1145.916667
mcherry_valid_measurement PLD3_TMEM106B_mCherry_primary   39     48            48      NaN       NaN                    NaN                        6.506865                          6.411427        1091.041667
mcherry_valid_measurement PLD3_mCherry_reporter_control    8     48            48      NaN       NaN                    NaN                        2.479096                          2.476516         825.187500
mcherry_valid_measurement PLD3_mCherry_reporter_control   12     48            48      NaN       NaN                    NaN                        3.030646                          3.019729         721.020833
mcherry_valid_measurement PLD3_mCherry_reporter_control   16     48            48      NaN       NaN                    NaN                        2.967710                          2.997551         777.229167
mcherry_valid_measurement PLD3_mCherry_reporter_control   20     48            48      NaN       NaN                    NaN                        3.300150                          3.335520         922.312500
mcherry_valid_measurement PLD3_mCherry_reporter_control   25     48            48      NaN       NaN                    NaN                        4.221678                          4.205880         749.395833
mcherry_valid_measurement PLD3_mCherry_reporter_control   29     48            48      NaN       NaN                    NaN                        3.783864                          3.820916        1031.833333
mcherry_valid_measurement PLD3_mCherry_reporter_control   32     48            48      NaN       NaN                    NaN                        3.586487                          3.604557        1080.708333
mcherry_valid_measurement PLD3_mCherry_reporter_control   36     48            48      NaN       NaN                    NaN                        3.537410                          3.551369        1139.416667
mcherry_valid_measurement PLD3_mCherry_reporter_control   39     48            48      NaN       NaN                    NaN                        3.692149                          3.693976        1085.562500
```
