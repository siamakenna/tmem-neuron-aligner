# 260213 All-Well Batch

Run timestamp: 2026-07-02T15:17:04
Data root: `/Users/pmihack/claire/tmem_2026/data/260213_Feb16recopy_HYdiff_landingpadlines_survival_384well1`
Days requested: `8, 12, 16`
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
          registration_qc      PLD3_TMEM106B_no_mCherry    8     48            48     48.0      48.0               1.000000                             NaN                               NaN                NaN
          registration_qc      PLD3_TMEM106B_no_mCherry   12     48            48     48.0      48.0               0.824531                             NaN                               NaN                NaN
          registration_qc      PLD3_TMEM106B_no_mCherry   16     48            48     48.0      48.0               0.788811                             NaN                               NaN                NaN
          registration_qc PLD3_mCherry_reporter_control    8     48            48     48.0      48.0               1.000000                             NaN                               NaN                NaN
          registration_qc PLD3_mCherry_reporter_control   12     48            48     48.0      48.0               0.824589                             NaN                               NaN                NaN
          registration_qc PLD3_mCherry_reporter_control   16     48            48     48.0      48.0               0.832714                             NaN                               NaN                NaN
          registration_qc          PLD3_only_no_mCherry    8     48            48     48.0      48.0               1.000000                             NaN                               NaN                NaN
          registration_qc          PLD3_only_no_mCherry   12     48            48     48.0      48.0               0.783302                             NaN                               NaN                NaN
          registration_qc          PLD3_only_no_mCherry   16     48            48     48.0      48.0               0.771891                             NaN                               NaN                NaN
mcherry_valid_measurement PLD3_TMEM106B_mCherry_primary    8     48            48      NaN       NaN                    NaN                        3.264539                          3.247826         783.604167
mcherry_valid_measurement PLD3_TMEM106B_mCherry_primary   12     48            48      NaN       NaN                    NaN                        4.420834                          4.373390         738.770833
mcherry_valid_measurement PLD3_TMEM106B_mCherry_primary   16     48            48      NaN       NaN                    NaN                        4.531156                          4.582896         721.875000
mcherry_valid_measurement PLD3_mCherry_reporter_control    8     48            48      NaN       NaN                    NaN                        2.548846                          2.521218         789.020833
mcherry_valid_measurement PLD3_mCherry_reporter_control   12     48            48      NaN       NaN                    NaN                        2.892090                          2.879336         696.104167
mcherry_valid_measurement PLD3_mCherry_reporter_control   16     48            48      NaN       NaN                    NaN                        2.783979                          2.780326         758.375000
```
