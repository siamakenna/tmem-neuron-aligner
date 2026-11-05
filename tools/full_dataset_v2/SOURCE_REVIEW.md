# Current-source review and practical next steps

Reviewed main: `47a2db795133e4b6a79baf5d5f3b36855d857dec`, November 5, 2026.

## What the inspection established

| Requirement | Current source / finding | Extension and remaining evidence |
|---|---|---|
| Unit → integration verification | 98 existing core/LUT/visualization/stage-trace/parameter/flowchart tests passed locally, with no failures, errors or skips. | 48 additional batch contract/integration tests passed. The full science adapter and full existing pytest suite still require the scientific environment; the launcher and CI run them. Software fixtures are separate from original-image validation. |
| Original ND2 and small intermediates | `preprocess_image` and `register_translation` already expose production observers. `pipeline_diagnostics` exposes actual segmentation/tracking internals. | The new worker observes those executed calls and saves per-visit arrays, bounded previews, stage ancestry, hashes and actual-image SVGs. Absent flat/dark calibration is skipped explicitly. No original ND2 file was present in the supplied workspace archives. |
| LUT visualization stub | `render_preview` is implemented, read-only and tested; `propose_lut_bbox` already supports connected components and range policies. | The worker adds same-image display-box comparisons. `within_range` uses `low < pixel <= high`, anchored support and an explicit spatial search. The proposal never adopts a measurement ROI. |
| Stitch real fields into wells | `audit_v1/stitching.py::assemble_well` preserves channels, uses supplied integer offsets and averages overlaps; unsupported pixels remain NaN. | A well task assembles every mapped site for each visit before registration. Genuine acquisition positions, camera orientation and landmark/calibration evidence remain required. Grid conventions and P counts cannot establish physical well coverage. |
| Scale beyond a few wells | The legacy batch CLI restricts `--max-sites` to one, picks channel indices from the first visit, and writes its primary aggregate tables at the end. | The new manifest worker explicitly selects every mapped position, remaps each file's metadata channels and writes independent durable receipts. Missing, failed, invalid and unprocessed slots remain visible. |
| Preserve current repairs | `plate_preflight.py`, `well_checkpoints.py` and `run_checkpointed_plate.py` strengthen the legacy boundary and preserve failures. | These shared modules are unchanged. The new path reads the frozen full-plate registration parameters instead of using older helper defaults. Additional unpushed device-local fixes still require reconciliation with the actual local source. |
| Tunability and robustness | Existing curated diagnostics declare their source constants and candidate sensitivity settings. | The new profile validates bbox/template/search/min-area bounds and records min-area and tracking-radius alternatives. Alternatives never rescue a failed primary result automatically. |
| I/O and optical understanding | Filename/header identity is not independent optical or physical-site authentication. | Every source records axes, named channels, dtype, voxel metadata when available, position indices, stat/inode identity and checksums. T/Z reductions, RGB, extra undeclared channels and inconsistent loaded shapes fail explicitly. |
| Soma tracking and biological claims | Tracking/mask functions exist; a technical QC pass does not establish biological identity. | Automatic exemplars remain candidates, not a neuron census. Registration, segmentation and tracking failures stay separate. Nonreporter phenotype is N/A; accepted identities remain zero. |
| External usability | No actual Cell Paint batch was supplied. | Five-channel extraction/reordering is covered by a fixture and a separate assay profile. Real Cell Paint axis/naming/geometry/model usability remains an independent test, not a second February run. |

## What is new knowledge versus engineering

The inspection identifies concrete scaling bottlenecks: implicit first-visit channel indexing, single-position delegation, end-only legacy table writing and an older registration default that differs from the reviewed plate policy. The extension makes those inputs/decisions inspectable and individually recoverable. These are software and provenance improvements. They are not biological discoveries or independently measured accuracy gains.

The next scientific evidence must come from the actual acquisition folder: a real all-site pilot, original/calibration before-after images, source-bound transformations, frozen failure counts, independent landmark/mask/identity references and a genuinely different assay batch. Measure the improvement against those references before claiming an accuracy or biological benefit.

## Execution order

1. Preserve/reconcile the existing full-plate run; do not duplicate its completed work.
2. Verify the actual current checkout and new adapter, then publish the source branch and inspect CI.
3. Inventory the entire original February folder and generate bounded real-image stage graphics.
4. Authenticate cross-day sites and real stitching geometry; run serial/two-worker all-site pilot with identical outputs and measured resources.
5. Process remaining declared well/site or well-mosaic tasks, reconcile every expected slot, and prepare the private collaborator packet.
6. Run and report the independent Cell Paint usability/accuracy assessment under its own channel/axis profile.
