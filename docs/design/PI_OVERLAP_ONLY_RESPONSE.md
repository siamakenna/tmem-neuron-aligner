# PI Summary: Overlap-Only Response

## Concern

The previous aligned time-lapse/viewer outputs showed some cells appearing or disappearing in the aligned field of view. This is likely an edge-of-field artifact caused by day-to-day plate/FOV shifts, focus differences, registration limits, or distortions.

If the full registered frame is viewed, cells near non-shared borders can appear to pop in or out even when the central shared field is stable.

## Pipeline Response

The pipeline already creates an overlap-only output named:

```text
registered_common_overlap
```

This is the shared intersection region across all registered days for a given well.

Current dashboard day previews and pass5 ROI/metrics use this common-overlap region, not the full registered frame. This means non-shared edge regions are removed before ROI generation and quantification.

Full registered frames are still retained for context, but overlap-only/common-overlap outputs are preferred for analysis.

## Schematic

```text
full registered field across days
        |
        v
intersection/common-overlap crop
        |
        v
artifact-reduced time-lapse previews, ROI candidates, and metrics
```

## Current Audit Numbers

- 96/96 wells have ROI/metrics source = `registered_common_overlap`.
- 9 wells retain at least 50% overlap and are labeled `analysis_preferred`.
- 87 wells are labeled `review_only` under the strict retained-area threshold.
- Best retained-overlap examples: `I11`, `F06`, `N06`, `J19`, `M05`, `N12`, `J17`, `N19`, `N13`.
- Worst retained-overlap examples: `E15`, `J08`, `J18`, `E09`, `N10`, `I10`, `F20`, `J10`, `F11`, `F05`.

The 87 `review_only` wells are not automatically unusable. They need visual review or stricter interpretation under the current retained-area threshold.

## Interpretation Boundary

Overlap-only cropping should reduce cells popping in/out from field-of-view drift because non-shared edge regions are removed.

It does not solve:

- poor registration;
- focus problems;
- biological cell loss;
- manual same-neuron identity uncertainty.

All biological claims remain preliminary until ROI identity review is complete.

## Dashboard Pages

Local dashboard:

```text
LOCAL_PROCESSED_OUTPUT/dashboard/overlap_only_pi_summary.html
LOCAL_PROCESSED_OUTPUT/dashboard/overlap_only_qc_summary.html
```

GitHub Pages dashboard:

```text
docs/overlap_only_pi_summary.html
docs/overlap_only_qc_summary.html
```
