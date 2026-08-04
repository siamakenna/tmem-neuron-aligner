# Documentation Index

## Design Decisions and Rationale

- [ALIGNMENT_METHOD_REVIEW](design/ALIGNMENT_METHOD_REVIEW.md) — Review of external alignment tools; why we adapted ideas rather than vendoring
- [OVERLAP_ONLY_AUDIT](design/OVERLAP_ONLY_AUDIT.md) — Audit confirming ROI candidates use overlap-only stacks; identifies metadata gaps
- [PIPELINE_AUDIT_AND_WORKPLAN](design/PIPELINE_AUDIT_AND_WORKPLAN.md) — Full pipeline structure audit: all CLI commands, packages, data root conventions
- [PI_OVERLAP_ONLY_RESPONSE](design/PI_OVERLAP_ONLY_RESPONSE.md) — PI-facing explanation of overlap-only processing and current audit numbers

## Results and Analysis

- [PILOT_EF05_RESULTS](results/PILOT_EF05_RESULTS.md) — E05/F05 single-frame mCherry pilot metrics and reproduction command
- [F05_LONGITUDINAL_PILOT_RESULTS](results/F05_LONGITUDINAL_PILOT_RESULTS.md) — F05 3-day longitudinal: registration shifts, crop coords, puncta metrics
- [EF05_LONGITUDINAL_COMPARISON](results/EF05_LONGITUDINAL_COMPARISON.md) — E05 vs F05 longitudinal comparison across Days 8/25/39
- [REPLICATE_LONGITUDINAL_COMPARISON](results/REPLICATE_LONGITUDINAL_COMPARISON.md) — Three replicate pairs (E/F, I/J, M/N) group-mean comparison
- [MCHERRY_GRAPHICAL_ANALYSIS](results/MCHERRY_GRAPHICAL_ANALYSIS.md) — Expanded 18-well mCherry analysis: condition means, trajectory plots
- [REGISTRATION_QC_MONTAGES](results/REGISTRATION_QC_MONTAGES.md) — QC montage generation, shift flag threshold (500 px), flagged wells

## Guides

- [DASHBOARD_GUIDE](guides/DASHBOARD_GUIDE.md) — Build and launch the local TMEM106B review dashboard
- [GITHUB_PAGES_DASHBOARD](guides/GITHUB_PAGES_DASHBOARD.md) — Build and publish the sanitized GitHub Pages dashboard
- [ROI_IDENTITY_REVIEW](guides/ROI_IDENTITY_REVIEW.md) — Manual ROI review workflow: priority wells, dashboard URLs, checklist
- [IMAGE_INTEGRATION_CHECKLIST](guides/IMAGE_INTEGRATION_CHECKLIST.md) — Onboarding new raw imaging data: file format, channel order, plate map
- [LOCAL_JUPYTER_GUIDE](guides/LOCAL_JUPYTER_GUIDE.md) — Jupyter environment setup with Miniforge/conda
- [NAPARI_VIEWING_GUIDE](guides/NAPARI_VIEWING_GUIDE.md) — Inspect registered stacks and ROI crops in napari
- [STAGE_QC_AND_ROI_WORKFLOW](guides/STAGE_QC_AND_ROI_WORKFLOW.md) — XY stage prefiltering (5 um threshold), QC reports, ROI-restricted quantification
- [CODEX_4_AGENT_TEAM_GUIDE](guides/CODEX_4_AGENT_TEAM_GUIDE.md) — 4-agent Codex workflow; includes TMEM safety defaults and pilot well list

## Plans

- [FULL_DATASET_EXECUTION_PLAN](plans/FULL_DATASET_EXECUTION_PLAN.md) — Master plan: Stages A-F, safety rules, channel selection, mCherry-validity
- [FULL_DATASET_DEFG_PLAN](plans/FULL_DATASET_DEFG_PLAN.md) — Stages D-G: ROI candidates, neuron export, mCherry metrics, interpretation
- [MANUAL_ALIGNMENT_OVERRIDE_PLAN](plans/MANUAL_ALIGNMENT_OVERRIDE_PLAN.md) — Manual x/y offset CSV workflow for failed registrations
- [PSEUDO_FOV_ALIGNMENT_PLAN](plans/PSEUDO_FOV_ALIGNMENT_PLAN.md) — Proposed pseudo-FOV stitching for single-FOV alignment failures (not yet implemented)

## Dashboard

The generated review dashboard (HTML/PNG/CSS/JS) has been moved to the `gh-pages` branch to keep the source tree clean. Rebuild with:

```bash
python scripts/build_github_pages_dashboard.py
```

See [GITHUB_PAGES_DASHBOARD](guides/GITHUB_PAGES_DASHBOARD.md) for full publish instructions.
