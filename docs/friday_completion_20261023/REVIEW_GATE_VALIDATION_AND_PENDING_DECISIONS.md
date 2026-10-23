# Review gates and pending decisions

Existing gates are preserved. The completed 340-test/49-subtest Mac baseline,
including Node, is user-reported prior verification; its private records have not
been imported or rerun here. New analysis tests exercise the actual builder and
exporter on explicitly synthetic fixtures and add downstream rejection checks.

| Safeguard | Existing contract / new analysis check |
|---|---|
| 488 before 561 | review_ui.js stages all nine identity/ROI judgments before phenotype controls |
| Missing/failed review | evaluate_review requires each criterion and accepted track decision |
| Known exclusions | Trusted config exclusions override passing automated/manual fields; current analysis policy adds current decisions |
| Stale source/render/config | Source and rendered manifests recomputed; exact config, review, verdict and export sidecars checked |
| Scientific region geometry | New analysis decodes bool core/ROI/adaptive masks and checks uint16 TCYX crop, containment, support and ROI area |
| Automated QC | Existing exporter failures plus exact source tracking flags; False strings cannot become true through truthiness |
| Technical vs biological rows | MANUAL_ACCEPTED and all evidence required; technical/pending IDs separately blocked in real policy |
| Display intensity | Existing LUT policy leaves measurement arrays unchanged; analysis requires unchanged source/render bytes |

Current decisions supplied by the user are preserved in this handoff:

- Nine J05 fixed-region measurements are technical rows, not an accepted cohort.
  Historical J05_N015 is the review example; its actual current packet must be
  matched to the source before scientific use.
- F05_N025 remains excluded for multiple-neuron ROI contamination.
- N05_N011 remains excluded under the current reviewed identity. Older public
  documents calling it a positive reference do not supersede this decision.
- The current N012 packet is excluded because of Day12 region/QC failures.
  The policy template leaves the full packet identity unresolved until import.
- Three additional flagged N05 pairs require further review. Their exact
  identities and newer private reports are absent here; no IDs are invented.

The new policy requires original decision evidence fingerprints. Historical v6
configuration and packets were not rewritten. No human approval was generated;
test review labels explicitly say AUTOMATED SYNTHETIC SOFTWARE TEST.
