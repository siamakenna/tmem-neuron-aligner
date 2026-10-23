# Original-acquisition intake

Complete this package from genuine microscope records. The new
acquisition_well_geometry.template.json intentionally leaves unknown calibration
and geometry null/empty and cannot authorize assembly. Existing historical
templates/reports are preserved. Do not assume one FOV per well.

| Required field | Allowed value / source | Validation |
|---|---|---|
| Well, day, tile ID | Recorded acquisition identity and original metadata | Expected list exactly once per well/day; all nine visits accounted for |
| Image axes/channel order | Explicit CYX, reordered to 405/561/488 from verified channel metadata | Three finite nonempty planes; no intensity-based channel guessing |
| Tile dimensions | Original image headers, binning and crop metadata | Verify against acquisition record; differing dimensions need explicit valid coverage |
| x_px,y_px | Reviewed final-image integer top-left coordinates | Nonnegative, inside canvas; duplicate IDs/positions rejected |
| Stage origin/XY units | Original stage metadata and declared origin | Finite micrometers; distinguish relative from absolute coordinates |
| stage_xy_to_image_yx | Independently checked signed permutation matrix | Orthogonal signed axes; confirm asymmetric 488 landmarks, camera rotation and flips |
| Center vs top-left | Instrument convention and camera geometry | Convert centers to top-left explicitly before supplying integer placements |
| pixel_size_um | Independent calibration with instrument/objective/binning record | Positive finite number; reviewer/date/evidence required; no guessed scale |
| canvas_yx/geometry_id | Shared reviewed coordinate plan | Positive dimensions and same origin/orientation/canvas across visits |
| expected_tile_ids | Original acquisition manifest | Missing/unexpected/duplicate tile stops complete-well claim |
| coordinate_evidence | Private source reference for orientation/calibration decision | Nonempty traceable record; orientation_validated true only after actual review |
| ic_status | not_applied or applied_with_provenance | Consistent per well/day and across visits; calibrated correction needs sidecar |
| Overlap/coverage | Original adjacent FOVs and placement records | Inspect seam statistics and boundary neurons; gaps block registration |

Common pitfalls: mixed relative/absolute Z, centers mistaken for corners,
XY swapped with row/column, camera reflection, snake order guessed from filenames,
different per-visit crop origins, binning changing physical pixel size and
unrecorded exposure changes. Do not repair these by inventing metadata.

Across Days 8,12,16,20,25,29,32,36,39, verify identities, original tile list,
dimensions/channel mapping, common origin/canvas, camera convention/calibration,
IC policy and full support. Compare a boundary neuron in both adjacent original
tiles and the assembled image. Record actual reviews in the private evidence.

Header-only tiles.template.csv and visits.template.csv match the existing CLIs.
Populate only after review. See STITCHING_VALIDATION_PLAN.md for commands.
