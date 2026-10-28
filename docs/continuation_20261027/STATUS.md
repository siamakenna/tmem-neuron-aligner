# TMEM106B continuation status
## Independent-review infrastructure checkpoint

The October 27 calculations are preserved, not rerun: all six wells and nine visits; 12 completed diagnostic cases; no software failures, timeouts or deferred cases. Primary 488 QC remains 91/108 valid visits, with all 17 failed gates retained. Six tracks remain diagnostically rejected, six pending independent review, and zero scientifically accepted.

The prior fresh local evidence remains separate from historical cluster evidence: portable controls 58 tests + 14 subtests; stage verification 278 tests + 92 subtests; original reporter 15 tests. These unchanged suites and the microscopy benchmark were not repeated for this continuation.

New work provides:
- A separate offline 488-only human review workspace, explicit blank decisions, per-neuron/day navigation, immutable automated QC, save/reload and source/display/manifest fingerprints.
- Strict private CSV/JSON validation and a dry-run status report. No annotation is converted into MANUAL_ACCEPTED or accepted measurements.
- A frozen versioned selection manifest, independent of documentation edits, preserving the original panel and exclusions.
- Publication safeguards and configurable legacy transfer paths; detailed image-derived receipts are now private, with public fingerprint references.

Use [REVIEW_VALIDATION_README.md](REVIEW_VALIDATION_README.md) for executable commands. The new workspace and readiness/failure summaries remain outside Git. Completed source images, arrays, benchmark outputs, blank old template and gallery are untouched.

Final focused validation: **98 tests plus 7 subtests passed**, JUnit 105 executions with zero failures/errors/skips. Scoped Ruff and Node syntax/logic checks passed. The new real blank workspace binds 326 source/display files, has 108 unreviewed observations, and yields six QC_BLOCKED / six REVIEW_PENDING statuses. It reads no 561 arrays. Original panel reconstruction passed without reading registered stacks. Browser automation could not open local-file URLs under the tool policy; no browser-rendering smoke pass is claimed. See [REVIEW_SOFTWARE_CHECKS.json](evidence/REVIEW_SOFTWARE_CHECKS.json).

## Scientific limits

No independent human decisions have been entered by Codex. Software checks cannot authenticate reviewer expertise or independence. Identity accuracy, contamination rate, identity-switch frequency and biological discovery remain unestablished. All radius/area/LUT alternatives stay unadopted; original area=180/radius=60 geometry is unchanged.

Missing raw detector images, correction fields/provenance, original tile placement and historical registration evidence remain unavailable. Exact N012 packet identity/source and other pending decisions still need source evidence. An eligible matched-well cohort is not available.

## Publication and retained history

The owner subsequently authorized a **software-only squash merge of PR #9** after fresh verification. Human annotation is not a prerequisite for merging infrastructure; it remains required for scientific release. Fresh full regression at checkpoint `2e70f59ce09ba11b715bf337304c9cb6a37f0a9f` passed 616 tests plus 135 subtests, with zero failures/errors/skips. Additional isolated UI-state and future-panel-freezer tests passed; shared production processing was not changed. See [SOFTWARE_RELEASE_20261028.md](SOFTWARE_RELEASE_20261028.md). Merge state/SHA must be verified against GitHub, not inferred from this note.

Public technical aggregates are intentionally limited to the user-declared checkpoint counts. Detailed historical receipts and case observations were preserved byte-for-byte privately before replacing public copies with fingerprint references. See [PRIVACY_AUDIT.md](PRIVACY_AUDIT.md). A normal cleanup commit does not erase earlier public commits.

See [SCIENTIFIC_RELEASE_BLOCKERS.md](SCIENTIFIC_RELEASE_BLOCKERS.md) for remaining gates.
