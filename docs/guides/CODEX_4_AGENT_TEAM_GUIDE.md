# Codex 4-Agent Team Guide

This repo has a project-scoped Codex workflow for safe, staged TMEM neuron-alignment development.

## Files

```text
AGENTS.md
.codex/config.toml
.codex/agents/planner.toml
.codex/agents/coder.toml
.codex/agents/tester.toml
.codex/agents/reviewer.toml
.agents/skills/ship/SKILL.md
prompts/chatgpt-codex-web-prompt.md
```

Temporary handoff files are written to `.pipeline/` and ignored by Git.

## Roles

- Planner writes `.pipeline/spec.md`.
- Coder implements the spec and writes `.pipeline/changes.md`.
- Tester adds/runs focused checks and writes `.pipeline/test-results.md`.
- Reviewer inspects the diff read-only and returns `SHIP`, `NEEDS WORK`, or `BLOCK`.

## Recommended Use

Start Codex from the repo root:

```bash
cd LOCAL_USER_HOME/Documents/tmem_neuron_aligner
codex
```

Then ask for a scoped change:

```text
Use $ship to make Stage A dry-run manifests robust for empty raw roots and add tests.
```

For processing-scale requests, include the intended wells, stages, output root, and whether the run is approved. The default is no heavy run until the expected read/write size and overwrite behavior are reported.

## TMEM Safety Defaults

- Raw ND2 files are read-only.
- Large microscopy outputs stay outside Git.
- Use `--resume`, `--overwrite false`, and `--max-workers 1` unless approved otherwise.
- Six-well pilot first: `E05,F05,I05,J05,M05,N05`.
- Full 96-well mCherry-valid processing requires explicit approval.
- Stages D-G, every-neuron extraction, and full OME-Zarr export require explicit approval.

## Review Artifacts

After a `$ship` run, inspect:

```bash
cat .pipeline/spec.md
cat .pipeline/changes.md
cat .pipeline/test-results.md
cat .pipeline/review.md
git diff
```

Do not merge or run heavy processing until a human has reviewed the diff and the review file.

## Example Pilot-Planning Prompt

```text
Use $ship to make scripts/run_full_dataset_queue.py ready to execute stages A,B,C for E05,F05,I05,J05,M05,N05 only. Keep --resume and --overwrite false, estimate read/write size before execution, and do not run the pilot until I approve the exact command.
```
