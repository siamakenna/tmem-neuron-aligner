# TMEM Neuron Aligner

A lab-shareable starter codebase for turning Nikon ND2/tiled spinning-disk images into stitched, registered, neuron-centered month-long time series. The first goal is not a perfect automated pipeline; it is a reproducible workflow that lets the lab integrate images now, inspect the same neuron over roughly a month, and progressively add quantification.

THIS IS A FIRST-PASS ROI CANDIDATE REVIEW DASHBOARD!

## What this pipeline does

```text
ND2 or exported TIFF tiles
→ organize by plate / well / day / channel
→ stitch each well/day
→ register each well/day to a reference day
→ crop the same neuron ROI across days
→ locally re-align the neuron crop
→ export OME-TIFF and/or OME-Zarr
→ quantify punctate versus diffuse mCherry signal
```

## Why two-stage alignment?

For a month-long experiment, whole-well alignment alone is usually not enough. The pipeline uses:

1. **Well-level registration** to correct stage drift and make the same well comparable across days.
2. **Neuron-level local registration** to keep the same neuron centered across the month.

Do not use the mCherry phenotype channel as the main registration reference unless there is no alternative, because mCherry diffusion is part of the biology you want to measure. For this ND2 dataset, use fluorescence channels for the pilot workflow rather than BrightFocus/brightfield images. Prefer a stable fluorescence morphology or nuclear channel for registration.

## Experimental layout

The mCherry punctation-versus-diffusion analysis is valid only for wells that actually contain mCherry. Missing mCherry in a condition is a design feature, not a zero-puncta measurement.

The well conditions repeat in a four-row alphabetical cycle:

```text
C, G, K, ...: PLD3 only; no TMEM106B and no mCherry
D, H, L, ...: PLD3 + TMEM106B; no mCherry
E, I, M, ...: PLD3 + mCherry; reporter-control wells, mCherry analysis valid
F, J, N, ...: PLD3 + TMEM106B + mCherry; primary experimental wells, mCherry analysis valid
```

Only the third and fourth rows in each cycle are valid for mCherry puncta/diffusion analysis. The first and second rows remain useful biological controls, but they must not be interpreted as zero-puncta mCherry samples.

## Quick start

### 1. Clone or upload this folder to GitHub

Create a new GitHub repository, upload the contents of this folder, and share the repository with lab members.

### 2. Create an environment

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[nd2,viewer,dev]"
```

On Windows PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[nd2,viewer,dev]"
```

### 3. Copy and edit the experiment config

```bash
cp configs/template_experiment.yaml configs/my_experiment.yaml
```

Edit `configs/my_experiment.yaml` so it points to your raw/exported image folder and plate map.

### 4. Validate the config

```bash
tmem-align validate-config configs/my_experiment.yaml
```

### 5. Run a tiny first test

Start with one plate, one well, and two or three timepoints. Do not run the full month-long plate first.

```bash
tmem-align stitch configs/my_experiment.yaml --plate Plate001 --well A01

tmem-align register-well configs/my_experiment.yaml --plate Plate001 --well A01 --reference-day Day01

tmem-align make-roi-stack configs/my_experiment.yaml --plate Plate001 --well A01 --roi-id Neuron001

tmem-align quantify configs/my_experiment.yaml --plate Plate001 --well A01 --roi-id Neuron001
```

## Recommended folder organization

```text
data/
  raw/
    Plate001/
      Day01/
        Well_A01/
          tiles_or_nd2_files_here
      Day07/
      Day14/
      Day21/
      Day28/
  interim/
    stitched/
    registered_wells/
    neuron_rois/
  processed/
    ome_tiff/
    ome_zarr/
    measurements/
```

Raw ND2/TIFF/Zarr data are intentionally ignored by Git. Keep images on shared storage, Box, OneDrive, Google Drive, or an institutional server. Commit only code, configs, and small example metadata files.

## Plate map

Use `configs/plate_map_template.csv` as a starting point. Each row should describe one well/day/condition.

Minimum columns:

```text
plate,day,well,well_group,condition,replicate,has_pld3,has_tmem106b,has_mcherry,mcherry_analysis_valid,raw_path
```

Optional but useful columns:

```text
channels,alignment_channel,pixel_size_um,z_step_um,scene_index,notes
```

## Manual ROI annotations

For the first pass, manual neuron ROI selection is acceptable. Save ROIs in `configs/roi_annotations_template.csv` format:

```text
plate,well,roi_id,reference_day,x,y,width,height,notes
```

The pipeline crops the same region across aligned well images, then performs local registration inside the crop.

## Output files

Expected outputs:

```text
data/interim/stitched/Plate001/Day01/Well_A01_stitched.ome.tif

data/interim/registered_wells/Plate001/Well_A01/Day01_registered.ome.tif

data/interim/neuron_rois/Plate001/Well_A01/Neuron001/Neuron001_registered_timeseries.ome.tif

data/processed/ome_zarr/Plate001/Well_A01/Neuron001.ome.zarr

data/processed/measurements/Plate001_Well_A01_Neuron001_measurements.csv
```

## Rupture-like score

The starter quantification estimates:

```text
rupture_like_score = diffuse_mcherry_intensity / punctate_mcherry_intensity
```

This is only a screening metric. Stronger rupture validation should use Galectin-3/Galectin-8, p62/LC3, LAMP1/LAMP2 changes, LysoTracker loss, and LLOMe positive controls.

## Current limitations

- The ND2 converter is intentionally conservative because ND2 metadata structures vary by microscope/software version.
- Stitching works best when tile positions are in metadata or filenames. If not, provide grid dimensions in the config.
- Long-term neuron identity may still require manual review because neurons can migrate, change morphology, or die.
- This codebase is designed as a starting scaffold for lab collaboration, not a fully validated analysis package yet.

## Local Jupyter workflow for ND2 data

For the 99 GB dataset, use `notebooks/01_local_nd2_pilot.ipynb`. The notebook reports one selected fluorescence ND2 file, metadata, and a saved indexed preview without loading the entire dataset into memory.

New commands:

```bash
tmem-align inspect-nd2 "/path/to/file.nd2"
tmem-align extract-nd2 "/path/to/file.nd2" "/path/to/interim/pilot.ome.tif" --position 0 --time 0 --channel 0 --max-project-z
```

It is not necessary to bulk-convert ND2 files before working with them. Use `nd2`/Dask-backed lazy or indexed reads for metadata and pilot subsets, then write only small selected OME-TIFF or OME-Zarr outputs needed for downstream review.

The mCherry puncta/diffusion analysis is restricted to wells marked `mcherry_analysis_valid=true`, normally the E/F phase of each repeated condition block such as E/F, I/J, and M/N. C/D-phase wells remain useful controls but must not be interpreted as zero-puncta samples.

## Reproducible E05/F05 pilot

After local setup, run the tiny E05/F05 image-level mCherry pilot:

```bash
python scripts/run_ef05_mcherry_pilot.py
```

This writes local outputs under `/Users/makennarodriguez/Documents/TMEM106B_interim/pilot/ef05_mcherry` and `/Users/makennarodriguez/Documents/TMEM106B_processed/pilot/ef05_mcherry`. See `docs/PILOT_EF05_RESULTS.md` for the current preliminary metrics and caveats.

## Reproducible same-well longitudinal pilot

The main experimental direction is to align the same well across days and preserve channels in a scrollable time stack:

```bash
python scripts/run_f05_longitudinal_pilot.py
```

This creates a three-day F05 `TCYX` OME-TIFF stack, registers later days to Day 8 using the 488nm channel, crops a common-overlap stack for quantification, and measures the 561nm mCherry channel across time. See `docs/F05_LONGITUDINAL_PILOT_RESULTS.md` for local output paths, registration shifts, and preliminary metrics.

To run the matched E05 reporter-control and F05 primary comparison:

```bash
python scripts/run_f05_longitudinal_pilot.py --well E05
python scripts/run_f05_longitudinal_pilot.py --well F05
python scripts/compare_ef05_longitudinal.py
```

See `docs/EF05_LONGITUDINAL_COMPARISON.md` for the current matched pilot comparison.

To include additional matched replicate pairs:

```bash
python scripts/run_f05_longitudinal_pilot.py --well I05
python scripts/run_f05_longitudinal_pilot.py --well J05
python scripts/run_f05_longitudinal_pilot.py --well M05
python scripts/run_f05_longitudinal_pilot.py --well N05
python scripts/compare_ef05_longitudinal.py
```

See `docs/REPLICATE_LONGITUDINAL_COMPARISON.md` for the current six-well pilot and registration QC flags.

To create registration QC montages:

```bash
python scripts/make_registration_qc_montages.py
```

See `docs/REGISTRATION_QC_MONTAGES.md` for the local output paths and current large-shift flags.

Before processing additional columns, build the metadata-only stage prefilter and lab-facing QC report:

```bash
python scripts/build_mcherry_stage_prefilter.py
python scripts/build_mcherry_qc_report.py
python scripts/plot_mcherry_pilot_analysis.py
```

For the current columns `05-07`, compare full-frame and foreground-ROI-restricted mCherry metrics:

```bash
python scripts/run_mcherry_roi_pilot.py --columns 05 06 07
```

See `docs/STAGE_QC_AND_ROI_WORKFLOW.md` for the current automated QC report, stage-prefilter output, ROI-restricted analysis, and caveats.

To create small animated GIF examples from the registered pilot time series:

```bash
python scripts/make_mcherry_timeseries_videos.py --wells E05 F05 M07 J06
```

This writes local video-like outputs under `/Users/makennarodriguez/Documents/TMEM106B_processed/pilot/mcherry_timeseries_videos`. These generated files are not tracked by Git.

See `docs/LOCAL_JUPYTER_GUIDE.md` for setup instructions.
