# TMEM106B Pipeline Audit and Work Plan

## Lightweight Audit

Checked on 2026-06-25 without reading ND2 pixels.

Repository root:

```text
LOCAL_USER_HOME/Documents/tmem_neuron_aligner
```

Raw data root:

```text
LOCAL_RAW_DATA
```

Intermediate and processed output roots:

```text
LOCAL_INTERIM_OUTPUT
LOCAL_PROCESSED_OUTPUT
```

## Current Structure

- `src/tmem_align/`: reusable package code for config loading, ND2 inspection/extraction, registration, ROI crops, quantification, OME-Zarr export, and optional napari viewing.
- `scripts/`: pilot runners and report builders.
- `configs/`: experiment, plate-map, ROI, and dashboard templates.
- `docs/`: workflow notes and lab-facing guides.
- `tests/`: synthetic/unit tests that do not require raw ND2 data.
- `reports/` and `outputs/`: small pilot/report artifacts already present in the repo.
- `viewer_site/`: local static dashboard generated from existing pilot reports.

## Commands and Scripts

Package CLI:

```bash
python -m tmem_align.cli --help
```

Available commands:

- `inspect-nd2`: metadata-only ND2 inspection.
- `build-manifest`: inventory ND2 files without loading full images.
- `extract-nd2`: lazy indexed pilot extraction with read/output byte guards.
- `validate-config`: validate experiment config and plate map.
- `stitch`, `register-well`, `make-roi-stack`, `quantify`, `export-zarr`: early pipeline commands for TIFF/OME-TIFF workflows.

Important scripts:

- `scripts/build_mcherry_stage_prefilter.py`: metadata/stage-position prefilter.
- `scripts/build_mcherry_qc_report.py`: registration/stage QC summary.
- `scripts/run_mcherry_roi_pilot.py`: ROI-restricted mCherry metrics from existing pilot stacks.
- `scripts/make_registration_qc_montages.py`: visual QC montages.
- `scripts/make_mcherry_timeseries_videos.py`: small GIF previews from existing stacks.
- `scripts/build_live_viewer.py` / `scripts/build_dashboard_index.py`: generate the local dashboard.
- `scripts/launch_dashboard.py`: serve the dashboard locally.
- `scripts/run_single_timepoint_colocalization.py`: exploratory selected-stack colocalization.

Some older scripts are prototype-style and execute immediately instead of exposing `--help`; avoid blanket-running all scripts.

## Environment

Active shell Python during audit:

```text
LOCAL_USER_HOME/anaconda3/bin/python
Python 3.11.5
```

The repo `.venv` is usable:

```text
.venv/bin/python
Python 3.12.5
```

Core dependencies were available in both environments. `napari` was missing from the active Anaconda Python but present in `.venv`; napari remains optional.

## Memory Safety

Safer current paths:

- `src/tmem_align/nd2_tools.py::inspect_nd2` opens ND2 metadata without loading pixel arrays.
- `extract_nd2_selection` uses `image.to_dask()` and indexed selection before `compute()`, with `max_read_bytes` and `max_output_bytes` guards.
- Stage prefiltering and dataset inventory inspect metadata and filenames.

Risk areas:

- `src/tmem_align/io.py::read_image` uses `tifffile.imread`, which loads the selected TIFF into memory.
- `register_file_to_reference`, ROI stack building, quantification, and OME-Zarr export load OME-TIFF/TIFF arrays into memory. Use only on pilot-sized selected outputs unless rewritten for chunked arrays.
- `scripts/run_f05_longitudinal_pilot.py` and `scripts/run_260213_longitudinal_pilot.py` use Dask for ND2 reads but call `compute()` after selection; this is acceptable only with small, guarded selections.
- `scripts/create_scrollthrough_video.py` loads existing ROI stacks at import/runtime and should not be invoked as a generic `--help` probe.

## Git Safety

`.gitignore` excludes ND2, TIFF/OME-TIFF, GIF, MP4/MOV, OME-Zarr/Zarr, raw/interim/processed data folders, dashboard symlinks, Python caches, and editor files.

Do not commit raw ND2 files or large generated microscopy outputs. Keep full-size processed outputs in `LOCAL_PROCESSED_OUTPUT` or a future shared lab results folder.

## Complete vs Prototype

Complete enough for pilot use:

- Metadata-only ND2 inspection.
- Small indexed ND2 extraction with size guards.
- Stage prefilter and QC report generation.
- Existing E05/F05 neuron crop examples and OME-Zarr exports.
- mCherry punctation/diffusion screening metrics.
- Static local dashboard over current reports.

Prototype-only:

- Whole-pipeline same-neuron identity tracking across all wells.
- Full plate-level OME-Zarr organization.
- Chunked lazy TIFF/Zarr processing for all downstream steps.
- Manual ROI identity review at lab scale.
- Colocalization validation and saturation/background QC.
- External/shared-drive deployment.

## Recommended Next Pilot

Do not process the full dataset. For the next safe pilot, choose one valid reporter-control well and one primary well, one FOV, and one neuron ROI:

- E05 or I05/M05 reporter control
- F05 or J05/N05 primary condition
- days already represented by small pilot outputs

Before any new pixel extraction, estimate selected array bytes and output size, then keep outputs outside Git.
