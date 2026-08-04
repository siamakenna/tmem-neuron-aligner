# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Pipeline for month-long TMEM106B neuron imaging: ND2/TIFF → stitch → register (well-level, then neuron-level) → crop ROIs → quantify mCherry puncta vs diffuse signal. Ward Lab codebase.

## Environment

`.venv` with `[nd2,dev]` extras installed. Activate with `source .venv/bin/activate`.

## Commands

```bash
# Setup (already done)
pip install -e ".[nd2,viewer,dev]"

# Tests
pytest                          # all tests
pytest tests/test_quantify.py   # single file
pytest -k test_quantify_single  # single test by name

# Lint
ruff check src/ tests/ scripts/
ruff format --check src/ tests/ scripts/

# CLI (installed as tmem-align)
tmem-align validate-config configs/my_experiment.yaml
tmem-align inspect-nd2 /path/to/file.nd2
tmem-align stitch configs/my_experiment.yaml --plate Plate001 --well A01
tmem-align register-well configs/my_experiment.yaml --plate Plate001 --well A01 --reference-day Day01
tmem-align make-roi-stack configs/my_experiment.yaml --plate Plate001 --well A01 --roi-id Neuron001
tmem-align quantify configs/my_experiment.yaml --plate Plate001 --well A01 --roi-id Neuron001
```

## Architecture

**Package** lives in `src/tmem_align/`. CLI entry point: `cli.py` (Click group, installed as `tmem-align`).

**Pipeline flow:**
1. `nd2_tools.py` — ND2 metadata inspection, manifest building, lazy subset extraction
2. `stitch.py` — grid-based tile stitching to OME-TIFF
3. `register.py` — phase cross-correlation registration (scipy/skimage), applied at well level
4. `roi.py` — crop ROI across registered wells, local re-registration within crop
5. `quantify.py` — mCherry puncta vs diffuse signal (Otsu threshold, morphology cleanup, rupture-like score)
6. `export_zarr.py` — OME-Zarr multiscale export
7. `stage_qc.py` — ND2 stage-coordinate prefiltering (XY drift check before pixel registration)
8. `analysis/mcherry_metrics.py` — higher-level mCherry analysis helpers

**Config:** YAML-based (`configs/template_experiment.yaml`). `config.py` loads it into `ExperimentConfig` dataclass. Config paths resolve relative to the config file's grandparent directory (`config.path.parent.parent`).

**I/O:** `io.py` wraps tifffile for read/write. `normalize_to_2d()` collapses singleton axes for registration input.

**Two-stage alignment** is the core design: well-level registration corrects stage drift, then neuron-level local registration keeps the same neuron centered. Do NOT use mCherry channel for registration — it changes with the biology being measured.

## Experimental design

Wells follow a four-row alphabetical cycle (C/D/E/F, G/H/I/J, K/L/M/N):
- Rows C/G/K: PLD3 only, no mCherry → **not valid for mCherry analysis**
- Rows D/H/L: PLD3 + TMEM106B, no mCherry → **not valid for mCherry analysis**
- Rows E/I/M: PLD3 + mCherry → reporter control, mCherry analysis valid
- Rows F/J/N: PLD3 + TMEM106B + mCherry → primary experimental, mCherry analysis valid

The CLI enforces this via `mcherry_analysis_valid` in the plate map.

## Key constraints

- `zarr<3` is pinned (zarr v3 API incompatibility)
- pytest runs with `-p no:napari` (avoids napari plugin auto-loading)
- Ruff line length: 100
- ND2 support is optional (`[nd2]` extra)
- Image data is at `/Users/pmihack/claire/tmem_2026/data`; only code/configs/metadata are committed
- `docs/` hosts GitHub Pages HTML dashboards for QC review
