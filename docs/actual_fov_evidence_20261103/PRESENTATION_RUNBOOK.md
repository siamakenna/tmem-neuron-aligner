# Editable PI meeting presentation

`scripts/create_final_pi_presentation.py` is an optional reporting utility using python-pptx and Pillow. It adds no production dependencies and never runs registration, segmentation, tracking, benchmark or acceptance workflows.

```bash
python scripts/create_final_pi_presentation.py --project PROJECT_PARENT --out NEW_PRIVATE_PRESENTATION_DIRECTORY
```

The project must contain the verified November 3 actual-FOV gallery and tables, the existing registered master/declaration, original-field figure inventory, saved acquisition/header summaries and private handoff reports. Source paths must remain confined to that project. Use a new output outside the repository and all input trees. No overwrite or symlink source/output is allowed. Missing/corrupt source evidence fails closed. Explicit saved no-view proposals remain unavailable panels, never fake masks.

The utility builds 15 main and five appendix slides in 16:9 format. Real microscopy appears as individual embedded PNG panels, with editable text, legends, arrows, diagrams, tables, chart data/workbooks and speaker notes. It copies exact saved SVG-embedded displays by card slot, checks their bound output hashes, and documents display-only crops of verified original-field QC panels. It does not contrast-adjust quantitative inputs or fabricate composites. Raw, normalized, Boolean, label and correlation displays remain distinct. No physical scale bar is used without independent calibration.

Counts, gains/losses, masks, displacements and coordinates come from saved records. Original stored-field registration and historical registered-atlas cell diagnostics remain separate coordinate streams. All failed gates, exclusions, masks, anchors and ROIs remain unchanged. No alternative is adopted and no biological track is accepted.

Outputs: editable PPTX, complete Markdown script, private figure-provenance CSV, copied deterministic generator, presentation manifest and initial readiness report. The manifest schema is private and blocked by the publication auditor. Images, decks, source paths, detailed measurements and rendered previews must never be staged.

The generator honestly marks rendering/visual inspection pending. Render the actual PPTX with a local presentation renderer, inspect every slide, create the PDF/contact-sheet companions and record a separate final verification receipt. A structurally valid PPTX is not a visual pass or a claim of native PowerPoint testing. Regenerate to a fresh directory after any source/layout change and preserve earlier receipts.

Scientific release still requires acquisition completeness/geometry and calibrated channel/correction evidence, original-to-atlas mapping, independent 488 identity/ROI review, separate final 561 review and genuine accepted matched-well exports. Neither presentation preparation nor software-only merging clears those gates.
