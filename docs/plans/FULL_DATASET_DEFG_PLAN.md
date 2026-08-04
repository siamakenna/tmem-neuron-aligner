# Full-Dataset D/E/F/G Plan

This plan starts after the full mCherry-valid A/B/C dashboard and QC summary have been reviewed.

Do not run these stages until explicitly approved.

## Scope

Use only mCherry-valid wells:

- Reporter controls: `E05-E20`, `I05-I20`, `M05-M20`
- TMEM106B + mCherry: `F05-F20`, `J05-J20`, `N05-N20`

Keep non-mCherry wells marked `not_applicable_no_mCherry` if they appear in manifests.

## Stage D: ROI Candidate Generation

- Use A/B/C registered common-overlap stacks as the first input.
- Generate per-well candidate ROI tables, not final biological calls.
- Include original/reference-frame coordinates, day coverage, registration QC status, and source identifiers.
- Mark all candidates `uncertain_identity` until manual review.
- Exclude or separately mark days with `exclude_recommended` registration QC.

Expected outputs:

```text
<output-root>/wells/<WELL>/roi_candidates/<WELL>_roi_candidates.csv
<output-root>/wells/<WELL>/roi_candidates/<WELL>_roi_review_template.csv
```

## Stage E: Neuron-Centered Time-Series Export

- Export only candidate or manually selected ROIs.
- Preserve `TCYX` order for neuron-centered OME-TIFFs.
- Save crop boxes in original/reference-frame coordinates.
- Generate small dashboard previews only; do not copy large stacks into the website folder.

Expected outputs:

```text
<output-root>/wells/<WELL>/neuron_rois/<ROI_ID>/<ROI_ID>_registered_tcyx.ome.tif
<output-root>/wells/<WELL>/neuron_rois/<ROI_ID>/<ROI_ID>_preview.png
<output-root>/wells/<WELL>/neuron_rois/<ROI_ID>/<ROI_ID>_metadata.json
```

## Stage F: mCherry and Colocalization Metrics

- Run only for mCherry-valid wells/ROIs.
- Treat punctation/diffusion metrics as screening metrics.
- Do not interpret large shifts or mCherry diffusion as biological findings without manual ROI identity review.
- Save threshold parameters, channel names, QC flags, and skip reasons.

Expected outputs:

```text
<output-root>/wells/<WELL>/metrics/<WELL>_mcherry_metrics.csv
<output-root>/wells/<WELL>/metrics/<WELL>_colocalization_metrics.csv
```

## Stage G: Dashboard Neuron Pages

- Add plate -> well -> neuron -> time series/QC/metrics navigation.
- Show missing outputs explicitly.
- Preserve lab-facing labels:
  - preliminary
  - requires visual review
  - ROI identity unconfirmed
  - exclude recommended

## Approval Gate

Before D/E/F/G execution, review:

- `all_wells_registration_qc_summary.csv`
- `all_wells_registration_qc_summary.json`
- dashboard QC page
- worst-shift wells/timepoints
- available disk space
- whether ROI extraction should start with pass-only days or include review days
