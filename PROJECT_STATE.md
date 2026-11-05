# TMEM106B longitudinal — verified state, 2026-11-05

Owner: Makenna Rodriguez. Goal: reproducible original-ND2 longitudinal analysis with inspectable image intermediates, authentic well assembly, tests and a clear presentation. Requested deadline: end of day; user timezone America/New_York. Default new-service budget: $0.

Audited GitHub main: 47a2db795133e4b6a79baf5d5f3b36855d857dec. Fetch again before any publication. Cloud materialization is a SHA-verified source snapshot, not a Git clone. No new commit or push from this session is verified; the connected integration rejected source-tree writes with HTTP 403.

## Current capabilities and proof
- Current source contains LUT rendering/box proposals, trace observers, segmentation/tracking diagnostics, flowchart exports and well assembly. See tools/full_dataset_v2/SOURCE_REVIEW.md and EVIDENCE.md.
- Added tools/full_dataset_v2: original-ND2 inventory, explicit axis/channel/site contracts, source-bound resumable receipts, actual-function adapter, serial/two-worker pilot, well assembly planning and Swarm generation gates. These additions still need verification/push from the Mac.
- Existing source: 98 focused tests passed locally; new contracts: 49 passed normally and the same 49 passed through a symlinked temporary parent. These are fixtures, not original-data or biological validation.
- Actual C05 original-ND2 Day8/12 alignment preview evidence is available. Separate real registered J05_N015 nine-visit segmentation/tracking stages are available from the October27 archive. Their source histories are distinct and are not a replay of one raw-to-tracking sample.
- Private PowerPoint: TMEM106B_actual_images_and_workflow_20261105.pptx in the recovery package. Native presentation editing rejected C05 image references, so the downloadable deck is the intended deliverable; do not treat the partial online draft as complete.

## Immediate blocker / exact session
Mac session: $HOME/Downloads/tmem_finish_1KkiKJ3Z
Checkout: results/publication/source
Branch: completion/full-dataset-v2-20261105T165938Z-bc25f12f
Logged HEAD: 47a2db7. The first test command stopped with 48 fixture setup errors before a commit, push, inventory or new original-image processing.
Reproduced root cause: macOS /var aliases /private/var; fake ND2 fixture keys used an unresolved temporary path while inventory read its resolved path. Fixed only the fixture to use Path(self.tmp.name).resolve(), with an explicit regression for symlinked temp directories. Production validation is unchanged.

## Data and scientific limits
Original February folder was observed under Desktop/260213_Feb16recopy_HYdiff_landingpadlines_survival_384well1; Documents is another supplied candidate. Verify the path on this device. Entire February inventory, authentic cross-day site matching, stage geometry, actual IC calibration, all-site real pilot and independent Cell Paint data remain unverified. P=1 does not establish whole-well coverage. Reported 192 wells ×9 visits +192 BF is a target, not a newly verified count. No new biological acceptance or inference is authorized by these diagnostics.

## Next handoff
Read TASK_CARD.md and run the small Mac recovery in the existing session. Done: tests pass on this Mac, explicit source/doc diff pushed on the preserved branch, remote SHA matches, logs recorded. Then perform one real source-bound data pilot after authentic acquisition evidence is available.
