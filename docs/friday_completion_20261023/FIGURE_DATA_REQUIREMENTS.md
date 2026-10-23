# Figure inputs and scientific limits

All image panels use pixels. A physical scale bar requires independently reviewed
calibration. Large image panels, explicit labels and PNG/PDF exports are provided.
Future real-image callers must carry exact source/fingerprint references; a
string label by itself does not establish human review or scientific validity.

1. Registration API: finite reference/moving/aligned 488 YX arrays of identical
   dimensions; QC with registration_channel=488, finite dy/dx/overlap_fraction,
   QC status and source reference. Shared reference-derived display limits.
2. Segmentation API: finite 488 image, bool detected mask, matching comparison
   mask. Real mode requires manual_mask={mask: bool_YX, evidence: source_ref}.
   A synthetic construction mask cannot be called a human-reviewed mask.
   Neighbor/boundary failures must remain visible, not retuned away.
3. Tracking: verified neuron_longitudinal.csv including all nine expected days,
   status/reason/source and quantities only for accepted visits. NaNs break
   lines. Status markers occupy a separate axis, never an invented intensity.
4. Phenotype API: registered raw561 plus bool matching stages
   01_phenotype_roi, 02_background_mask, 06_size_filtered_puncta,
   08_diffuse_support. The latter two must partition the fixed ROI. This is a
   computational decomposition, not proof of rupture/fibrils. Acquisition
   saturation and display clipping are different quantities.
5. Matched wells: all six well/day summaries, actual accepted neuron counts,
   paired eligibility and missing-data warnings. Biological replication is
   wells/pairs; n annotations count neurons only. No pooled neuron error bars.
6. Survival: patient/cell identity, observation and event times, confirmed
   fate evidence, reasons for loss, censor time/status and cohort entry rules.
   No curve until a separately reviewed survival specification exists.
7. QC: complete expected cohort ledger, mutually exclusive observation statuses,
   exclusion reasons and separate fate classifications. Denominator is declared
   neuron-visits; absent wells are warnings, not invented unobserved neurons.

The analysis provenance contains input/output/code hashes. Plot generation
revalidates it against live source evidence before writing files. Retain all
private arrays/workspaces to reproduce real plots; moving them requires updating
the manifest and generating a new provenance record.
