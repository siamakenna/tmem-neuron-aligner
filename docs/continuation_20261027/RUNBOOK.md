# Run now, then continue without Biowulf

> **Complete-package local continuation supersedes this launcher.** The six registered stacks and source are now verified locally. Follow the latest section of [CODEX_NEXT.md](CODEX_NEXT.md), inspect existing results, and use direct local commands. Do not run the historical NIH-connected launcher below or repeat completed setup/tests. The remainder is retained as transfer-history documentation, not the current execution plan.

The new launcher publishes the code and these notes before starting image transfers or local processing. It uses the user's existing NIH Git identity in a new isolated worktree and creates a new `continuation/portable-20261027_<session>` branch. It never merges or force-pushes.

## Current Mac: one command

Download `TMEM106B_finish_hour_20261027.sh` from the conversation, then run this in a **local Mac Terminal**, not inside SSH:

```bash
bash "$HOME/Downloads/TMEM106B_finish_hour_20261027.sh"
```

The prepared launcher uses a **30-minute work budget**, then packages the transfer folder. Authentication and final copying/packaging can add time; the deadline is an execution budget, not a guarantee about network speed. NIH passwords are entered only in Terminal. No new cluster jobs are submitted.

1. Push the portable code, compact verified evidence, and Markdown notes. `GITHUB PUSH VERIFIED` gives the actual new commit.
2. Download a Git bundle so the second device receives real repository history.
3. Copy the frozen master and registered stacks for **all six wells**, validating hashes. About 2 GB of registered stacks travel; keep at least 8 GiB free for the data, environment, outputs, and transfer ZIP.
4. Preserve the original three-case result ZIP as separate evidence.
5. Run the portable control tests, create an isolated local environment, and run affected unit/integration checks. Python 3.11+ is required for this microscopy environment. Python 3.9/3.10 can still publish and transfer code/data; local microscopy then remains deferred.
6. Use the remaining time for up to two declared diagnostic candidates per well, at most two workers. A partial run is recorded as partial.
7. Push compact session/test/benchmark summaries, refresh the local Git bundle, and create `TMEM106B_portable_20261027_*_TRANSFER.zip` with a SHA256 sidecar.

Read `SESSION_RESULTS.md`, `SESSION_STATE.json`, and `PUSH_RECEIPT.json` in the generated folder for actual completion. The initial Markdown checklist is a packaging-time snapshot; later session receipts supersede it.

## If interrupted on the current Mac

Keep the printed `SESSION_FOLDER`. Reuse the same folder; do not create a fresh session merely to retry a download:

```bash
bash "$HOME/Downloads/TMEM106B_finish_hour_20261027.sh" \
  --session "/absolute/path/printed/as/SESSION_FOLDER" --minutes 20
```

Existing source bindings and published commits must still match. Completed transferred files are reused after checksum checks. New local benchmark outputs get a new timestamped directory; prior outputs remain preserved. If authentication or source verification fails, inspect `logs/` and the recorded error before retrying.

To publish and package only code/notes, omitting the six large stacks:

```bash
bash "$HOME/Downloads/TMEM106B_finish_hour_20261027.sh" --no-data --minutes 10
```

## Other device: no NIH connection

Transfer the whole `_TRANSFER.zip` and its `.sha256` sidecar using AirDrop, an external drive, or the user's existing file transfer method. Code also exists on the printed GitHub branch. GitHub alone does not include the image data.

On a Mac/Linux device, verify the ZIP before extracting. Replace the two paths below with the actual transferred ZIP and its containing folder:

```bash
cd "/folder/containing/the/transferred/ZIP"
shasum -a 256 -c TMEM106B_portable_20261027_SESSION_TRANSFER.zip.sha256
unzip -q TMEM106B_portable_20261027_SESSION_TRANSFER.zip
cd TMEM106B_portable_20261027_SESSION
bash CONTINUE_LOCAL.sh
bash START_CODEX.sh
```

`SESSION` above is a filename placeholder. `CONTINUE_LOCAL.sh` recreates a device-specific environment, restores Git metadata from `code.bundle` when needed, validates the data, and continues bounded work with **zero NIH connections**. It does not reuse the first device's virtual environment. If a Codex CLI is installed, `START_CODEX.sh` opens it in the repository with the saved continuation instructions; otherwise it prints the folder and prompt location for opening in the Codex interface.

The actual copy/paste Codex prompt is [CODEX_NEXT.md](CODEX_NEXT.md). Local image data lives beside `repo` in `dataset`; generated reports live in `benchmarks`. Keep both outside Git. Any later push from the second device uses that device's existing GitHub authentication.

## Boundaries that remain visible

- The six-well panel diagnoses existing algorithms; it does not itself prove that segmentation or tracking improved.
- This export contains registered stacks. Matching raw detector images and IC fields remain required for real-image IC/alignment before/after validation.
- A completed calculation, positive match score, or single-soma screen does not grant identity, ROI ownership, or biological acceptance.
- Prior review history is incomplete; the new declared panel is not described as held out.
- Preserve original anchors, nine visits, 488 identity rules, and independent 561 outcomes. No automatic acceptance or partial-visit accepted export is introduced.
