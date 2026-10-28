# Offline 488 review: open, annotate, save, validate

Run these commands from the transferred package's `repo` directory. Reuse its existing `.venv-local`, registered dataset, completed benchmark and original gallery. No installation, cluster access, external account or deployed server is needed.

## 1. Open the prepared workspace

```bash
open ../review-workspace-20261028/index.html
```

This separate private workspace reuses the existing sheets; it does not alter `review-local`, its blank template, `benchmark-local`, original images, arrays, anchors or QC. The page embeds its 488 images for offline use and makes no network requests or browser-storage writes.

If transferring to another device and the workspace does not exist, prepare a **new** directory once:

```bash
../.venv-local/bin/python scripts/diagnostic_review.py prepare \
  --benchmark ../benchmark-local --gallery ../review-local \
  --workspace ../review-workspace-20261028
```

Existing directories are refused, not overwritten. Do not regenerate the completed benchmark or original gallery. The generated workspace is version/code-bound; preserve old annotations and prepare a new version if source/display/UI changes require re-review.

## 2. Review manually

Enter your reviewer identity. Select a neuron and day or use Previous/Next. Inspect the fixed 488 crop and larger registered search context. Read immutable automated QC and source hashes. The legend identifies the frozen anchor, identity core, phenotype ROI and unadopted tracking proposals.

Choose identity `yes`, `no`, or `uncertain`, and ownership `clear`, `uncertain`, or `contaminated`. Leave unreviewed choices blank. Explain uncertainty or negative findings in notes. **Save this visit annotation** records your explicit choices and a timezone-aware timestamp; it does not accept the track or change automated QC. Reviewer attribution locks once attributed observations exist. Different reviewers should use separate files.

Progress distinguishes complete decisions from unresolved/blocking decisions. All nine visits of all 12 selected neurons need human review, including automated failures. Do not use 561 to choose identity/ROI geometry. Later 561 review belongs to the separate final workflow.

## 3. Save and reload

Click **Download private JSON** before closing. It writes a timestamped download; no real annotations were entered by Codex. Use **Reload JSON** to continue that file. Keep successive downloads as an audit history rather than overwriting an earlier review.

For the commands below, save/copy your downloaded JSON privately as `../review-workspace-20261028/my-review.json` (or substitute its actual path). Never commit it. The old `review-local/review_template.csv` remains untouched; it lacks the new source/display/timestamp bindings and is not silently promoted into reviewer evidence.

## 4. Validate and inspect blocked tracks

```bash
../.venv-local/bin/python scripts/diagnostic_review.py validate \
  --benchmark ../benchmark-local --gallery ../review-local \
  --workspace ../review-workspace-20261028 \
  --annotations ../review-workspace-20261028/my-review.json \
  --out ../review-workspace-20261028/my-validation-01.json \
  --csv-out ../review-workspace-20261028/my-review-01.csv
```

Use new output names for later versions. The CSV retains the original identity/ownership terminology plus reviewer, timestamp, visit, workspace, source, trace-manifest, display and channel provenance. JSON is preferred; formula-like free text is rejected for spreadsheet CSV export rather than silently changing it.

The validator rejects duplicate/unknown observations, wrong categories, missing provenance, mixed attribution, non-488 decisions, invalid timestamps and changed evidence. Incomplete and uncertain annotations remain visible. A changed source/display/workspace yields `EVIDENCE_STALE`; never copy new hashes into old decisions to force a pass.

Read the per-neuron `tracks` section in the validation JSON. Status is `REVIEW_PENDING`, `QC_BLOCKED`, `EVIDENCE_STALE`, `TECHNICAL_ONLY`, `EXCLUDED`, or `ELIGIBLE_FOR_EXISTING_FINAL_REVIEW`. None means scientifically accepted. The final status only permits considering the next existing review stage; all real final-export requirements are listed separately.

The prepared `readiness_summary.json` contains private visit validity/reasons, source hashes, ROI/core geometry, tracking proposals, mask/area sensitivity and initial dry-run statuses. `initial-validation.json` validates the blank sheet: zero completed human decisions, not a cohort approval.

## 5. Resume the existing scientific workflow only when real requirements exist

This tool does **not** convert its CSV/JSON into `tmem.manual_review.v2`, fill phenotype criteria, call the exporter or write accepted metrics. Independently supply the existing curated files, exact displayed v6 workspace, legitimate final human review and exclusion/decision evidence. Then use the existing command, with actual private paths and a new output directory:

```bash
PYTHONPATH=src:. ../.venv-local/bin/python scripts/export_reviewed_metrics.py \
  --curated /path/to/private/curated \
  --workspace /path/to/private/v6-workspace \
  --reviews /path/to/private/authentic-final-review.json \
  --config /path/to/private/review-config.json \
  --out /path/to/private/new-reviewed-export
```

Do not run this with guessed paths or invented decisions. The existing exporter recomputes source/render fingerprints and all-nine automated gates. Only its genuine accepted exports can enter the existing matched-well analysis; use the October 23 matched-analysis README and decision-policy template. Exact N012 packet identity/source must be resolved, not guessed. Neurons remain nested within wells.

Browser automation of local-file pages was blocked by the tool's URL policy. No workaround or server was used. Front-end syntax/logic and Python validation are tested; the researcher still needs to open the local page in their browser.
