# Inputs, outputs, parameters and rationale

## Interfaces

| Entry point | Inputs | Outputs and purpose |
|---|---|---|
| `scripts/run_terminal_completion.py` | New output folder; optional explicit original ND2 pair / selection or genuine well manifest | Machine-readable software/data status, phase logs, rendered designs, Claire packet and applicable real-image evidence. Run `--help` for the exact interface. |
| `tmem_align.nd2_tools.extract_nd2_selection` | Original ND2; explicit P/T/C/Z selections where required; memory limits | OME-TIFF with explicit remaining axes. It is extraction, not proof of whole-well acquisition. |
| `scripts/trace_tmem_pipeline.py raw-pair` | Explicit CYX arrays; optional detector-coordinate NPY flatfield, documented dark offset and background radius | Per-stage numeric arrays, previews, parameters and provenance for preprocessing and 488 translation. |
| `scripts/trace_tmem_pipeline.py registered-track` | Explicit TCYX registered stack, master table and neuron ID | Existing-anchor segmentation/tracking/phenotype diagnostics. Historical raw IC/stitching cannot be recovered from a registered stack. |
| `scripts/trace_original_nd2_well.py` | Strict original ND2 manifest, all intended observations, authentic geometry, channel and IC evidence | Explicit original extraction, detector preprocessing, well/day assembly, coverage and longitudinal registration evidence. Invalid templates stop before claiming a well. |
| `scripts/render_pipeline_flowcharts.py` | Output folder; optional verified StageTrace | Actual SVG/PNG design diagrams and available recorded preview panels, with unavailable stages labelled. |
| `scripts/package_claire_stress_tests.py` | Output location and actual source tree | Compact software stress request, test instructions, source hashes and a results form. No delivery claim. |

## Trace granularity

Detector preprocessing exposes raw input, float dark subtraction, the actual flatfield divisor, corrected floats, optional background estimate/subtraction, and final numeric conversion. Alignment exposes estimation images, masks, shift and transformed support. Segmentation exposes normalization, smoothing, threshold candidates, morphology, labels, component scores and selected masks. Tracking exposes the template, search window, correlation surface, competing peaks and displacement. Phenotype stages remain separate from 488 identity/ROI decisions.

All array comparisons must keep coordinate frames, channel order, units and display LUTs explicit. Float results and support masks are not interchangeable with display PNGs or zero-filled missing regions.

## Tunability

| Setting | Existing example | Why it matters |
|---|---|---|
| Tracking search radius | 40 / 60 / 80 px | A wider window can select another soma. Record identity changes and competing peaks, not only score. |
| Segmentation minimum area | 140 / 180 / 220 px | Tests sensitivity to small components and neuron/neighbour merging. |
| Consensus fraction | 0.6 | Controls longitudinal 488 support; it is not a per-visit identity verdict. |
| Core area / dilation | 80–2500 px / 2 px | Separates identity support from phenotype sampling geometry. |
| Registration maximum shift | 256 px | A software guard; exceeding it is a failure, not a reason to silently expand it. |
| LUT low/high | 0 / 4095 in example config | Display choices, not calibrated physical limits for every uint16 acquisition. Declare appropriate limits for real comparisons. |
| LUT range policy | `visible` or `within_range` | `visible`: pixel > low, including clipped-high pixels. `within_range`: low < pixel <= high. |
| LUT box padding / min area | 2 px / 20 px | Controls a connected-component viewing proposal within the search bounds. No ROI adoption follows automatically. |

`configs/tmem_stage_diagnostics_within_range.json` is an explicit example of a box constrained by both LUT limits. It does not replace the default config or change measurement geometry. The replaceable visualization extension is `render_preview(image, lut, bounds=..., overlays=...)`; quantitative arrays are not modified.

## Original-pair boundaries

Use two fluorescence acquisitions from the same intended well at specified visits. The runner checks reported dimensions/channel order and selection indices. Reported channel names alone cannot settle contradictory excitation metadata. Without valid correction evidence, IC is explicitly skipped and the comparison remains a diagnostic original-field alignment. Whole-well interpretation requires the separate geometry/coverage contract.
