# Private human-review reconciliation

This is an evidence/readiness adapter, **not** a measurement exporter or biological classifier. It preserves genuine diagnostic 488 annotations and reports what is missing before the existing v6/final export, cohort and figure workflows can proceed. Original source stacks, anchors, primary area=180/radius=60, masks, QC and old galleries remain unchanged.

## Current local outputs

The private sibling `readiness-reconciliation-20261028/` contains:

- `reconciliation.json`: original human annotation document unchanged, diagnostic/final/cohort gate states and missing evidence for every neuron.
- `visit_readiness.csv`: each neuron/day, original attribution/notes/hashes, fixed/search image references, immutable QC, nonacceptance and unevaluated fate/censoring state.
- `well_readiness.csv`: candidates, QC blocks, pending/excluded/technical records, verified pre-existing exports, cohort eligibility, failed/nonaccepted/unreviewed visits.
- `matched_pair_readiness.csv`: E05/F05, I05/J05 and M05/N05 readiness. No treatment effect is computed.
- `figure_readiness.json`: prerequisite checks only. No figure is rendered.

The actual run uses the preserved blank sheet: zero human decisions, zero verified existing accepted exports and zero eligible matched pairs. The report is not an accepted cohort or a substitute for reviewing all 108 visits.

## After genuine human review

First use the existing offline interface and its [save/validate instructions](REVIEW_VALIDATION_README.md). Substitute your own private downloaded JSON or validated provenance-bound CSV below. Use a **new output directory** for every report version:

```bash
../.venv-local/bin/python scripts/reconcile_reviews.py \
  --workspace ../review-workspace-20261028 \
  --benchmark ../benchmark-local --gallery ../review-local \
  --annotations ../review-workspace-20261028/my-review.json \
  --out ../my-new-private-readiness-report
```

No valid record is fabricated when a field, reviewer, timestamp or source binding is absent. Negative/uncertain findings and failed visits remain visible. Exact original free text is preserved in JSON; CSV escapes formula-like text for safer spreadsheet display. Output directories are owner-only and files are owner-readable/writable. Nothing overwrites source/review folders or prior output.

## Link independently supplied final v6 artifacts

Copy [the empty source-safe template](../../configs/final_review_links.template.json) to a private location. Its `tracks` mapping uses actual declared diagnostic IDs and private paths for `curated`, `workspace`, `config`, `reviews`, and optionally `export`. Paths are relative to the links file unless absolute. Never commit a populated links file containing private paths or records.

Pass it with `--final-links /path/to/private/final-links.json`. The adapter will **not open final/561 evidence for a track until its explicit positive diagnostic 488 decisions and immutable QC gates pass**.

For a qualifying track it then checks:

Final configurations and exports must be target-only (one declared/accepted ID). Shared bundles are rejected before measurement reads, so a positive track cannot expose an unreviewed neighbor's phenotype. Existing multi-track packets are not rewritten automatically; they remain blocked until independently supplied target-only evidence is available.

1. Original frozen primary parameters, exact nine 488 crops, identity core and fixed ROI. Missing parameter provenance or a different geometry is a blocker, not permission to rewrite old packets.
2. Genuine existing v6 source and rendered-workspace fingerprints/configuration through the existing review contract.
3. The separately supplied authentic final review, including later independent 561 QC, and existing all-nine automated/global/well QC. No diagnostic decision is translated into v2 review fields.
4. An optional pre-existing accepted export through the existing `matched_analysis.load_bundle` verifier. It does not invoke the exporter or create accepted measurements.

The true target for an accepted export remains [the existing verified exporter](REVIEW_VALIDATION_README.md#5-resume-the-existing-scientific-workflow-only-when-real-requirements-exist). A ready diagnostic sheet is not `MANUAL_ACCEPTED`. Software cannot authenticate a reviewer's expertise/independence or fabricate missing provenance.

## Cohort and figure prerequisites

Optionally pass `--analysis-inputs /path/to/private/analysis-inputs.json` and `--analysis /path/to/private/verified-analysis`. These must use the existing `REAL_ACCEPTED` contract, not synthetic examples or diagnostic metrics. Before opening phenotype measurements, every bundle must match the exact reconciled curated/workspace/config/review/export paths and unchanged file fingerprints. Same-ID replacement evidence does not qualify. The existing loader then rechecks live source/decision/exclusion/cohort evidence; the existing analysis verifier rechecks tables and their provenance.

An existing verified export is distinct from a cohort-eligible neuron. Exact N012 packet identity/source and other pending decisions still require genuine evidence. Wells/matched well pairs remain biological units, never visits or independent neuron replicates.

When genuine accepted analysis is available, the figure plan can identify inputs for longitudinal trajectories, within-well summaries, matched-well comparisons and QC/attrition through the existing verified plotter. The full matched comparison requires eligible data in all six wells. ROI/segmentation provenance stays linked to final source/render evidence. No images are generated here, and no real biological figure is made from an unapproved diagnostic or a synthetic example.

Fate/censoring is not evaluated or inferred by this report. QC/missingness does not mean death. Survival remains blocked pending independent fate/censoring evidence and a prespecified model. Raw detector/correction/calibration/stitching inputs remain separately required for their corresponding validation claims.
