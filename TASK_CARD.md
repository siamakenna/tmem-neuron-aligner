# MAC-RECOVER — one bounded Codex task

Goal: recover the already-created publication branch on this Mac, run its real checks and push only the verified source/docs. Read AGENTS.md, PROJECT_STATE.md, NEXT_TASKS.md, EVIDENCE.md and tools/full_dataset_v2/README.md first.

Existing session: $HOME/Downloads/tmem_finish_1KkiKJ3Z
Existing checkout: $HOME/Downloads/tmem_finish_1KkiKJ3Z/results/publication/source
Expected branch: completion/full-dataset-v2-20261105T165938Z-bc25f12f
Logged baseline HEAD: 47a2db795133e4b6a79baf5d5f3b36855d857dec

The old script failed before commit/push because FakeND2.files used unresolved temporary paths. Apply the canonical-path-only fixture fix plus symlink regression. Do not relax source/site/QC checks. Existing scientific Python: $HOME/Downloads/tmem_completion_9cbf60nt/venv/bin/python, or the failed session's venv/bin/python if present; probe before choosing. Never disable TLS verification.

Use the supplied RESUME_EXISTING_MAC.sh with --verify-only first. It patches only the known old fixture hash, preserves instructions on conflict and runs the existing verification runner in a new private log directory inside the SAME session. Inspect source diff and fresh origin/main before running with --publish. Publication is source-only and already authorized; no merge or force push. If current main changed, inspect compatibility and record the difference; do not silently reset or rebase user changes.

Acceptance: 49new contracts pass on this Mac; the actual production-function adapter and affected existing tests pass; source unchanged while testing; staged diff contains only tools/full_dataset_v2, its workflow and the reconciled project instruction docs; normal push verified against remote SHA. Save a receipt and update the ledgers. Stop after two failed approaches with the exact log and next diagnostic.

Excluded: new plate jobs, raw-data transfer, publication of image results, changing LUT/segmentation/QC policies, whole-well claims without acquisition geometry, and unrelated improvements. After acceptance, the next ticket is the authentic original-ND2 pilot; do not report that ticket complete from fixture tests.
