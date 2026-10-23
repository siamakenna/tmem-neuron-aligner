# Validation evidence and scope

Source baseline: 4ce8f9446ceea022ec5f989109f1acb47269c3b3 (main, PR #7 merged).
New work branch: validation/friday-independent-completion-20261023.

Prior Mac validation is accepted as the user's completed result: **340 repository
tests +49 subtests**, including Node. The private log/environment records were
not imported and unchanged tests were not rerun. No new baseline accuracy claim
is made. The environment installation already initiated before that steering
completed; it was used only to test new additions.

New validation is restricted to test_matched_analysis.py and
test_scientific_figures.py plus scoped lint, CLI checks and visual inspection.
The new suite passed 52 tests in 87.15 seconds. Eight affected figure tests were
then rerun after a visual refinement; these are not additional unique tests.
Scoped lint passed on all seven added Python files. See TEST_RESULTS.csv.
Test data
are small, deterministic synthetic uint16 crops processed through the existing
review builder/exporter with explicit automated software-test review labels.

Checks cover well/pair weighting with unequal neuron counts, exact paired
arithmetic, Day8 change, missing/nonaccepted visit preservation, undefined SD,
invalid quantities/conditions/statuses, conflicting accepted status, duplicate
bundles, technical row rejection, known exclusions, source/render/config/export
tampering, failed automated QC, synthetic-to-real relabeling, non-overwrite,
output fingerprints, plot gaps/status counts and survival blockade.

The figure demo uses production registration, segmentation and phenotype
functions on deterministic fixtures. It is a bounded plotting integration,
not a repeat of the completed stress suite. It illustrates a known segmentation
failure honestly rather than tuning the detector. Files and code hashes are
recorded in local analysis_provenance.json/figure_index.json. Historical
fixtures/reports were not overwritten.

Software correctness, synthetic numerical accuracy, real-image registration
quality, human-annotation segmentation accuracy and same-neuron identity
confidence are separate claims. Only the first two can be illustrated without
additional validated real evidence. No new real-image accuracy, survival,
physical stitching, rupture or fibril inference is reported.
