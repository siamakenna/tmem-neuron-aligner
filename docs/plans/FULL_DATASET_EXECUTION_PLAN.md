# Full-Dataset Execution Plan

This plan moves toward full TMEM106B mCherry-valid processing while preserving raw ND2 files and keeping every batch restartable.

## Safety Rules

- Raw ND2 files are read-only.
- Raw ND2 files are never moved, renamed, deleted, overwritten, or committed.
- Large generated outputs stay outside Git under `LOCAL_PROCESSED_OUTPUT` and `LOCAL_INTERIM_OUTPUT`.
- Processing runs by well/day batches, not as one giant in-memory job.
- `--resume` skips completed outputs by default.
- `--overwrite false` is the default planning mode.
- Non-mCherry wells remain `not_applicable_no_mcherry` for mCherry analysis.

## Queue Stages

Stage A: dataset inventory and metadata extraction

- Inventory all ND2 files.
- Infer well, day, channels, FOV, condition, and mCherry-analysis validity.
- Exclude Brightfield/BrightFocus from fluorescence processing unless explicitly requested.
- Write dry-run inventory, processing manifest, and summary JSON.

Stage B: same-well registration and QC

- For each selected mCherry-valid well, read one well/day/FOV at a time.
- Use stable fluorescence alignment channel, preferably 488 nm.
- Keep raw selected, registered full, and registered common-overlap outputs separate.
- Write registration shifts, common-overlap crop, QC flags, and montages.

Stage C: web-friendly dashboard previews

- Generate small PNG/GIF previews only.
- Store web derivatives under `LOCAL_PROCESSED_OUTPUT/dashboard`.

Stage D: neuron ROI detection/selection workflow

- Generate candidate neuron/foreground ROI table per well.
- Mark all candidates as `uncertain_identity` until manual review.
- Avoid claiming same-neuron identity before review.

Stage E: neuron-centered time-series export

- For confirmed or candidate ROIs, export neuron-centered OME-TIFF stacks and small preview GIFs.
- Preserve crop coordinates in original/reference-frame coordinates.

Stage F: mCherry punctation/diffusion and colocalization metrics

- Run only for mCherry-valid wells/ROIs.
- Save puncta/diffuse metrics, fractions, threshold parameters, and exploratory colocalization summaries.
- Mark non-mCherry wells as not applicable, never zero-puncta.

Stage G: dashboard index update

- Rebuild the local dashboard so lab members can click plate/well/neuron/time-series/QC/metrics.

## Current Dry-Run Command

```bash
python scripts/run_full_dataset_queue.py \
  --dry-run \
  --all-mcherry-valid-wells \
  --resume \
  --overwrite false \
  --max-workers 1 \
  --stages A,B,C,D,E,F,G
```

## Dry-Run Outputs

```text
LOCAL_PROCESSED_OUTPUT/full_dataset_queue/manifests/
  full_dataset_inventory_dry_run.csv
  processing_manifest_dry_run.csv
  dry_run_summary.json
```

## Current Executable Status

Stage A dry-run inventory is implemented.

Stages B and C now have an executable small-pilot path in `scripts/run_full_dataset_queue.py`:

- Stage B reads selected fluorescence ND2 files per well/day, writes raw selected CYX OME-TIFFs,
  same-well registered full TCYX stacks, common-overlap TCYX stacks, registration QC CSVs, and
  registration QC montages.
- Stage C writes small dashboard-ready PNG previews and a `queue_index.json` with safe raw source
  identifiers.

Stages D-G remain planning/scaffolding only and require explicit approval before execution.

The first real-data smoke test used only E05 days 8 and 12 and wrote outputs outside the repo under:

```text
LOCAL_PROCESSED_OUTPUT/stage_bc_smoketest_e05_days8_12_v3
LOCAL_PROCESSED_OUTPUT/dashboard_stage_bc_smoketest_v3
```

QC flagged E05 day 12 as a large shift, so larger pilot runs should be reviewed carefully before
downstream neuron ROI or mCherry metric stages.

## Approval Gate

Do not run full pixel extraction until the dry-run manifest has been reviewed. The next approved run should start with a small executable pilot, for example:

```bash
python scripts/run_full_dataset_queue.py \
  --wells E05,F05,I05,J05,M05,N05 \
  --resume \
  --overwrite false \
  --max-workers 1 \
  --stages A,B,C
```

After that pilot passes QC and storage checks, expand to:

```bash
python scripts/run_full_dataset_queue.py \
  --all-mcherry-valid-wells \
  --resume \
  --overwrite false \
  --max-workers 1 \
  --stages A,B,C,D,E,F,G
```

The current script implements Stage A dry-run planning. Full pixel-executing stages should be enabled only after the pilot command and estimated output size are explicitly approved.
