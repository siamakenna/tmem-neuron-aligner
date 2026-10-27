# What the latest diagnostics establish

## Local expansion — completed calculations, provisional review

The verified complete package enabled a frozen 12-candidate panel across all six wells. The original three cases below remain regression controls and were excluded from the new panel; they do not increase the new biological sample size. No production geometry or tracking algorithm has been changed.

All 12 calculations completed in 875.748 seconds, with no failed/timed-out/deferred software cases. Primary QC retained 91/108 valid visits; six cases were diagnostically rejected and six remain unapproved/pending independent review. No biological track was accepted. Actual-488 image inspection found:

- **E05_N057:** primary segmentation has 7/9 valid visits, failing days 32 and 39; constructed core 429 pixels. The central signal is visibly dimmer/fragmentary on those later visits. Radius-60 proposals depart up to 71.14 pixels from the stored anchor; radius 80 up to 90.57 pixels, with some proposals outside the fixed crop. These are diagnostic departures, not independently labeled identity errors. No failure was overridden.
- **F05_N005:** 9/9 primary valid visits, core 284 pixels. Later images contain several neighboring 488-positive objects; wide-radius proposal markers visibly land on neighboring objects in some visits. The red fixed ROI is largely centered on the anchor object, but proximity/continuity with neighbors requires boundary review. Automated single-soma or all-visit passes do not establish ownership or acceptance.

Inspection here is agent triage of actual registered 488 crops, not independent expert annotation. Baseline is the frozen original anchors and primary area=180/radius=60 diagnostic setting. Alternatives (areas 140/220 and radii 40/80) are compared on exactly the same declared cases; all remain unadopted. Reported overlaps measure agreement between derived supports, not accuracy or contamination truth. There is no demonstrated algorithmic accuracy improvement or biological discovery.

### Same-panel quantitative comparison

| Declared setting | Valid visits /108 | Cases with 9 valid visits /12 | Minimum visit-mask IoU versus primary |
|---|---:|---:|---:|
| Minimum area 140 | 91 | 6 | 0.0881 |
| Minimum area 180 (primary) | 91 | 6 | 1.0000 |
| Minimum area 220 | 97 | 7 | 0.1456 |

Median visit-mask IoU is 1.0 for each grid setting, but the minima expose large changes hidden by that median. These summaries cover 107 nonempty-union comparisons per setting; the both-empty N05_N022 Day39 comparison is undefined, not scored as perfect agreement. The additional six valid flags at area 220 occur in E05_N057 (days32/39), J05_N029 (day36) and J05_N028 (days29/36/39). **This is sensitivity, not a six-visit accuracy improvement or a rescue:** E05_N057's core simultaneously grows from 429 to 642 pixels. Changing area 180→140 alters J05_N028's core from 943 to 1,388 pixels despite unchanged aggregate valid-visit counts. No alternative was adopted or selected using phenotype values.

Radius-40 proposals differ from primary radius60 proposals by >20 pixels on **25/108 visits**; radius80 differs on **21/108 visits**. The >20px threshold is descriptive, not an acceptance gate. Maximum proposed departures from frozen anchors are 108.90, 87.26 and 133.61 pixels for radii40/60/80 respectively. Stored anchors are not reviewed ground truth, and image inspection shows alternatives can select different nearby objects; these counts are not identity-error rates.

Among QC-valid visits, the minimum fraction of a fixed ROI supported by that visit's primary 488 mask ranges from 0.2539 (F05_N061) to 0.6954 (J05_N028) across cases. This is agreement between derived supports, not a measured contamination fraction. N05_N022 Day39 has zero support because segmentation failed; it remains invalid and inherited tracking QC was already false.

All 12 informational secondary-soma screens passed, including E05_N066, whose 1,764-pixel core visibly spans several bright structures. Together with the six primary diagnostic rejections, this reinforces the need for independent identity/ownership review. No smaller ROI, altered LUT, or stronger match was used to force acceptance. Full case-level triage, readiness gates and exact local next actions are in [LOCAL_REVIEW_HANDOFF.md](LOCAL_REVIEW_HANDOFF.md).

The following sections retain the historical three-case findings unchanged.

The latest run adds inspectable evidence about existing processing behavior. It does not yet demonstrate a more accurate tracking algorithm, corrected ROI ownership, or a biological discovery.

## Why the same three cases appeared again

The run selected E05_N006 to expose a known identity/anchor problem, F05_N007 to expose an ROI boundary-ownership problem, and J05_N015 as a technical reference. Holding inputs fixed makes software changes easier to check. This small debugging panel was overused as the main validation set, however; I05, M05, and N05 were absent from the latest diagnostic run.

There are **27 track-visits from three neurons in three wells**. The **9,633 executed intermediate records** are different operations on those inputs. Their number measures trace coverage, not additional neurons, wells, or biological replicates.

## Quantified findings

| Case and comparison | Observed result | What it establishes |
| --- | --- | --- |
| F05_N007, Day 12, tracking search radius 40 → 60 pixels | Proposed-anchor displacement from the stored anchor increases from **1.581 to 73.502 pixels**. Diagnostic match score increases from **0.85574 to 0.86811**. | A slightly higher matching score can accompany a substantially different object proposal. Match score alone cannot establish identity or justify a wider search. |
| E05_N006, minimum segmentation area 180 → 220 pixels | Valid 488 visits decrease from **9 to 8**; the constructed consensus core changes from **248 to 260 pixels**. | The area parameter can change longitudinal inclusion and the resulting core. A constructed core does not override an all-nine-visit acceptance requirement. |
| J05_N015, minimum segmentation area 180 → 220 pixels | Valid visits remain 9; the core changes from **216 to 260 pixels**. | Even when the visit count is unchanged, geometry can depend on the setting. Phenotype measurements need geometry sensitivity checks. |
| F05_N007, minimum segmentation area 140, 180, and 220 pixels | The core remains **292 pixels** with 9 valid visits. | This particular core is stable across the declared area grid. This does not resolve its previously identified boundary-ownership concern. |
| All three cases, automated secondary-soma screen | Each screen reports a single-soma pass. | This informational screen does not resolve the identity and boundary issues previously identified by image review. It cannot serve as an acceptance gate on its own. |

All tracking proposals and parameter alternatives remain unadopted. Stored anchors, the source master, and acceptance decisions were not overwritten. The displacement above is relative to a stored anchor; that anchor is not independently established biological ground truth, and a large displacement is not by itself proof of an identity switch.

## What improved

The workflow now records the actual arrays before and after observed operations, configuration values, array/file hashes, stage ancestry, and display rules. This makes it possible to identify where a mask, tracking proposal, or ROI changes and to reproduce the comparison. Unit and integration/regression checks passed on the NIH environment.

The results expose a concrete tracking failure mode and parameter-dependent ROI geometry. They supply testable engineering questions: does constraining candidate identity reduce wrong-object assignments, and how much do allowed parameter changes alter accepted geometry? A numerical improvement requires those questions to be scored on a declared comparison panel with reviewed identities and boundaries.

## What remains unestablished

- Real raw-image IC before/after: the latest before/after software verification uses a synthetic known-truth example. The three real diagnostic inputs were already registered stacks.
- Historical raw inputs, IC, stitching, and registration: each real case explicitly records these four historical stages as unavailable.
- Corrected E05_N006 identity or F05_N007 ROI ownership: execution success and a single-soma screen do not reverse the earlier image-review findings.
- Improved performance across all six wells: the next portable panel must provide that evidence. Do not label selected tracks as held out unless their review/tuning history is documented.
- A newly accepted paired biological cohort, physical calibration, or a biological phenotype claim: these remain unsupported by this packet.

## Next comparison

Declare candidate selection and parameter ranges before examining 561 phenotype outcomes. Use 488 for identity, tracking, segmentation, and ROI construction. Preserve the original baseline and compare identity errors, valid-visit counts, ROI overlap/ownership, core area, and parameter sensitivity. Record exclusions and missing inputs as results. Only then evaluate whether a proposed change improves the analysis.

Source values are in the corresponding case archive's `trace/tracking_comparison.json`, `trace/parameter_sensitivity.json`, `trace/secondary_soma_screen.json`, and `trace/summary.json`. [STATUS.md](STATUS.md) identifies the returned packet and pushed commit.
