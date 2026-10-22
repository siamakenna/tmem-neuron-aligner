# TMEM106B current implementation and verification scope

This guide replaces the earlier v1 setup instructions. Use a generated handoff's
top-level `CLAIRE_README.md` for exact portable commands. Its `index.html` links
current review, real-data evidence, test reports and source/environment records.

## 1. Unit tests and small integrations

`scripts/run_claire_verification.py` is the portable entry point. It checks the
package manifest, records the environment and exact source, runs **all current
tests**, generates synthetic stage evidence, and checks expected rejection of a
pending export. It works without `.git`. The shell wrapper
`scripts/run_claire_audit.sh` delegates to this runner.

Use a new output outside the immutable packet. Missing dependencies and failed
assertions fail verification. The pending-export check expects exit 2 with no
accepted metrics CSV. Its handled rejection does not fail the full runner.

The previous v5 run passed 270 tests and 30 subtests. It remains historical
evidence. Current v6 reports record the new implementation separately. Source
hashes identify modified files; a base commit alone cannot identify a dirty
worktree or a portable source snapshot.

## 2. Preprocessing, IC and alignment evidence

The runner calls the deterministic synthetic stage command:

```bash
python scripts/run_tmem_audit.py synthetic --out /path/to/NEW_OUTPUT_DIRECTORY
```

It writes separate PNG/JSON stages for preprocessing, alignment, phenotype and
stitching. IC means illumination correction here. The current operation order is
dark subtraction with negative clipping, flatfield division, optional
rolling-ball background subtraction and one final uint16 quantization.
Synthetic exact results verify software and do not establish physical accuracy.

The real evidence records the completed raw baseline and empirical IC comparison.
Raw registration remains the reference. IC sensitivity changed N05 Days 36 and
39 shifts by (-1,+6) pixels without improving their reported correlations.
Whole-image statistics do not establish local neuron-level impact.

Alignment inputs, shift signs, transforms and common overlap are explicit. The
identity/alignment input is channel 2 (488). Channel 1 (561) receives the same
transform and never determines it.

## 3. ROI and phenotype intermediates

The current workflow retains the existing 128 by 128 crop, 488 adaptive masks,
roughly 60% longitudinal consensus identity core and 2-pixel phenotype dilation.
The review exposes adaptive masks, core/ROI geometry and stored stage diagnostics.

Phenotype intermediates retain background support, corrected intensity, signed
DoG, threshold candidates, filtered puncta, object labels and diffuse support.
Resolved parameters record actual constants and exact filter boundaries. Do not
silently add a different phenotype implementation's upper-size filter.

"Raw 561" in this review means the registered crop before local phenotype
background correction. It does not mean untouched ND2 pixels.

## 4. Display LUTs and bounding boxes

Scientific arrays and geometry do not depend on display limits. The documented
interpretation of "bounding box constrained by LUT ranges" is a fixed
488-derived crop shown with explicit intensity limits. A lab-specific spatial
convention would require a separately reviewed specification.

The review shows fixed longitudinal reference and candidate LUT ranges, sources,
scope and clipping counts. Display clipping does not indicate acquisition
saturation or alter quantitative intensity values.

Fresh v6 reviews bind source evidence and exact displayed assets/configuration.
Modified or stale images, LUT settings or source arrays block export. Old v1
approvals cannot approve the new workspace.

## 5. Independent stress review

`claire_stress_cases.csv` maps cases to fixtures, commands/tests, expected outcomes
and artifacts. The handoff copies it to a blank `stress_results.csv`. Human
observations and reviewer names stay empty until executed. Classify actual
failures as expected/handled, a new bug, a new QC condition, a scientific
limitation, or a visualization-only issue.

Synthetic low-signal, large-shift, mask, display and tile checks establish only
their stated software conditions. Missing original microscope inputs are
`blocked_missing_real_input`, not passing validations.

## 6. Per-FOV, whole-well and per-neuron operations

| Scope | Operation and validation boundary |
|---|---|
| Per original FOV | Axis/channel inventory and reviewed camera-coordinate correction. Original orientation and calibration require acquisition evidence. |
| Per well/day | Explicit-coordinate CYX assembly with coverage and seam diagnostics, common origin and geometry. Synthetic reconstruction does not validate historical microscope stitching. |
| Per well time series | 488 longitudinal registration and common-overlap geometry. Do not reuse old atlas anchors on newly assembled mosaics. |
| Per candidate neuron | Existing 488 anchors, crop/mask review, phenotype decomposition and evidence-bound metric export. |

The assembler preserves channels, uses integer placement and arithmetic overlap
averaging, and reports coverage/seams. It does not implement subpixel alignment,
global optimization, feathering or automatic orientation. Original orientation,
overlaps and boundary-neuron behavior remain blocked without source tiles and
metadata.

## 7. Acceptance and biological inference

Review all nine 488 identity/ROI visits before 561 phenotype QC. Use the actual
reviewer name and explicitly accept/exclude. F05_N025 remains a known exclusion
despite a historical automated soma-screen PASS. Uncertain decisions stay pending.

Export checks source/rendered fingerprints, manual criteria, known exclusions
and automated QC before copying accepted source measurements. It does not
approve inference. These examples all come from TMEM106B wells. Final analysis
requires a validated cohort from all six wells and three matched biological
replicate pairs. The working slideshow records the remaining validation limits.
