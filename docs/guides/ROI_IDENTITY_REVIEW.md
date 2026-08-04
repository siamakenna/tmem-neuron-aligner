# Manual ROI Identity Review

The pass5 D/E/F/G outputs are ROI candidates, not confirmed same-neuron tracks. Use this guide to review identity before using neuron-level mCherry or colocalization metrics for biological interpretation.

## Launch The Dashboard

From the repository root:

```bash
python -m http.server 8765 --directory LOCAL_PROCESSED_OUTPUT/dashboard
```

Open:

```text
http://127.0.0.1:8765/index.html
```

Useful dashboard pages:

- Plate/well overview: `http://127.0.0.1:8765/index.html`
- ROI review queue: `http://127.0.0.1:8765/roi_review_queue.html`
- Priority-well review queue: `http://127.0.0.1:8765/roi_review_priority_wells.html`
- Unreviewed ROI queue: `http://127.0.0.1:8765/roi_review_unreviewed.html`
- Confirmed same-neuron queue: `http://127.0.0.1:8765/roi_review_confirmed_same_neuron.html`
- Poor-registration/exclude queue: `http://127.0.0.1:8765/roi_review_poor_registration_or_exclude.html`
- Saturation/clipping warning queue: `http://127.0.0.1:8765/roi_review_saturation_clipping_warnings.html`
- ROI well index: `http://127.0.0.1:8765/roi_full_mcherry_valid_pass5.html`
- First-pass metric summary: `http://127.0.0.1:8765/roi_first_pass_metric_summary.html`

## Review Order

Start with the best-aligned wells:

```text
J19,I11,I20,N19,M19,N08,J17,F09,J14,N12
```

These wells are prioritized in the ROI Review Queue. Review other wells after the first priority set, especially if they have many review or excluded registration days.

## What To Inspect

For each ROI candidate:

- Open the ROI card in the ROI Review Queue.
- Inspect the preview montage across included pass days.
- Open the linked ROI detail page if you need the full path to crop TIFF, metadata JSON, mCherry metrics, and colocalization metrics.
- Check the listed pass days, review days, and excluded days.
- Check colocalization warnings, especially saturation or clipping warnings.
- Compare ROI morphology, position, and signal pattern across days.
- Treat large-shift or poor-registration days as QC context, not biological evidence.

## Status Values

Use exactly one of these values in `manual_identity_status`.

- `confirmed_same_neuron`: The same neuron is visually traceable across included pass days. Registration and crop framing are adequate for candidate-level interpretation.
- `uncertain_identity`: Default status. Use when the ROI may be the same neuron, but identity is not confident enough yet.
- `lost_or_dead`: The neuron appears absent, dead, severely degraded, or no longer trackable across the included time series.
- `poor_registration`: Identity cannot be judged because registration, drift, field mismatch, or crop placement is too poor.
- `exclude`: Do not use this ROI for downstream neuron-level interpretation.

`uncertain_identity` means the pipeline found a candidate ROI and exported metrics, but no human has confirmed that the same neuron is being tracked across days.

## Why Metrics Stay Preliminary

The pass5 metrics summarize ROI candidates. They do not prove:

- that the same neuron was followed across days;
- that registration was adequate for every day;
- that mCherry redistribution is biological rather than segmentation or alignment artifact;
- that colocalization reflects true molecular overlap.

Use first-pass summaries for triage only. Biological claims should use ROIs marked `confirmed_same_neuron`, with poor-registration and excluded cases removed.

## Edit The Review CSV

The generated source review table is:

```text
LOCAL_PROCESSED_OUTPUT/full_mcherry_valid_defg_pass5/full_mcherry_valid_pass5_roi_identity_review.csv
```

The lab-editable working copy is:

```text
LOCAL_PROCESSED_OUTPUT/full_mcherry_valid_defg_pass5/review_summaries/full_mcherry_valid_pass5_roi_identity_review_working.csv
```

Edit the working copy. Keep `roi_id`, `well`, `condition`, `pass_days`, `review_days`, `excluded_days`, `crop_path`, and `metadata_path` unchanged. Update these fields:

- `manual_identity_status`
- `reviewer_notes`
- `reviewer`
- `review_date`
- `identity_confidence`
- `review_complete`

Suggested `review_date` format:

```text
YYYY-MM-DD
```

After editing and saving the working CSV, rebuild review pages and summaries:

```bash
python scripts/build_roi_review_workflow.py
```

The dashboard status summary will then reflect the updated manual labels.

## Review Progress Tracking

The dashboard treats an ROI as reviewed when any of these is true:

- `review_complete` is marked `true`, `yes`, `reviewed`, `complete`, or `done`;
- `manual_identity_status` is changed from `uncertain_identity`;
- `reviewer`, `review_date`, `identity_confidence`, or `reviewer_notes` contains a value.

Leave all review fields blank and keep `manual_identity_status` as `uncertain_identity` for unreviewed ROIs.

The review builder preserves manual edits in the working CSV. If the working CSV already exists, it is read as the source of truth for review status and is not regenerated from the original pipeline CSV.

## Outputs Created By The Review Builder

Review dashboard:

```text
LOCAL_PROCESSED_OUTPUT/dashboard/roi_review_queue.html
```

Dashboard metric summary:

```text
LOCAL_PROCESSED_OUTPUT/dashboard/roi_first_pass_metric_summary.html
```

Summary CSV/JSON files:

```text
LOCAL_PROCESSED_OUTPUT/full_mcherry_valid_defg_pass5/review_summaries/
```

## Practical Review Rule

If you would not be comfortable defending the crop as the same neuron across the included pass days, leave it as `uncertain_identity` or mark the specific reason: `lost_or_dead`, `poor_registration`, or `exclude`.
