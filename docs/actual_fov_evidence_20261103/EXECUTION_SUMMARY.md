# Actual-FOV evidence execution — 2026-11-03

The new renderer was executed against the existing twelve source-bound registered-track cases, covering all nine visits (108 live FOV/crop bindings). Existing segmentation/tracking traces were verified and reused; the completed benchmark and acquisition jobs were not rerun.

The private output contains 28 PNG/SVG sheets, 456 processing/comparison cards, an HTML index, provenance and three comparison tables. Four declared cases at three declared visits receive detailed sheets; every case/visit contributes to the tables. The illustrated sequence includes the registered FOV, exact box, normalization, smoothing, winning threshold/morphology, selected soma, search/correlation/peak, identity core and unchanged ROI. Missing stages remain unavailable.

Paired display exploration uses the same source pixels and frozen geometry. The predeclared 200–2000 ADU interval deliberately probes both background exclusion and bright-signal loss; it is not optimized or calibrated. Smaller views can lose frozen core/ROI support or fail entirely. Saved minimum-area and search-radius alternatives show both diagnostic gains and losses. Higher correlation and newly passing flags do not establish identity accuracy. Detailed results and per-case measurements remain private, outside Git.

Current affected validation: **123 tests plus 27 subtests passed**, with no failures, errors or skips. This is fresh local validation, not the historical baseline or an independent collaborator run. Fixture-setup failures encountered while developing the new tests were corrected and their logs preserved. Scoped lint and whitespace checks passed.

Direct PNG pages and an independently rasterized SVG were visually inspected. Self-contained HTML structure and links were checked; no native-browser visual execution is claimed. Small arrow glyphs can fall back in the PNG font; numbered panels and SVG preserve the processing sequence.

No production algorithm/default, source pixel, anchor, segmentation, tracking result, measurement geometry, QC decision or acceptance gate was changed. No accepted track/export or biological claim was created. Original detector-coordinate correction fields, acquisition-to-atlas mapping, independent identity/ROI labels, separate final 561 review and all-nine-visit acceptance remain prerequisites, not software-test outcomes.

See [RUNBOOK.md](RUNBOOK.md) for executable regeneration instructions. The source-bound collaborator request must be regenerated after committing, and remains prepared—not sent or independently executed. Publication of this checkpoint does not authorize merging.
