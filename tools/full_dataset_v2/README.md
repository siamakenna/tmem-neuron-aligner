# Full-dataset original-ND2 diagnostics, November 5

This workflow extends the supplied inventory-only kit without replacing the scientific checkout. The worker imports the **actual local repository**, records its code/commit/environment, checks channels on every visit and retains the full-plate policy from `plate_preflight.PARAMETERS` (anchored reference, anchor correlation 0.10, post-correlation 0.07 in reviewed main `47a2db7`). Original ND2 files remain read-only. Real plate analysis is a separate execution step.

Start where the original February ND2 files already exist. The downloadable standalone kit contains code/documentation and an earlier private original-FOV storyboard under `EXISTING_REAL_FOV_EVIDENCE`. GitHub contains only source; the private storyboard and the 92 GB acquisition folder are excluded.

## 1. Configure this device and verify current source

After extracting this package into a new folder, run from that folder:

```bash
cp config.env.example config.env
nano config.env
source config.env
export TMEM_KIT="$PWD"
bash "$TMEM_KIT/CHECK_AND_VERIFY.sh"
```

Set the three actual paths: current Git checkout, original ND2 root, tested Python. The example includes previously observed paths, not a promise that those paths are current. The original folder was observed on Desktop on November 3; the supplied November 5 kit assumes Documents. Use the directory that exists on this device.

The check prints a session directory and writes `SESSION_STATUS.json` even if the scientific import/test stage fails. It fetches GitHub references, preserves all local changes, and reports the actual local HEAD and fresh `origin/main`. A fetch does **not** update the working tree. If they differ, review the newer commits and unpushed remediation before choosing the scientific checkout. It then runs:

1. New unit/integration contract tests.
2. The live-checkout adapter against known-truth synthetic readers and actual production preprocessing/registration/segmentation/LUT/stitching functions.
3. Affected existing project tests, with an actual JUnit report.

Use `bash CHECK_AND_VERIFY.sh --full` once instead if you want the full existing test suite. Missing/renamed tests, failed imports, failures and skips remain visible; they do not become a pass. No package installation or certificate bypass is performed. If dependencies are missing, use the existing validated scientific environment or create an isolated environment using the checkout's own dependency declarations.

Before any new plate processing, inspect the existing `full-plate-registration-*` run and any active legacy process. A printed `[60/192]` is not a completion receipt. This command inventories an exact old result directory without modifying/importing it:

```bash
"$TMEM_PYTHON" "$TMEM_KIT/reconcile_legacy.py" \
  --root "$TMEM_LEGACY_RUN" \
  --out "$TMEM_PRIVATE_BASE/LEGACY_RUN_RECOVERY.json"
```

`TMEM_LEGACY_RUN` must be that actual old output directory. Reuse requires matching original/config/code/output provenance; the tool deliberately does not promote legacy CSVs into task successes. Do not schedule duplicate plate work while that reconciliation is unresolved.

## 2. Inventory the entire February folder

On Mac/allocated compute, create a **new** output directory name; do not pre-create the inventory directory:

```bash
export TMEM_INVENTORY="$TMEM_PRIVATE_BASE/inventory_$(date -u +%Y%m%dT%H%M%SZ)"
"$TMEM_PYTHON" -B "$TMEM_KIT/full_dataset.py" inventory \
  --root "$TMEM_RAW_ROOT" --out "$TMEM_INVENTORY" \
  --profile "$TMEM_KIT/february.profile.json" --expect-february-counts
```

This scans **every ND2 header and declared position**; it never calls `asarray` or decodes pixel arrays. Each header is an atomic checkpoint. `INVENTORY_PRIVATE.json` reports unreadable files, unparsed names, multiple acquisition files, missing visits, channel metadata, T/Z and P axes. It reports the expected 1,728 fluorescence + 192 Day-8 brightfield count separately. For an independently known plate roster, add `--expected-wells /actual/acquisition_wells.json` (a JSON list of actual well IDs); otherwise an entirely absent well cannot be inferred from observed filenames.

Empty scans fail. Linked sources are excluded and reported. P=1 or absent P is **not** proof of full-well coverage. Brightfield is counted separately and never silently used as the fluorescence reference.

## 3. Produce original-image graphics immediately, before site matching

This bounded diagnostic can run without fabricating longitudinal site correspondence:

```bash
export TMEM_PREVIEWS="$TMEM_PRIVATE_BASE/original_previews_$(date -u +%Y%m%dT%H%M%SZ)"
"$TMEM_PYTHON" -B "$TMEM_KIT/preview_originals.py" \
  --inventory "$TMEM_INVENTORY/INVENTORY_PRIVATE.json" \
  --profile "$TMEM_KIT/february.profile.json" --repo "$TMEM_REPO" \
  --wells E05 F05 --days 8 12 --max-files 4 --out "$TMEM_PREVIEWS"
open "$TMEM_PREVIEWS/OPEN_ACTUAL_IMAGE_FLOWCHARTS.html"
```

Choose other actual wells as needed. The four-file limit is explicit, not an all-dataset result. **Every P position in each selected file is extracted.** Graphics include the selected original pixels, executed preprocessing and actual local segmentation intermediates when enabled. Without authenticated site matching, alignment/tracking are unavailable, not invented. The full manifest worker in step 4 adds longitudinal alignment, tracking candidates and same-image LUT-box comparisons.

Default preprocessing has no flatfield/darkfield/background: IC nodes are explicitly skipped. To claim actual IC before/after, the source-bound observations must supply the **actual** calibration arrays and their provenance, e.g.:

```json
"calibration": {
  "flatfield": {"path": "/actual/flatfield.npy", "sha256": "ACTUAL_SHA256", "channels": ["405", "561", "488"], "provenance": "actual detector-coordinate acquisition calibration"},
  "darkfield": {"path": "/actual/darkfield.npy", "sha256": "ACTUAL_SHA256", "channels": ["405", "561", "488"], "provenance": "actual camera dark acquisition"}
}
```

Add this to each applicable observation in the site map **before** planning. No calibration is inferred or called historical from a median estimate. Calibration files must be NumPy arrays with finite values, positive flatfield values, valid broadcast shape and explicitly canonical channel order. Do not apply a field calibrated for another detector/visit.

## 4. Authenticate sites, plan, then run a real pilot

`SITE_MAP_UNVERIFIED_PRIVATE.json` is a complete position checklist, not a verified mapping. Fill it using the Nikon acquisition plan/stage metadata/landmarks. Each observation needs an authentic cross-day site ID, explicit P/T/Z indices, one uniquely matched channel metadata label per role, and an acquisition evidence file plus reason. P indices can change between visits: map the actual physical sites, not array-order guesses.

Alternatively normalize the genuine instrument site table to CSV columns `path,position,site`, with one row per actual ND2 position. The following maps channels independently from each file's metadata:

```bash
"$TMEM_PYTHON" "$TMEM_KIT/prepare_site_map.py" \
  --inventory "$TMEM_INVENTORY/INVENTORY_PRIVATE.json" \
  --profile "$TMEM_KIT/february.profile.json" \
  --acquisition-csv "$TMEM_PRIVATE_BASE/MICROSCOPE_SITE_MAP.csv" \
  --reason "Cross-day sites authenticated against the original microscope acquisition log" \
  --out "$TMEM_PRIVATE_BASE/SITE_MAP_PRIVATE.json"

export TMEM_MANIFEST="$TMEM_PRIVATE_BASE/FIELD_MANIFEST_PRIVATE.json"
"$TMEM_PYTHON" -B "$TMEM_KIT/full_dataset.py" plan \
  --inventory "$TMEM_INVENTORY/INVENTORY_PRIVATE.json" \
  --site-map "$TMEM_PRIVATE_BASE/SITE_MAP_PRIVATE.json" \
  --profile "$TMEM_KIT/february.profile.json" --repo "$TMEM_REPO" \
  --out-root "$TMEM_PRIVATE_BASE/field_results" --out "$TMEM_MANIFEST"

export TMEM_PILOT_OUT="$TMEM_PRIVATE_BASE/real_pilot_$(date -u +%Y%m%dT%H%M%SZ)"
"$TMEM_PYTHON" -B "$TMEM_KIT/full_dataset.py" pilot \
  --manifest "$TMEM_MANIFEST" --wells E05 F05 --out "$TMEM_PILOT_OUT"
```

The planner rejects unmapped positions, duplicate source selections, missing visits, ambiguous per-file channels, and T/Z>1 without a validated policy. It does not silently discard extra planes. `--allow-subset` is only for an explicitly labeled subset; it cannot generate a full-dataset Swarm.

The pilot retains all selected visits and all authenticated sites in two actual wells, runs serial and two-worker executions separately, compares every output byte/hash and diagnostic result, checks original source immutability, measures wall time/RSS, and verifies an exact-source resume does not recompute. It is stricter than the minimum two-day test: a nine-day manifest receives a nine-day pilot. It preserves QC failures. Passing means reproducible execution, not scientific acceptance.

You can also run an explicit task with:

```bash
"$TMEM_PYTHON" "$TMEM_KIT/full_dataset.py" run \
  --manifest "$TMEM_MANIFEST" --task E05__ACTUAL_SITE_ID
```

Use the exact `id` listed in the manifest. If a process is killed, `ACTIVE.lock` remains; confirm the original job is dead and reconcile its retained attempt before removing that **one** lock. No automatic stale-lock removal or overwrite is allowed. Different source/config/input evidence requires a new manifest/output root.

## 5. Run on a WELL basis when actual stitching geometry exists

Located existing code: `src/tmem_align/audit_v1/stitching.py::assemble_well`, with CLI entry points `scripts/assemble_tmem_well.py` and `scripts/register_tmem_well.py` in the inspected source snapshot. The adapter checks the actual checkout when executed.

The verified existing assembler performs channel-preserving arithmetic mean overlap at explicitly provided **integer detector-coordinate offsets**. It does not infer tile order, stage/camera orientation, rotation or an affine calibration. A synthetic grid is not an acquisition plan.

Copy `geometry.TEMPLATE.json` to a private file. Supply each well's real shared canvas and **every authentic site's placement on every visit**, with source calibration/landmark evidence. `coordinate_model` must become `verified_integer_translation` only after that model is actually verified. Then:

```bash
"$TMEM_PYTHON" "$TMEM_KIT/full_dataset.py" well-plan \
  --manifest "$TMEM_MANIFEST" --geometry "$TMEM_PRIVATE_BASE/GEOMETRY_PRIVATE.json" \
  --out-root "$TMEM_PRIVATE_BASE/well_results" \
  --out "$TMEM_PRIVATE_BASE/WELL_MANIFEST_PRIVATE.json"
```

Use that well manifest for the pilot and later Swarm. Each task first preprocesses **all** real fields for a visit, assembles the mosaic, stores coverage and seam diagnostics, then registers the ordered **well mosaics**. It does not register independent FOVs and relabel them whole wells. Unobserved gaps remain NaN; they are saved and stop registration until a validated support-aware adapter is available. Current assembly requires three canonical channels and a maximum 40-million-pixel canvas. Off-axis calibration and five-channel Cell Paint mosaic support remain explicit limitations. A mosaic still does not prove physical well coverage without a well outline/acquisition plan.

## 6. Biowulf/Swarm after the real pilot

All paths must point to actual files **on Biowulf**. Neither a Mac path nor this ZIP transfers the raw acquisition folder. Run heavy work on allocated compute.

```bash
export TMEM_KIT="/data/$USER/tmem_hpc_private/TMEM106B_FullDataset_v2_20261105"
export TMEM_RAW_ROOT="/data/$USER/ACTUAL_ND2_SOURCE"
export TMEM_OUT_ROOT="/data/$USER/tmem_hpc_private/inventory_v2_20261105"
export TMEM_PYTHON="/data/$USER/VALIDATED_ENV/bin/python"
# Replace ACTUAL_ND2_SOURCE and VALIDATED_ENV before submitting.
sbatch --export=ALL "$TMEM_KIT/submit_inventory.sbatch"
```

The new inventory output directory must not already exist. The supplied older kit instructed `mkdir -p` for it; this version deliberately creates it itself to preserve prior receipts. The scripts use durable private output directly; they do not reserve unused lscratch. If adding scratch staging later, explicitly copy/verify durable results before job exit.

For the actual serial/two-worker pilot, set `TMEM_MANIFEST`, `TMEM_PILOT_OUT`, `TMEM_PILOT_WELL_A`, `TMEM_PILOT_WELL_B` on Biowulf, then `sbatch --export=ALL "$TMEM_KIT/submit_pilot.sbatch"`. The 48 GB/4-CPU/6-hour pilot request is a starting allocation, not a measured runtime guarantee.

Generate commands only after the corresponding real pilot passes:

```bash
"$TMEM_PYTHON" "$TMEM_KIT/full_dataset.py" swarm \
  --manifest "$TMEM_MANIFEST" \
  --pilot-report "$TMEM_PILOT_OUT/REAL_PILOT_REPORT_PRIVATE.json" \
  --out "$TMEM_PRIVATE_BASE/all_verified_well_sites.swarm"

# Set TMEM_GB from the measured pilot peak plus headroom.
# Verify time/storage needs and inspect the generated command file first.
swarm --devel --maxrunning 8 -g "$TMEM_GB" -t 2 --time 06:00:00 \
  --logdir "$TMEM_PRIVATE_BASE/logs" --err-exit \
  "$TMEM_PRIVATE_BASE/all_verified_well_sites.swarm"

# Submit the same reviewed commands after the dry run:
swarm --maxrunning 8 -g "$TMEM_GB" -t 2 --time 06:00:00 \
  --logdir "$TMEM_PRIVATE_BASE/logs" --err-exit \
  "$TMEM_PRIVATE_BASE/all_verified_well_sites.swarm"
```

Keep nine ordered visits within one task. Eight concurrent tasks is a cap, not a demonstrated optimal I/O rate. Start lower if pilot reads saturate shared storage. Never run a heavy full-plate job on the login node. Official usage: https://hpc.nih.gov/apps/swarm.html and https://hpc.nih.gov/docs/userguide.html.

## 7. Aggregate all expected tasks and review actual images

```bash
"$TMEM_PYTHON" "$TMEM_KIT/full_dataset.py" aggregate \
  --manifest "$TMEM_MANIFEST" --hash-inputs \
  --out "$TMEM_PRIVATE_BASE/PLATE_STATUS_PRIVATE.json"
"$TMEM_PYTHON" "$TMEM_KIT/render_coverage.py" \
  --manifest "$TMEM_MANIFEST" --out "$TMEM_PRIVATE_BASE/PLATE_COVERAGE_PRIVATE.svg"
```

The plate diagram places actual well IDs on A–P/01–24 axes; grey means outside the supplied manifest, not a measured empty well. Aggregation verifies expected/completed/failed/missing/active/invalid tasks and every saved output checksum. QC-failed visits remain amber. `execution_complete` is separate from accepted neuron identities and whole-well coverage.

Per-task outputs include per-visit preprocessed and registered `.npy`, actual channel remaps, frozen registration QC, stage JSON, PNG previews, a self-contained `ACTUAL_IMAGE_FLOWCHART.svg`, candidate soma diagnostics, and LUT-box before/after panels. Full-array recording for **every** intermediate is optional via `trace_arrays:true`; by default compact stage previews/hashes avoid duplicating multi-terabyte float intermediates. That omission is explicit per stage. Changing this setting changes the bound manifest and pilot; do not edit a running manifest. For bounded devices, optional processing `array_storage:"npy.gz"` stores final preprocessed/registered NPY arrays through deterministic lossless streaming gzip (no precision or geometry change). Default is `npy`; the choice is source/config-bound and does not reduce registration RAM. Coverage/stage arrays and all QC remain unchanged. Read compressed arrays with `gzip.open(path,"rb")` and `np.load(stream,allow_pickle=False)`.

## Parameters, I/O and what the outputs mean

| Item | Input | Output / interpretation |
|---|---|---|
| Selection | Original ND2 header + explicit P/T/Z | Exact CYX detector pixels; no implicit projection/resize |
| Channels | Every file's actual metadata + role map | Canonical order; later channel swaps corrected independently |
| IC | Actual hashed detector-coordinate flat/dark arrays | Before/float dark/field/float IC/background/quantized previews; absent calibration explicitly skipped |
| Registration | Ordered visits, declared structural channel | Current checkout's frozen defaults and retained failures |
| Segmentation/tracking | 488 only, current production functions | One automatic diagnostic exemplar per site, not an all-neuron census or accepted identity |
| LUT preview stub | Real array + explicit fixed low/high | Display-only preview; never supplies measurement pixels |
| LUT bbox | `low < 488 <= high`, connected component at anchor, bounded spatial search | Proposed viewing box; neither ROI adoption nor measurement geometry change |
| Robustness | Bounded bbox/template/search/min-area configuration | Resolved settings, min-area ±40/Jaccard and search-radius ±20/anchor alternatives; no automatic rescue or threshold relaxation |
| mCherry | Explicit reporter assay/rows | Nonreporter C/D/G/H/K/L = N/A; reporters E/F/I/J/M/N remain unaccepted diagnostics |
| Well assembly | All real sites + authenticated offsets | Actual mosaic/coverage/seams before well-level registration |

The LUT-box panel quantifies **inspection area reduction**, not a measured segmentation accuracy gain. Tracking scores and global registration correlation are different metrics. Default fixed display limits are illustrative; choose and record assay-appropriate LUTs before planning. Display limits cannot turn failed registration into a pass. Frozen Day32/36/39 failures and historical exclusions are not overwritten.

## 8. Test a separate Cell Paint batch

Copy `cellpaint.profile.TEMPLATE.json` to a private profile and replace **actual visits, every exact channel label and structural role** from the new acquisition metadata. It deliberately has no neuronal segmentation/561 phenotype assumptions. Run a new inventory with `--profile` and **without** `--expect-february-counts`, then original-image previews, per-file remapping checks and a separate serial/two-worker pilot using authenticated sites. Do not reuse February calibration/anchors/site geometry or label a repeated February run external validation.

The ND2 filename parser expects `WellA01`/`DayN` labels; other naming schemes, multi-Z/T data and five-channel mosaics remain unsupported until explicitly tested. The separate TIFF adapter below was exercised on ten real independent JUMP TIFFs,two five-channel fields,one acquisition, with metadata role/hash verification and serial/parallel equality. Its scope is ingestion/preprocessing/LUT portability. Broader usability needs representative additional fields and reference annotations; Cell Painting segmentation/temporal tracking/biological accuracy were not validated.

### Independent single-acquisition TIFF input

`preview_cellpaint_tiff.py` supports a separately authenticated five-role TIFF batch. The private manifest must bind every DNA/ER/RNA/AGP/Mito image and its exact role/filename metadata by SHA256, actual field timestamp and a uniquely selected experiment-metadata row proving one imaging pass. Each source must be a scalar uint16 YX plane; no projection, resize or temporal axis is invented. Raw and preprocessed CYX arrays, per-role fixed-LUT `render_preview` outputs, skipped calibration stages and failure receipts are retained outside Git. LZW TIFFs use the existing Pillow/libtiff decoder only when tifffile lacks imagecodecs, preserving all header and exact-value gates.

```bash
PYTHONPATH="$TMEM_REPO/src:$TMEM_REPO/tools/full_dataset_v2" \
"$TMEM_PYTHON" -B "$TMEM_REPO/tools/full_dataset_v2/preview_cellpaint_tiff.py" \
  --repo "$TMEM_REPO" --manifest /actual/private/CELLPAINT_MANIFEST.json \
  --out /actual/private/new_cellpaint_diagnostics --compare-workers
```

The serial/two-worker check compares every field result and artifact hash, then verifies all originals, metadata, manifest and source remain unchanged. This tests ingestion/preprocessing/display portability. Cell Paint segmentation, temporal tracking, calibration benefits and whole-well coverage remain unvalidated; February neuronal models and geometry are not applied.

## 9. Publish the new source to GitHub

For the preserved November5 recovery session, use its reviewed `RESUME_EXISTING_MAC.sh` and existing branch. Do not restart the old launcher or use the initial standalone publisher below to create another worktree. The verified recovery and subsequent source-only increments are recorded in the root ledgers.

Source publication uses an isolated branch and, when GitHub CLI authentication permits, a draft PR. Existing local fixes stay in their current checkout. For an initial standalone-kit publication, after local verification:

```bash
bash "$TMEM_KIT/PUSH_SOURCE.sh"
```

This fetches current `origin/main`, creates an isolated new worktree/branch, copies only the explicit code/test/docs allowlist, runs new contracts + live science adapter + affected existing tests, commits and pushes, and verifies the remote SHA. With authenticated `gh`, it opens a draft PR; otherwise it prints the exact compare URL. It never merges, force-pushes, stages your existing unrelated changes, or publishes private originals/figures/results. Your existing unpushed remediation is preserved in its original checkout and still needs its own reconciled verification/publication; this script does not quietly copy it onto main.

If Git author identity is missing, set your real identity in that repository and rerun the final commit/push in the preserved publication worktree; do not invent an identity. A package test pass is not a verified GitHub push. Retain `PUSH VERIFIED` and CI receipts.

## Claire / collaborator folder

`CLAIRE_PACKET_CHECKLIST.md` defines the technical review packet. Copy only source-bound real pilot stage graphics, QC/failure summaries, measured alignment/LUT inspection changes and a parameter/I/O explanation into a private share folder. Keep original ND2 inputs and full pixel traces on approved storage. This package prepares review material; nothing has been sent.
