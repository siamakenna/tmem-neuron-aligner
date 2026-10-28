# Independent 488 review handoff

Start with [REVIEW_VALIDATION_README.md](REVIEW_VALIDATION_README.md). It contains the exact local commands to open, save, reload and validate the 108-visit review.

## Reviewer responsibilities

Review every selected neuron at all nine days using 488 only. The selected IDs and order are in [the frozen manifest](../../configs/panels/portable_20261027_v1.json). No visit is pre-marked as a human pass. Record same-neuron identity as yes/no/uncertain and ROI ownership as clear/uncertain/contaminated; leave an unreviewed visit blank. Explain uncertain or negative decisions in notes.

White cross = original frozen anchor; yellow = fixed identity core; red = fixed phenotype ROI. Cyan/magenta/orange circles = unadopted radius40/60/80 proposals. The white rectangle in the larger registered search window is the original 128px measurement crop. Larger views and LUTs are display only, not adopted geometry.

The existing gallery's saved raw_search stage means registered 488 pixels before local normalization; it is not a raw detector image. Off-crop matches and neighboring structures need actual image inspection, not score-only approval.

Inherited automated QC failures are immutable. You may annotate your biological interpretation of such visits, but a yes/clear decision cannot clear a failed QC gate. Codex's provisional observations are not expert annotations. The original per-case triage table is retained in the private preserved handoff rather than republished.

## Saving and auditing

Enter your own reviewer identity; it locks after attributed annotations exist. Save each visit, then download private JSON before closing. Reload the same JSON to continue. No account, external service, browser storage or server deployment is required.

Run the Python validator against the current sources after downloading. A changed source array, trace manifest, displayed sheet, workspace or generator/UI invalidates old bindings. Do not replace hashes to make stale annotations pass. Duplicate observations, unknown categories, partial fields, mixed attribution, invalid timestamps and non-488 decision fields are blocked or explicitly incomplete.

The private readiness_summary.json and validator report expose source images, QC reasons, geometry sensitivity, tracking proposals and unresolved decisions. Public documentation intentionally does not contain case-level biological labels or reviewer records.

## Dry-run statuses and scientific release

REVIEW_PENDING, QC_BLOCKED, EVIDENCE_STALE, TECHNICAL_ONLY and EXCLUDED remain blocked. ELIGIBLE_FOR_EXISTING_FINAL_REVIEW only means the 488 preparation can proceed to the separate verified final workflow; it is not scientifically accepted.

Do not edit or bypass the existing review_gate.py, export_reviewed_metrics.py or matched_analysis.py contracts. Authentic final source/render fingerprints, all nine QC visits, separate later 561 phenotype review, exclusions, decision evidence and an eligible well-level cohort still apply. See [SCIENTIFIC_RELEASE_BLOCKERS.md](SCIENTIFIC_RELEASE_BLOCKERS.md).

The owner may authorize software-infrastructure merging after its software gates pass. This never approves biological measurements or supplies the missing human decisions.
