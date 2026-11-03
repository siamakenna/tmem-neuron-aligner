# Where stitching lives and what it does

| Code | Role |
|---|---|
| `src/tmem_align/audit_v1/stitching.py::assemble_well` | Preserves CYX channels on an explicitly supplied canvas; arithmetic-mean overlap, uint32 coverage, seam differences and NaN missing support. |
| `src/tmem_align/audit_v1/stitching.py::stage_to_pixel` | Converts a verified signed-permutation stage/image convention to integer YX offsets; returns rounding residuals. It is not an arbitrary affine transform. |
| `scripts/assemble_tmem_well.py` | One well/day from the full expected tile roster, explicit coordinate table and reviewed geometry. Missing, duplicate and unexpected IDs are rejected. |
| `scripts/register_tmem_well.py` | Longitudinal registration of assembled well/day inputs, with common support and channel-preserving transforms. |
| `scripts/trace_original_nd2_well.py` | Original ND2 extraction and detector preprocessing linked to explicit assembly/registration; retains source/selection/correction evidence. |
| `scripts/run_260213_all_wells_batch.py` | Legacy one-observation-per-well/day field route. It is not a tile stitcher; duplicate observations now require explicit resolution. |

## Coordinate limits

The current assembler accepts measured integer top-left tile offsets. Its stage helper requires a verified orthogonal signed-axis mapping. The supplied checkpoint reports a small off-axis camera term and absent pixel-to-stage transform. Rounding that term away or declaring a nominal grid reviewed would not validate the geometry. Use genuine measured placement/landmarks, or implement and test an appropriate measured affine/resampling model before applying it to those acquisitions.

An acquisition with one CYX frame may be one FOV, a crop or an already assembled field. It is not automatically a full well. Establish the expected site roster and boundaries from acquisition records, then run one evidence-complete pilot. Inspect overlap seams, boundary landmarks, coverage and physical scale independently before extending to the other well/day groups.

Nine-visit registration also changes coordinates relative to historical neuron anchors. Establish a source-bound mapping or re-localize anchors; do not reuse old anchors against a new mosaic merely because the well and day labels match.

## Status

The checkpoint's **0/54 independently validated whole-well mosaics** remains unchanged by this software continuation. Synthetic stitching tests establish software properties; original ND2 file availability, coverage counts and successful exit codes do not independently establish physical correctness.
