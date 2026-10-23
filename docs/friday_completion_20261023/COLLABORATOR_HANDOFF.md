# Collaborator handoff

The software can assemble explicitly placed source tiles, align well visits
using 488, expose per-neuron masks/phenotype stages, bind manual review to the
exact source/display evidence, and export only tracks meeting its all-nine
manual/automated contract. This addition prepares descriptive analysis and
figures for a final accepted cohort.

The historical direct-to-Day8 path can become fragile after large late shifts
or remounting. The newer anchored path uses a validated reference history and
reports reference day, shifts, post-correlation, overlap and QC. It applies the
488-derived transform to 561. It does not independently align the phenotype to
make it resemble the reference. Review source commands in
`scripts/register_tmem_well.py` and `scripts/run_260213_longitudinal_pilot.py`.

488 establishes spatial structure for registration and candidate geometry.
It does not automatically prove longitudinal identity, purity of the region,
or cell survival. 561 is measured after geometry is fixed. Fixed display LUTs
do not alter measurement arrays. Puncta and diffuse intensities are a
computational partition; they do not alone prove lysosomal rupture or fibrils.

The review/export system checks source and rendered fingerprints, all required
visit judgments and automated QC. The new analysis checks those again, verifies
exported quantities against their source, and checks mask/crop consistency.
No gate substitutes for actual expert review.

Nine J05 fixed-region rows remain technical measurements. F05_N025 and current
N05_N011 remain excluded. The N012 current packet remains excluded for Day12
region/QC problems; its exact private packet identity must be imported. Three
other flagged N05 pairs remain pending. No new acceptance/exclusion decisions
were made here and no accepted six-well cohort was inferred from old reports.

The scientific comparison is E05/F05, I05/J05 and M05/N05. Neurons are repeated
measurements nested in each well. Well means and matched pair differences are
the biological summaries; each well/pair receives equal weight. Missing visits
and excluded tracks remain visible, and actual neuron/well/pair counts accompany
the outputs. Fewer available pairs stay explicitly incomplete and descriptive.

Original tile geometry, coordinate convention, camera orientation and physical
calibration still need acquisition evidence. Do not reuse old atlas anchors on
new mosaics. Before survival claims, obtain confirmed fate classifications and
censoring/loss records. Before mechanistic claims, obtain orthogonal validation.

For John's older dataset, first inventory channels, axis order, visits, tile
geometry, exposure/saturation metadata and pixel calibration. Explicitly map the
stable registration and phenotype channels, build a new coordinate system and
new review-bound evidence. Existing code provides reusable components; validity
on that dataset remains untested until its inputs are inspected.

Use BIOWULF_ONLY_REMAINING_ACTIONS.md for commands. The completed Mac baseline
is prior evidence (340 tests +49 subtests including Node, user reported); new
analysis/figure checks are recorded separately. No large/private data are in
this publication.
