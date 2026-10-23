# Matched-well descriptive analysis

```bash
python scripts/analyze_matched_wells.py --inputs analysis_inputs.json --out NEW_ANALYSIS
python scripts/generate_scientific_figures.py --analysis NEW_ANALYSIS --out NEW_FIGURES
```

Use the existing validated environment. Run from the source checkout; the loader
uses its existing exporter and review functions. Pending templates deliberately
fail. Validation failure returns exit 2 before publishing analysis tables.
Existing output directories are never overwritten.

## Required input manifest

Copy `analysis_inputs.template.json` into the private analysis-input directory.
Paths resolve relative to the manifest, not the terminal working directory.
`schema_version` is `tmem.matched_analysis_inputs.v1` and `evidence_type` is
`REAL_ACCEPTED` or `SYNTHETIC_EXAMPLE`. Mixing modes is prohibited. Units are
`ADU` / `px2` for real data and `synthetic_ADU` / `px2` for examples.

Each `bundles` entry needs:

| Key | Required content |
|---|---|
| `export` | Directory with accepted_neuron_metrics.csv, analysis_scope.json and review_verdicts.json from the existing exporter |
| `curated` | Original immutable per-neuron source fixtures and CSVs |
| `config` | Exact configuration shown in the reviewed workspace |
| `reviews` | Actual evidence-bound manual_review.json |
| `workspace` | Exact rendered review directory, or parent containing review/ |

The loader recalculates source and displayed-asset fingerprints, reevaluates
the review, checks attribution and all automated flags, decodes the reviewed
128×128 uint16 crop and bool masks, checks ROI area and intensity conservation,
and compares every exported source value to the original row. It checks exporter
source identifiers against the local contract. An older incompatible export
requires inspection/re-export from its genuine evidence; no ignore-gates flag
exists. Fingerprints bind bytes; they cannot authenticate a person's judgment.

The exporter still requires all nine visits for an accepted track. The analysis
does not weaken that policy. `cohort_status_csv` also lists nonaccepted tracks,
so their missing/excluded visits remain part of the denominator.

## Cohort ledger and current decisions

The header-only template is `cohort_status.template.csv`. Required columns:
`neuron_id,well,day,condition,observation_status,cell_fate,reason,source_reference`.

Wells map exactly to reporter_control E05/I05/M05 and TMEM106B F05/J05/N05.
Days are 8,12,16,20,25,29,32,36,39. IDs must agree with the well. Duplicate
neuron/day records, unknown conditions, unsupported days and missing source
references are rejected. `accepted` must match an actual released observation.

Allowed observation statuses: accepted, excluded_qc, pending_review,
lost_to_followup, uncertain_identity, missing_image, failed_measurement.
Every nonaccepted row needs a reason and has blank quantitative results.
Omitted expected ledger visits become missing_image with reason
expected_visit_not_supplied; this is an explicit unknown, never a death event.

Fate is separate: blank/not_classified, observed_alive, confirmed_death,
lost_to_followup, uncertain_identity, missing_image_or_failed_measurement,
excluded_qc. An accepted measurement does not automatically establish alive.
An accepted quantitative row may carry a separately sourced confirmed-death
classification, but no survival estimate follows from it in this workflow.

`decision_policy` points to `decision_policy.template.json`. Real mode requires
source files plus their SHA256 hashes, resolved current identity decisions and
the explicit F05_N025/N05_N011 exclusions. It retains J05_N015 in
technical_only_neuron_ids, rejects accepted rows for technical/pending IDs and
requires the current N012 packet's excluded identity to be supplied, not guessed.
List the other flagged N05 identities in pending_neuron_ids until qualifying
review is imported. Do not set unresolved lists to empty merely to run analysis.

## Tables and interpretation

| Output | Meaning |
|---|---|
| neuron_longitudinal.csv | Nine rows per declared neuron; status/fate/source, quantities, Day8 change |
| well_day_summary.csv | All 54 well/day combinations; counts, mean, median, within-well sample SD |
| matched_pair_day.csv | All 27 pair/day combinations; two well means/counts, difference and ratio |
| condition_day_summary.csv | Equal-weight well means and equal-weight paired differences; actual N |
| qc_summary.csv | Mutually exclusive observation counts and reasons; full expected denominator |
| analysis_warnings.json | Missing visits/wells/pairs and incomplete cohort warnings |
| analysis_provenance.json | Input/output/code hashes, exclusions, units and scientific scope |

Mean ROI intensity = integrated total / fixed ROI area. Diffuse fraction =
diffuse / total; puncta density = count / area. Day8 is the actual same-neuron
baseline, never the first later available visit. Zero total/control/baseline
denominators yield missing fractions/ratios/percent changes, not infinity.
SD needs at least two contributors. Tables report per-metric contributing counts.
No zero imputation or interpolation is performed. Neuron SD measures variation
within a well; well SD describes variation among biological replicates.

Biological replication is at well or pair level, at most three per condition.
An unpaired-only input is rejected; at least one paired visit is needed for a
descriptive matched analysis. Missing pairs remain blank and generate warnings.
No p-values, neuron-pooled SEM, automatic survival, rupture or fibril conclusions.

## Focused validation

```bash
python -m pytest tests/audit_v1/test_matched_analysis.py tests/audit_v1/test_scientific_figures.py -q
```

These are the new checks. Do not rerun the unchanged baseline on this account.
The synthetic example uses the actual workspace builder and exporter with
reviewer text explicitly identifying automated software fixtures. Those files
must never be relabeled as real review.
