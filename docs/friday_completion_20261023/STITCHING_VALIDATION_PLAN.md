# Real stitching validation after evidence intake

From the source checkout, with genuine private input files:

```bash
python scripts/assemble_tmem_well.py --tiles tiles.csv --geometry well_geometry.json --well J05 --day 8 --out NEW_J05_DAY8_ASSEMBLY
python scripts/register_tmem_well.py --visits visits.csv --well J05 --out NEW_J05_REGISTRATION
```

Repeat assembly for each required well/day using its reviewed geometry. The
visits CSV refers to the actual new assembly directories, with exactly the
requested chronological visits. Use fresh output names. Memory guards are
part of these commands; request appropriate resources rather than processing
a full plate locally.

Before registration, inspect well_cyx.ome.tif, coverage_yx.tif, geometry.json,
provenance.json and diagnostics.json. Coverage gaps block registration. Verify
the arithmetic mean in overlaps against original pixels; inspect seam errors
and boundary-neuron support. Placement order must follow verified coordinates,
not filename order. Wrong coordinates can make a plausible mosaic; source
landmarks are necessary to establish correctness.

The assembler does integer placement and arithmetic overlap averaging. It does
not infer orientation, optimize global matching or perform subpixel stitching.
Reversed axes, duplicate placements, gaps and calibration rejection are covered
by prior software checks; those unchanged tests are not repeated in this turn.
Real calibration/orientation accuracy remains unverified without genuine inputs.

Registration checks common geometry/IC/coverage, uses 488, and reports shifts,
reference history, overlap and correlation. Inspect every QC failure before any
candidate work. Newly assembled coordinates invalidate historical atlas anchors.
