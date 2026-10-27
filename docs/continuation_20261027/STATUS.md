# TMEM106B continuation status — October 27, 2026

## Current local checkpoint — complete package

The complete package has now been verified locally, without NIH/Biowulf access. All 230 package hashes and 222 archived source hashes matched before edits; no required dataset files are missing. The frozen master has 3,897 rows; six registered uint16 TCYX stacks each contain nine visits (days 8, 12, 16, 20, 25, 29, 32, 36, 39). The dataset verifier checked seven files totaling 1,985,842,849 bytes. Raw detector inputs and IC fields remain absent.

A fresh Python 3.12.5 environment was installed from requirements-portable.txt outside Git. Fresh portable controls passed **58 tests plus 14 subtests**. Fresh stage verification passed **278 tests plus 92 subtests**, zero failures/errors/skips; these Mac results are separate from the historical Biowulf record below. A new 488-only panel reporter has focused tests and generates large nine-visit contact sheets without modifying source arrays or benchmark traces.

The unchanged portable runner **completed all 12 cases in 875.748 seconds (14.6 minutes)**, using two workers, two candidates per well, a 35-minute outer limit and an eight-minute per-case limit. Software counts: **12 completed, 0 failed, 0 timed out, 0 deferred**. Frozen selection order: E05_N057, F05_N005, I05_N052, J05_N029, M05_N009, N05_N010, E05_N066, F05_N061, I05_N006, J05_N028, M05_N022, N05_N022. Selection used ID hashing and complete visit records, not 561 outcomes or valid-tracking optimization. N05_N022 retains its original failed Day39 tracking flag. This is a diagnostic panel, not held out or an accepted cohort.

Scientific diagnostic counts: **6 rejected, 6 pending independent review, 0 accepted**. There are **91/108 primary valid 488 track-visits**; all 17 invalid visits remain invalid. The stage inventory contains 39,099 executed records, 60 skipped, 48 unavailable historical records, and six recorded failure records—all six describe the same N05_N022 Day39 insufficient-signal failure at two recording levels across three area settings. These are not six software-case crashes or independent samples.

The new report completed on real outputs: 24 contact sheets (12 fixed-crop and 12 larger registered-search-context), a compact index, numeric comparison, processing flowchart and 108 blank source-bound annotation rows. Its final **15 focused tests** and targeted Ruff checks pass. All 12 actual 488 case sheets were inspected for provisional identity/ownership concerns. Every automated secondary-soma screen passed; that does not reverse the image concerns or failed visit gates. See [LOCAL_REVIEW_HANDOFF.md](LOCAL_REVIEW_HANDOFF.md) and [LOCAL_RESULTS.json](evidence/LOCAL_RESULTS.json).

Local evidence is in sibling directories `../verification-local`, `../benchmark-local`, and the environment/log files beside this repository. Source base was verified live at a978ac54c943d5e28a01a4d92fa989b6e4760684; main at cbed28cef77826cd8a5b45b6520fa81b127b3bfa. Work is isolated on `continuation/six-well-local-20261027`. The source ZIP omitted Git metadata and 225 tracked paths; these omissions are not staged as deletions. Older incomplete-package recovery edits remain in their separate checkout.

The source/measurement master and primary configuration remained unchanged. All radius, area and LUT-box proposals remain unadopted. Accuracy improvement, independent boundary ownership, raw IC/alignment validation and an accepted matched-well cohort remain unestablished. Local logs, arrays, images, environments and galleries are outside Git. The final publication receipt is retained beside the repository after push/remote-SHA verification; no merge is authorized.

The sections below describe the **historical packaging checkpoint**, not current local completion.

The processing instrumentation and its Biowulf verification completed. The returned evidence records a successful push of commit `a978ac54c943d5e28a01a4d92fa989b6e4760684` to branch `diagnostics/stage-trace-20261027_n9oz6u94` in `siamakenna/tmem-neuron-aligner`. This statement comes from the returned push receipt and command log; it is not a new live GitHub query. The receipt does not establish that a pull request was created or merged.

The current priority is to make the work usable on another device without NIH access, then run a bounded diagnostic panel across all six available wells. Code and documentation can travel through GitHub. Image data and generated image reports travel separately.

## Completed and verified

- [x] Save small numeric intermediates, previews, operation parameters, ancestry, and explanations for preprocessing, IC, alignment, segmentation, ROI construction, tracking, and phenotype decomposition.
- [x] Add fixed-LUT previews and 488-derived viewing-box proposals with explicit non-adoption states.
- [x] Add parameter validation, sensitivity comparisons, I/O documentation, and processing flowcharts.
- [x] Complete Biowulf verification: **278 tests plus 92 subtests**, with zero failures, errors, or skips. The unit phase contains 55 tests plus 31 subtests; integration/regression contains 223 tests plus 61 subtests.
- [x] Recover the known synthetic alignment shift `[-4, 6]` pixels. The maximum synthetic IC rounding error was approximately 1.214 ADU.
- [x] Execute three real registered-track diagnostics: E05_N006, F05_N007, and J05_N015, each across all nine visits.
- [x] Return 9,633 executed intermediate stage records, 24 skipped stages, and 12 unavailable historical stages across those three diagnostics.
- [x] Push the tested instrumentation commit to the branch above.
- [x] Record the concrete tracking and segmentation sensitivity findings in [FINDINGS.md](FINDINGS.md).

## Pending execution or evidence

- [ ] Copy the frozen master and six registered stacks to the device that will continue the analysis; verify the transfer receipts and inventory.
- [ ] Run the portable benchmark across E05, F05, I05, J05, M05, and N05 using a declared selection rule and bounded time budget.
- [ ] Record which tracks completed, failed, timed out, or were deferred. A deadline is not evidence that deferred cases passed.
- [ ] Review identities and ROI ownership using the actual images and saved intermediates. Compare errors against a frozen baseline.
- [ ] Validate real-image IC and alignment before/after using matching raw detector-coordinate images and correction fields. Already registered stacks do not supply this evidence.
- [ ] Verify the new portable changes locally, commit the exact intended files, push, and retain the new commit/push receipt.
- [ ] Create or update a pull request if needed. Merge status remains unverified until checked on GitHub.

The checkboxes above describe evidence at packaging time. New portable code, notes, and benchmark results remain pending execution/push until their own recorded receipts say otherwise. The existing instrumentation push does not imply that these later files are already on GitHub.

## Scientific status

The three diagnostic executions retain `real_accepted_ids=[]`, `production_eligible=false`, and `scientific_inference_ready=false`. They do not create a newly accepted biological cohort. J05_N015 remains a technical reference; its historical technical use does not make it a newly approved experimental replicate.

The six wells correspond to three well pairs: E05/F05, I05/J05, and M05/N05. Neurons are nested within wells, and repeated visits or intermediate images do not add independent biological replicates. Acquisition settings, digital range checks, and registered-stack diagnostics do not independently establish physical calibration or historical stitching correctness.

## Evidence locations

- Original returned packet: `TMEM106B_stage_implementation_results_20261027.zip`.
- Packet SHA256: `297e049cb7db0e6d93446a86dc7cdb9a83f53b910233ebc11e8f9c99ba0819bd`.
- Returned run: `18_tmem_stage_implementation_20261027_n9oz6u94`.
- Returned receipt: `PUSH_RECEIPT.json`; push command result: `git_push_attempt.json`.
- Verification: `verification_results.zip`, containing JUnit XML, logs, and `verification_status.json`.
- Per-case evidence: `<neuron_id>_results.zip`, containing `trace/summary.json`, `trace/manifest.json`, `trace/tracking_comparison.json`, and `trace/parameter_sensitivity.json`.
- Existing pipeline guide: [PIPELINE_GUIDE.md](../diagnostics_20261027/PIPELINE_GUIDE.md).

## One-hour execution order

1. Preserve the code, evidence packet, and data transfer inventory before leaving NIH access.
2. Start the bounded portable benchmark once its required inputs are present. Keep original anchors and settings frozen.
3. Use the remaining time for result review and the explanation of what changed and why.
4. Commit and push code, compact summaries, and Markdown notes. Keep large data, environments, and generated galleries outside Git.
5. Continue from [CODEX_NEXT.md](CODEX_NEXT.md) on the other device. If the deadline arrives, preserve an explicit partial status and the last verified push; do not turn unfinished work into a completion claim.
