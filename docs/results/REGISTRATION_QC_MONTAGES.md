# Registration QC Montages

This QC step creates quick-look montages for the registered same-well longitudinal pilot stacks. The generated PNGs are local outputs and are not committed to Git.

## Reproduce

From the repo root:

```bash
source .venv/bin/activate
python scripts/make_registration_qc_montages.py
```

## Local Outputs

```text
LOCAL_PROCESSED_OUTPUT/pilot/registration_qc/
  registration_qc_shift_summary.csv
  E05_day8_day25_day39_registered_alignment_ch2_montage.png
  E05_day8_day25_day39_registered_mcherry_ch1_montage.png
  E05_day8_day25_day39_common_overlap_mcherry_ch1_montage.png
  E05_day8_day25_day39_alignment_day_overlay.png
  ...same pattern for F05, I05, J05, M05, N05
```

## What To Review

- `registered_alignment_ch2_montage`: the 488nm channel used for registration, shown across Day 8, Day 25, and Day 39.
- `registered_mcherry_ch1_montage`: the full registered 561nm mCherry frames, including any black borders caused by shifts.
- `common_overlap_mcherry_ch1_montage`: the cropped overlap region used for mCherry quantification.
- `alignment_day_overlay`: RGB overlay of the alignment channel, where red is Day 8, green is Day 25, and blue is Day 39.
- `registration_qc_shift_summary.csv`: shift values, large-shift flags, and common-overlap correlation-to-Day-8 values for the alignment and mCherry channels.

## Shift Flags

Large shifts are flagged when either `abs(dy)` or `abs(dx)` exceeds 500 pixels.

| well | day | dy | dx | large_shift |
|---|---:|---:|---:|---|
| F05 | 25 | -1.0 | 921.0 | true |
| J05 | 39 | 1026.0 | -2.0 | true |
| M05 | 39 | 0.9 | -921.0 | true |

These cases should be visually reviewed before biological interpretation. They may represent real stage offsets, field-of-view mismatch, or registration ambiguity.

## Correlation Values

The QC summary also includes `alignment_corr_to_day8_common_overlap` and `mcherry_corr_to_day8_common_overlap`. These are descriptive values, not pass/fail thresholds. They can be low even when shifts are small because the signal changes across days, the fields are sparse, and the current pilot compares whole-frame wells rather than manually selected neuron ROIs.

## Current QC Interpretation

E05, I05, and N05 have stable subpixel shifts across the selected days. F05 Day 25, J05 Day 39, and M05 Day 39 require careful review. The scripts crop to common overlap before quantification, but a large shift can still mean that the overlap is not the most biologically representative region of the well.
