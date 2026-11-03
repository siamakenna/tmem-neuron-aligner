# Original acquisition and scientific-readiness handoff

Run began November 2 and continued November 3, 2026. This supersedes the portable-only assumption that original acquisitions were unavailable. It does not retroactively validate historical stitching, correction or biological classifications.

## Genuine evidence established

- Located 1,920 local original ND2 containers. A metadata-only inventory read 1,931 image headers: 1,920 ND2 and 11 TIFF, with no header failures in the declared scope. No cluster transfer was initiated.
- All 54 target well/day groups have one filename-labeled fluorescence container. Their authentic headers report `CYX`, three 2868×2868 uint16 planes, named 405/561/488 channels, and a single acquired frame with no multi-site loop. Filename well/day labels are not independently verified plate-map identities.
- One original-field CYX extraction round-tripped through OME-TIFF with exact pixel equality, preserved dtype/channel order, and source/output/array hashes. This demonstrates non-destructive extraction, not complete-well coverage or optical wavelength accuracy.
- Executed new full-resolution, named-488 original-field registration comparisons using existing `to_first` and `anchored` implementations. Per-method/day QC, failures, timeouts, resumed attempts, numerical arrays, source bindings and before/after panels remain private. These are original acquired fields, not verified whole-well mosaics. No production default or historical atlas coordinate mapping changed.
- Preserved the completed 12-case neuron diagnostic benchmark, all primary parameters/masks/anchors and 17 failed visit gates. No completed gallery or registered-stack hash was rerun merely for reproduction.

## Experimental validation remains incomplete

**Whole-well assemblies independently validated: 0/54.** Source containers exist; the blocker is now geometry/completeness evidence, not an assumed missing ND2 transfer. A single detector field cannot be declared a complete well without the acquisition plan, expected tile inventory, orientation and boundary checks.

Metadata reports a small off-axis camera transform and no pixel-to-stage transform. The reported physical pixel size is not an independent calibration check. Named 561/488 channels have conflicting excitation metadata. These discrepancies must be resolved with acquisition records, not intensity guessing or rounded orientation assumptions. Original-container presence does not prove absence of on-instrument correction.

Authentic matching flat/dark fields and historical correction provenance were not located in the declared project folders. No historical IC field was reconstructed from registered stacks, and no new estimate was substituted for validation.

Numerical registration gates and correlation are image agreement, not tracking accuracy or proof of a plate-remount cause. Some original-field results fail support/QC, and interrupted runs retain their own records. Independent landmarks and whole-well geometry remain required before adopting transforms or reusing old neuron anchors.

## Human and biological gates

Scoped review/export searches found no completed source-verifiable human annotations or accepted exports in accessible project folders. This is not a claim that no external reviewer has a separate file. All 108 diagnostic observations remain pending; six tracks remain diagnostically rejected/QC-blocked and six pending. Verified accepted neurons: **0**; eligible matched well pairs: **0**.

Preserve F05_N025 and N05_N011 exclusions, J05_N015 technical-only status, N012 packet identity/source evidence and other unresolved N05 cases. Separate authentic final 561 review, all-nine-visit QC, current decision policy and cohort ledger remain mandatory. Wells/matched well pairs—not cells or repeated visits—are biological replicates. No treatment, survival, death, rupture or fibril claim is made.

## Verification and private handoff

New constructed software checks passed: **129 tests +11 subtests** in affected integration; **58 focused tests** including explicit ND2 selection, CYX preservation and memory/index guards. These are current software checks. Earlier full 616+135 and reconciliation 135+10 remain historical, not rerun claims. No shared image-processing implementation changed, so the full suite was not repeated.

The private acquisition execution folder contains source inventories, environment/command records, original-field receipts, failures and resumed attempts. The required final private handoff in `pi-handoff-20261102/` is generated from completed receipts after the bounded image jobs finish. At source-publication time those jobs and report generation may still be in progress; this document alone does not certify file creation. Required deliverables are:

- `FINAL_COMPLETION_STATUS.md`
- `ACQUISITION_AND_STITCHING_REPORT.md`
- `REGISTRATION_VALIDATION.md`
- `IC_VALIDATION_STATUS.md`
- `NEURON_QC_AND_REVIEW_STATUS.md`
- `MATCHED_WELL_READINESS.md`
- `PI_HANDOFF_BRIEF.md`
- `REMAINING_ACTIONS.md`
- `SCIENTIFIC_COMPLETION_MATRIX.csv`
- `WELL_DAY_ASSEMBLY_STATUS.csv`, `ORIGINAL_FIELD_REGISTRATION_QC.csv`, `FIGURE_INDEX.csv`, and `PRESENTATION_OUTLINE.md`.

Consult the final local publication checkpoint for the actual branch, PR state and verified remote/merge SHA once publication completes; no merge state should be inferred from this summary alone. Images, private paths, detailed image-derived measurements, annotations, galleries and execution logs are not published. The sanitized source tree does not erase historical public-branch exposure.

## Smallest remaining manual actions

1. Acquisition expert: confirm the field/tile plan and full-well extent, stage/image convention, calibration, channel settings and original correction state; provide authentic correction fields/provenance and boundary landmarks.
2. Researcher: complete the existing source-bound 108-observation 488 review, retain failures/exclusions and unresolved identities, then independently complete final 561 review where otherwise eligible.
3. Validate one evidence-complete whole-well pilot, extend only after its geometry/support passes, then establish a new-to-old coordinate mapping or re-localize anchors. Only genuine accepted exports may enter matched-well analysis and biological plotting. Independent fate/censoring is separately required for survival.
