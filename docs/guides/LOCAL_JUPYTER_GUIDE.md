# Local-only Jupyter workflow for the TMEM106B ND2 dataset

This workflow runs entirely on your computer. GitHub contains code and small metadata files only; the 99 GB ND2 dataset stays on your local disk or external SSD.

## Recommended storage

```text
TMEM106B_data/
  raw_nd2/       # original files; never modify
  pilot/         # optional small copied subset
  interim/       # extracted/stiched/registered files
  processed/     # OME-Zarr, ROI stacks, CSV measurements
```

Keep the GitHub repository elsewhere, for example `~/Documents/tmem-neuron-aligner`.

## Install once with Miniforge

1. Install Miniforge for your computer.
2. Open Terminal.
3. Change into the repository folder.
4. Create the environment:

```bash
conda env create -f environment.yml
conda activate tmem-align
python -m ipykernel install --user --name tmem-align --display-name "Python (tmem-align)"
```

## Launch JupyterLab

```bash
conda activate tmem-align
cd ~/Documents/tmem-neuron-aligner
jupyter lab
```

Open `notebooks/01_local_nd2_pilot.ipynb` and select the `Python (tmem-align)` kernel.

## Safe order for the 99 GB dataset

1. Set `RAW_ROOT` to the local ND2 folder.
2. Inspect one representative ND2 file.
3. Verify channel names, axes, position counts, dates, and well assignments.
4. Use fluorescence ND2 files for the pilot; do not default to BrightFocus/brightfield images.
5. Extract a single position/channel/timepoint from one mCherry reporter-control well and one primary experimental well.
6. Confirm the images visually before attempting stitching.
7. Only after the pilot succeeds, process additional days and replicates.

Do not convert all ND2 files into TIFF at once. That can duplicate the dataset and consume hundreds of gigabytes.

## Condition guardrails

The well conditions repeat in a four-row alphabetical cycle:

```text
C, G, K, ...: PLD3 only; no TMEM106B and no mCherry
D, H, L, ...: PLD3 + TMEM106B; no mCherry
E, I, M, ...: PLD3 + mCherry; mCherry reporter-control wells
F, J, N, ...: PLD3 + TMEM106B + mCherry; primary experimental wells
```

Only the E/I/M-phase and F/J/N-phase wells are valid for mCherry punctation-versus-diffusion analysis. Do not interpret C/G/K-phase or D/H/L-phase wells as zero-puncta mCherry samples.

It is fine that the files are ND2. Use the `nd2` package for lazy metadata inspection and Dask-backed indexed reads, then save only small pilot subsets as OME-TIFF or OME-Zarr when a downstream tool needs an interchange format.

## Reproduce the current E05/F05 pilot

From the repo root, after activating the environment:

```bash
python scripts/run_ef05_mcherry_pilot.py
```

This creates local interim previews and processed CSV/PNG summaries outside the repository. See `docs/PILOT_EF05_RESULTS.md` for the current preliminary values and limitations.

## Reproduce the same-well longitudinal pilot

The main analysis unit is the same well across days, not different wells aligned to each other. For a first scrollable time stack:

```bash
python scripts/run_f05_longitudinal_pilot.py
```

This selects F05 Day 8, Day 25, and Day 39 fluorescence ND2 files, registers the day frames with the 488nm channel, writes `TCYX` OME-TIFF stacks, and quantifies 561nm mCherry in the common aligned overlap. See `docs/F05_LONGITUDINAL_PILOT_RESULTS.md`.

For future files that expose tile positions, stitch each well/day first, then register the stitched well images across days. If Python stitching is not reliable for a given acquisition, Fiji Grid/Collection Stitching can be used as a validation or fallback step. For larger scale-up, prefer OME-Zarr for chunked viewing rather than large monolithic TIFF conversion.

## Reproduce the matched E05/F05 comparison

```bash
python scripts/run_f05_longitudinal_pilot.py --well E05
python scripts/run_f05_longitudinal_pilot.py --well F05
python scripts/compare_ef05_longitudinal.py
```

The comparison combines metrics only after each well has been registered to its own Day 8 reference. See `docs/EF05_LONGITUDINAL_COMPARISON.md`.

## Add additional matched replicate pairs

```bash
python scripts/run_f05_longitudinal_pilot.py --well I05
python scripts/run_f05_longitudinal_pilot.py --well J05
python scripts/run_f05_longitudinal_pilot.py --well M05
python scripts/run_f05_longitudinal_pilot.py --well N05
python scripts/compare_ef05_longitudinal.py
```

This writes a six-well comparison for E05/F05, I05/J05, and M05/N05. See `docs/REPLICATE_LONGITUDINAL_COMPARISON.md`.

## Create registration QC montages

```bash
python scripts/make_registration_qc_montages.py
```

This writes local PNG montages and `registration_qc_shift_summary.csv` under `LOCAL_PROCESSED_OUTPUT/pilot/registration_qc`. Review the 488nm alignment-channel montages and RGB day overlays before scaling to more wells. See `docs/REGISTRATION_QC_MONTAGES.md`.
