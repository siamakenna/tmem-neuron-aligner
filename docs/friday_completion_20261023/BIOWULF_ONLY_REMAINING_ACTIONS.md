# Minimal Biowulf checklist

Use the existing validated environment and source checkout. Do not repeat the
completed Mac baseline. The missing work is supplying genuine evidence, reviewing
the cohort and running real inputs. No new code development is expected for the
descriptive analysis path.

1. Bring the reviewed PR source onto the Biowulf checkout. Import private
   decision packets and their manifests, not public substitutes. Resolve N012's
   full packet identity and the three flagged N05 cases. Preserve J05 technical
   rows and all current exclusions. Record decisions in decision_policy.json
   with evidence_files entries `{ "path": "original_decision_file", "sha256": "actual_sha256" }`.
   Do not manufacture reviewer names or clear pending fields without evidence.

2. Only if starting from original acquisitions, provide actual tiles.csv,
   well_geometry.json and visits.csv using the intake templates. Review physical
   calibration/orientation/common origin and tile support before running:

   ```bash
   python scripts/assemble_tmem_well.py --tiles tiles.csv --geometry well_geometry.json --well J05 --day 8 --out NEW_J05_DAY8_ASSEMBLY
   python scripts/register_tmem_well.py --visits visits.csv --well J05 --out NEW_J05_REGISTRATION
   ```

   Repeat with genuine well/day identities. Use fresh anchors for new mosaics.
   If working from existing immutable curated packets, do not unnecessarily
   rebuild or replace them. If new curated packets are needed, inspect
   `python scripts/render_curated_neuron_phenotypes.py --help` and use the
   documented actual atlas-root/output-root and reviewed parameters. Dataset
   paths and new candidate identities must come from the genuine source.

3. Set private input paths (these must exist) and a fresh output root:

   ```bash
   tmem_curated='/replace/with/immutable/curated'
   tmem_config='/replace/with/exact/review_config.json'
   tmem_run='/replace/with/NEW_ANALYSIS_RUN'
   mkdir -p "$tmem_run"
   python scripts/build_review_workspace.py --curated "$tmem_curated" --config "$tmem_config" --out "$tmem_run/workspace"
   ```

   Open workspace/review/index.html locally through the established review
   workflow. Complete actual all-nine 488 identity/ROI review, then 561 phenotype
   review. Download the actual manual_review.json into the private run directory.
   Existing approvals cannot approve modified source/display evidence.

4. Export using those exact inputs and a new export directory:

   ```bash
   python scripts/export_reviewed_metrics.py --curated "$tmem_curated" --reviews "$tmem_run/manual_review.json" --config "$tmem_config" --workspace "$tmem_run/workspace" --out "$tmem_run/export"
   ```

   Exit 2 means no accepted export; inspect review_verdicts.json and any
   automated_qc_block.json. Do not relabel technical rows or fill failures with
   zeros. Repeat independently for other cohort bundles as needed.

5. Copy analysis_inputs.template.json, cohort_status.template.csv and
   decision_policy.template.json to the private run as analysis_inputs.json,
   cohort_status.csv and decision_policy.json. Populate all actual bundles,
   expected neurons/visits, conditions, statuses, reasons and source references.
   Bind current exclusions, technical and pending cases. Then:

   ```bash
   python scripts/analyze_matched_wells.py --inputs "$tmem_run/analysis_inputs.json" --out "$tmem_run/analysis"
   python scripts/generate_scientific_figures.py --analysis "$tmem_run/analysis" --out "$tmem_run/figures"
   ```

   Review analysis_warnings.json, per-well/pair counts and QC reasons before
   discussion. Real registration/segmentation/phenotype image panels need their
   separate arrays/masks/evidence; the CSV pipeline cannot supply them.

6. Supply independently documented fate/event/loss/censoring records before
   requesting survival analysis. Keep disappearance, uncertainty and technical
   failure distinct from confirmed death. Supply orthogonal biology before
   claiming rupture or TMEM106B fibril accumulation.
