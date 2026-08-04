# Manual Alignment Override Plan

Manual alignment overrides are intended for wells/days where automatic registration fails but the correct x/y offset can be identified by visual review.

## When To Consider A Manual Offset

Use manual review when:

- the dashboard overlay visibly jumps between adjacent days;
- DAPI/reference signal is low signal-to-noise;
- automatic registration reports large shifts or very low retained overlap;
- the shift is obvious by eye in Fiji or another viewer;
- the well is important enough to rescue for ROI review.

Do not use manual offsets to make a biologically changing phenotype channel appear stable. A stable reference or morphology cue should guide the correction.

## Offset Template

Use `configs/manual_alignment_offsets_template.csv` with these fields:

- `well`
- `day`
- `dx_pixels`
- `dy_pixels`
- `reference_channel`
- `reviewer`
- `confidence`
- `notes`

The sign convention should be validated against the registration code before applying offsets at scale. Until then, offsets are review records only.

## Proposed Application Step

1. Reviewer records candidate offsets in the CSV.
2. A future pipeline stage validates the offset convention on a small subset.
3. The pipeline applies offsets only with an explicit `--manual-offsets` option.
4. Outputs are written to a separate output root, preserving current results.
5. Dashboard pages show which wells/days used manual offsets and who reviewed them.

## Interpretation Boundary

Manual offsets may improve technical alignment, but they do not confirm same-neuron identity. ROI identity review remains required before biological interpretation.
