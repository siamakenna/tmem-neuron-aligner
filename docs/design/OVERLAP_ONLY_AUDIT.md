# Overlap-Only Alignment Audit

This audit incorporates PI feedback about cells appearing to pop in or out of time-lapse views after registration.

## Summary

The existing `registered_common_overlap` outputs already implement the requested overlap-only concept: they crop the registered time series to the shared intersection region across all aligned days for each well.

Current pass5 ROI candidates, neuron-centered crops, mCherry metrics, and exploratory colocalization metrics were generated from `registered_common_overlap` stacks, not the full registered field.

The main gap was metadata and labeling. The common-overlap crop was computed during A/B/C but was not persisted as explicit overlap-only metadata next to each well. Dashboard pages also did not make the distinction between full registered context and overlap-only analysis as clear as the PI requested.

## Audit Findings

1. `registered_common_overlap` represents the intersection region across aligned days.
   - The crop is reconstructed from per-day registration shifts.
   - It removes non-shared registered-frame borders caused by day-to-day field-of-view drift.

2. Dashboard A/B/C day previews use common-overlap stacks.
   - The preview writer reads `registered_common_overlap`.
   - Preview titles already describe them as common-overlap mCherry previews.

3. D/E/F/G pass5 ROI candidates and metrics use common-overlap stacks.
   - The ROI export plan uses `wells/<well>/registered_common_overlap/<well>_registered_common_overlap_tcyx.ome.tif` as the source stack.
   - ROI metadata records `source_stack` as the common-overlap OME-TIFF.

4. ROI crop coordinates are saved in common-overlap coordinates.
   - Fields include `crop_common_overlap_x0`, `crop_common_overlap_y0`, `crop_common_overlap_x1`, and `crop_common_overlap_y1`.

5. Full registered-frame crop traceability needed improvement.
   - A/B/C computed the common-overlap crop box but did not persist it as a metadata JSON.
   - `scripts/build_overlap_only_audit.py` now reconstructs and saves this metadata from existing QC shifts.

6. Some poor-shift wells retain very little overlap.
   - Example: F11 retains about 8.9% of the full registered area.
   - These wells should remain visible for review but should be treated cautiously for biological interpretation.

## New Overlap-Only Metadata

Run:

```bash
python scripts/build_overlap_only_audit.py
```

This creates:

```text
LOCAL_PROCESSED_OUTPUT/full_mcherry_valid_queue_abc/overlap_only_audit/overlap_only_summary.csv
LOCAL_PROCESSED_OUTPUT/full_mcherry_valid_queue_abc/overlap_only_audit/overlap_only_summary.json
LOCAL_PROCESSED_OUTPUT/full_mcherry_valid_queue_abc/wells/<well>/overlap_only_metadata/<well>_overlap_only_metadata.json
```

It also updates:

```text
LOCAL_PROCESSED_OUTPUT/dashboard/overlap_only_qc_summary.html
LOCAL_PROCESSED_OUTPUT/dashboard/wells/<well>.html
LOCAL_PROCESSED_OUTPUT/dashboard/rois/<well>/<roi>.html
```

## Dashboard Interpretation

Dashboard language now distinguishes:

- `registered_full`: full registered context, may contain edge artifacts, context only.
- `registered_common_overlap`: overlap-only analysis view, preferred for ROI review, metrics, and interpretation.

Dashboard note:

```text
Overlap-only views remove non-shared edge regions across days to reduce cells popping in/out due to field-of-view drift. Full registered views are retained for context but should be interpreted cautiously.
```

## Recommended PI-Facing Conclusion

The pipeline already used overlap-only stacks for dashboard previews and pass5 ROI/metrics. The new work makes that explicit, persists overlap metadata, flags low-retained-overlap wells, and updates the dashboard/GitHub Pages workflow so reviewers can clearly distinguish full registered context from overlap-only analysis.

## Remaining Cautions

- Overlap-only cropping reduces edge pop-in/pop-out artifacts but does not solve poor biological identity tracking.
- Wells with very low retained overlap should be manually reviewed before interpretation.
- ROI identity remains `uncertain_identity` until manually reviewed.
- Large-shift wells should remain visible in the dashboard but should not be interpreted biologically without review.
