# Terminal completion against November 3 main

Base source: `72c7ee058075af0e2c40b5ca0e909780967f502e`. The uploaded 377-file source archive matched its SHA256 receipt and Git archive commit marker. This is a source inspection, not independent confirmation of private Mac execution receipts.

| Requirement | What exists / changes in this continuation | Execution and validation |
|---|---|---|
| Unit → integration checks | Existing `verify_stage_pipeline.py`; new Terminal runner records phases, failures and environment | Run against the applied source on the Mac. Local results and unavailable dependencies are listed in `TEST_RESULTS.md`; historical totals are not added. |
| Small numerical and visual intermediates | Existing `StageTrace`, preprocessing, alignment, segmentation, tracking and phenotype diagnostics | Saved stages carry parameters, parents, checksums, reasons and previews. Missing stages remain missing. |
| Original ND2 inputs | Existing explicit extraction plus new original-pair/whole-well execution entry points | Real pixel reads require original files on the execution device. This source archive contains none. |
| ND2 position/time/Z handling | Legacy implicit selection now fails before reading a multi-observation array | Explicit `extract_nd2_selection` remains available. A single-plane legacy route must not silently select P0/T0 or project Z. |
| Duplicate well/day handling | Batch selector now rejects duplicate fluorescence observations | Multiple FOVs must enter the explicit whole-well route; a later file may not overwrite an earlier one. |
| LUT visualization / box | Already implemented `render_preview` and `propose_lut_bbox`; explicit two-sided-range example added | Display-only proposal. `visible` includes saturated pixels; `within_range` uses both intensity limits. Neither adopts a measurement ROI. |
| Graphic flowcharts | New executable SVG/PNG renderer with optional verified StageTrace images | Design diagrams are generated; image-backed panels require real traces. A diagram alone does not prove execution. |
| Whole-well stitching | Existing `assemble_tmem_well.py`, `register_tmem_well.py` and `audit_v1/stitching.py`; original-ND2 route now links to them | Reported independent whole-well validation remains **0/54**. Authentic coverage and geometry are still required. |
| IC before/after | Existing trace saves raw, dark subtraction, field/division, background and quantization separately | No matching historical flat/dark calibration is supplied here. Uncorrected diagnostics may run; measured IC validation remains blocked. |
| Parameter robustness | Existing declared segmentation and search-radius sweeps; new guards and runnable stress packet | Preserve failures and source bindings. Higher correlation is not improved soma identity. |
| Claire stress tests | New compact source-bound packet with commands and results form | Prepared locally by the runner; not sent and not independently executed by Claire. |
| Documentation / I/O / rationale | This directory and existing diagnostic guide | Includes concrete software improvements, supported findings and missing scientific evidence. |
| GitHub publication | Companion Mac launcher creates a separate branch, runs checks and verifies a push | No new GitHub push occurred in the authoring session. A verified remote SHA must come from the Mac run. |

## What knowledge has actually improved

Two source-level failure mechanisms are now explicit and tested: ambiguous ND2 observations could be silently reduced, and duplicate well/day entries could be overwritten. These corrections improve data preservation and interpretability; they are not a new biological finding.

Earlier private work reports nonempty common support for all six anchored field series and no nine-visit common support for F05 with `to_first`. This is a method-sensitivity observation from the supplied checkpoint, not a newly executed comparison or independently established registration accuracy. The previously reported 17 failed primary visits and zero accepted tracks remain visible.

## Scientific prerequisites that code cannot supply

Complete well/site membership, correct optical channel mapping, physical calibration, stage/camera geometry including any off-axis component, matching correction fields and independent identity/ownership evidence remain required. Original files being available on both devices resolves file availability; it does not supply these facts. Automated review must retain its actual provenance and cannot be relabelled as a human decision.

Use the run's private `RUN_STATUS.json` and command logs for actual local outcomes. A blocked scientific stage does not erase completed software work, and a passing software test does not clear a scientific gate.
