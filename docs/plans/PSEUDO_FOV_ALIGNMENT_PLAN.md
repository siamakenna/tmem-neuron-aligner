# Pseudo-FOV Alignment Plan

This plan addresses the PI concern that cells can appear to pop in or out when single-field time series are aligned across days.

## Why Single-FOV Alignment Can Fail

iNeurons should overlay closely over 1-2 day intervals when the same field is reacquired and the imaging-session alignment is good. Large day-to-day x/y shifts, weak focus consistency, or low signal-to-noise in the reference channel can make automatic single-FOV registration fail even when the correct offset is visually obvious in Fiji.

The current dashboard keeps those failures visible. Low retained overlap, large shifts, and uncertain overlays are technical QC flags, not biological findings.

## Why Pseudo-FOV Alignment May Help

Small single fields may not contain enough stable structure for robust registration. A stitched larger pseudo-field of view can provide more nuclei, stable morphology, and background landmarks, improving the chance that the registration algorithm finds the correct day-to-day offset.

The preferred registration anchor should be a stable signal such as nuclear distribution, morphology, or another reference-like channel. mCherry phenotype should not be the primary anchor when it may change biologically.

## Proposed Workflow

1. Group adjacent acquisition fields for a well/day when available.
2. Stitch or tile them into a lightweight pseudo-FOV reference per day.
3. Register day-level pseudo-FOVs using a stable reference channel or stable morphology image.
4. Transfer the estimated x/y offset back to the single-FOV well outputs.
5. Recompute common-overlap regions after applying the validated offset.
6. Rebuild dashboard previews and QC tables so alignment success/failure remains visible.

## Manual Offset Integration

For difficult wells/days, a reviewer may define manual x/y offsets using `configs/manual_alignment_offsets_template.csv`. Manual offsets should be treated as reviewed technical corrections, not silent changes.

## Validation Before Biological Interpretation

Before using pseudo-FOV aligned outputs for biological conclusions:

- inspect same-frame overlays in the dashboard;
- confirm that iNeuron morphology/nuclear distribution is stable across adjacent days;
- verify retained overlap is sufficient for the ROI being interpreted;
- keep ROI identity status as `uncertain_identity` until manually reviewed;
- document the registration anchor and reviewer confidence.

This plan is not implemented as a full reprocessing step yet.
