# Dashboard Guide

The local dashboard lets lab members move from plate/well overview to individual well pages and neuron/ROI visualizations without knowing the folder structure.

## Generate

```bash
python scripts/build_dashboard_index.py --config configs/dashboard_config.yaml
```

This reads existing reports and processed pilot outputs. It does not read raw ND2 pixels.

## Launch

```bash
python scripts/launch_dashboard.py --port 8765
```

Open:

```text
http://127.0.0.1:8765/viewer_site/index.html
```

## What It Shows

- 192-well overview from the current all-wells report.
- condition and mCherry-analysis validity.
- source acquisition folder, ND2 filename, channel names, and FOV as safe identifiers.
- registration shifts and QC pass counts.
- available per-well visualizations.
- available neuron/ROI visualizations for E05 and F05.
- missing neuron outputs clearly as unavailable.

## Local Path Configuration

Edit:

```text
configs/dashboard_config.yaml
```

To point at a shared lab drive later, change:

```yaml
paths:
  raw_root: /Volumes/LabShare/TMEM106B/raw
  interim_root: /Volumes/LabShare/TMEM106B/interim
  processed_root: /Volumes/LabShare/TMEM106B/processed
  processed_pilot_root: /Volumes/LabShare/TMEM106B/processed/pilot
  interim_pilot_root: /Volumes/LabShare/TMEM106B/interim/pilot
```

The committed dashboard manifest uses safe source identifiers rather than absolute raw file paths.

## Data Safety

- Do not commit raw ND2 files.
- Do not copy large OME-TIFF/OME-Zarr outputs into the website folder.
- The dashboard uses local symlinks in `viewer_site/linked_processed`, which are ignored by Git.
- Put new small web derivatives in `LOCAL_PROCESSED_OUTPUT/dashboard` if needed.

## Current Pilot Visibility

Well pages exist for all 192 wells. Rich linked processed outputs are currently available for selected pilot wells/columns, especially E05, F05, E06/F06/J06/M06/N06, and E07/F07/J07/M07/N07. Neuron-level ROI pages are currently populated for E05 and F05 only.
