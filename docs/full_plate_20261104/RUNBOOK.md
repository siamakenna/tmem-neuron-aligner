# Full-plate continuation adapters

## Reviewed-repair boundary (new future workflow)

The future runner uses v2 run/receipt/aggregate schemas. It does not migrate v1 receipts or legacy selected-only folders. Header preflight checks exact declared well/day/filename-sequence identity, regular unique source paths/inodes, CYX shape/dtype and complete consistent named-channel order. Header and filename agreement is not physical acquisition authentication. Optical conflicts remain UNRESOLVED. Before delegation the same checks repeat, and the actual legacy loader's arrays and channel names must agree. Brightfield, multiple observations, alternate channel/site/row-map configurations and nonreporter phenotype output fail closed.

All Python source files under `src/tmem_align` and `scripts`, exact contract/selection/reference-config contents, actual anchored/QC parameters, measurement defaults and Python/dependency versions are fingerprinted. The frozen stage-diagnostics reference is hashed for provenance but is **not applied** by the whole-field legacy worker. Future scheduled raw files receive chunked content SHA256 plus stat/inode metadata; saved-header/stat-only evidence is not relabelled content verification. No such real-image work is required to inspect or test the software.

Per-well results carry a canonical payload hash. Finalized aggregate receipt/table hashes and exact task set are checked before any worker is scheduled. Invalid future checkpoints produce private owner-only diagnostic quarantine copies/reports while original bytes remain untouched. Corrupt or incompatible evidence never triggers automatic recovery. Failed receipts remain failed. Shared final-table validation reconciles QC/failures, reporter-only measurement coverage and independently reconstructed summary keys/counts/metrics before finalization. Missing phenotype values never become zero.

For the source-supported corrected presentation, add `--revision V3` to the existing generator command. V2 defaults remain compatible and exported prior versions stay unchanged. V3 uses broad registered structural fields on its first two slides and keeps the ambiguous N05 example in the dedicated support discussion. `visit_08` means zero-based index 8 (Day 39), checked against the bound trace and winning threshold ancestry, not Day 8. Filename well IDs are not certified optical FOVs.

Never launch a duplicate real run while the original process is alive. Console progress is not a durable checkpoint. These tools do not change the legacy writer or its directory.

Use PYTHONPATH=src:scripts with the existing scientific environment. The optional presentation tool additionally uses python-pptx/Pillow.

Replace uppercase placeholders below with absolute paths. Paths containing `..` or symlinks are intentionally rejected, including sibling paths spelled with `../`; resolve the intended absolute path before invoking a CLI. Output directories must be new and outside the actual Git repository and source trees.

```bash
python scripts/audit_full_plate_run.py --run-dir EXISTING_RUN --dataset-config configs/tmem_full_plate_20261104.json --process-status RUNNING --out NEW_PRIVATE_AUDIT
python scripts/create_pi_presentation_v2.py --project PROJECT --curation PRIVATE_DECLARATION --plate-audit NEW_PRIVATE_AUDIT/run_audit.json --dataset-config configs/tmem_full_plate_20261104.json --out NEW_PRIVATE_DECK
```

The generic v2 contract supports variable schedules/sites/dimensions/channels and missing policy. The legacy execution adapter rejects multisite/alternate-axis inputs rather than pretend it implements arbitrary acquisition geometry. Confirmed geometry and reviewer confirmation are deliberately rejected without existing independent authentication. The TMEM configuration is frozen separately from generic primitives.

The legacy worker is TMEM-specific: the runner requires channels 488/561, an exact reporter-map match to the existing worker, and the single `stored_observation_coverage_unresolved` declaration. Every selected row must retain a nonempty `site_fov` filename-sequence token; that token is bound as source metadata and is not an authenticated physical FOV/site. Alternate physical-site contracts require a different adapter and are rejected here.

For a future justified retry only:

```bash
python scripts/run_checkpointed_plate.py --dataset-config STUDY_CONFIG --selection SELECTED_CSV --out NEW_PRIVATE_CHECKPOINT_RUN --workers 1
python scripts/run_checkpointed_plate.py --dataset-config STUDY_CONFIG --selection SELECTED_CSV --out SAME_CHECKPOINT_RUN --workers 1 --resume
```

The future runner locks one writer, hashes selected raw files, binds configuration/selection/code, writes each completed or failed well atomically, preserves failures and verifies resume bindings. It does not recover unsaved results from a legacy run. Resources and scientific defaults remain unchanged. Do not run a real worker comparison while another job saturates memory. Compare 1/2/4 workers on identical bounded inputs only when resource-safe; record wall time, actual peak RSS and numerical equality. Constructed executor tests are not microscopy benchmarks.

Mac: start with workers=1 on a 16 GB machine. Slurm example: request one task, explicit memory/time caps, workers no greater than allocated CPUs, outputs outside Git and raw inputs read-only. Pin the source commit and environment freeze. Submit no Biowulf job without authenticated access. Do not combine several unbounded stacks or parallel writers to one directory.

Curation requires explicit roles longitudinal/segmentation/tracking/ownership_ambiguous with bound figure/trace hashes, 488 basis, rationale and illustrative/ambiguous status. No ID-prefix, matching-score or 561-based hero fallback remains. Curation is not biological acceptance.

Keep all source paths, run receipts, detailed measurements, checkpoints, decks and rendered figures private. Run source/privacy review and focused tests before publication. Pending QC is unavailable, never zero. Nonreporter phenotype is missing/not applicable. Preserve all primary failures, ROIs, anchors, exclusions and separate final 561 review. Rendering/visual inspection remains a separate parent verification gate.
