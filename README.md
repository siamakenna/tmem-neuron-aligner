# TMEM106B Neuron Aligner

Longitudinal single-neuron tracking and mCherry phenotype analysis for the TMEM106B imaging pilot.

## Current analysis

The workflow uses **488 morphology for neuron identity and tracking** and measures **561/mCherry independently as phenotype**.

The current analysis is at the curated internal-review stage. The full automatic atlas is retained as a candidate-generation resource, while high-quality longitudinal tracks are visually reviewed before phenotype interpretation.

### Current curated workflow

- 9 longitudinal visits: Days 8–39
- 6 wells / 3 matched control–TMEM106B pairs
- 128 × 128 neuron-centered crops
- tight longitudinal 488 identity core
- fixed phenotype ROI
- explicit punctate vs. diffuse mCherry visualization
- manual single-neuron QC

## Representative examples

### Clean longitudinal track — J05_N015

![J05_N015](docs/figures/J05_N015_audit_montage.png)

### Clean longitudinal track — N05_N011

![N05_N011](docs/figures/N05_N011_audit_montage.png)

### Known QC exclusion — F05_N025

![F05_N025](docs/figures/F05_N025_qc_montage.png)

F05_N025 remains centered but contains more than one neuron within the phenotype ROI and is retained as a QC example.

## Documentation

See:

**[Curated Review — September 1, 2026](docs/CURATED_REVIEW_20260901.md)**

for experimental design, QC history, phenotype definitions, representative images, interpretation guardrails, and current analysis status.

## Data policy

Large microscopy files, registered TIFF stacks, and MP4 review files are intentionally excluded from Git.

This repository contains code, analysis parameters, compact QC records, and representative figures required to document and reproduce the workflow.
