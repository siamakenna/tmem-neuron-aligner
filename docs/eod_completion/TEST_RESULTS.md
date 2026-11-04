# Verification performed in the source-authoring session

Inspected baseline: `72c7ee058075af0e2c40b5ca0e909780967f502e`. The archive's SHA256 and Git PAX commit marker matched the supplied receipt; all 377 source files extracted safely.

## Targeted checks that passed

**131 unittest cases, 58 subtest observations, zero failures, zero errors, zero skips.** The machine-readable per-module counts are in `LOCAL_SOFTWARE_CHECKS.json`. Subtest observations are reported separately, not added to parent-case counts.

| Module | Cases |
|---|---:|
| Existing LUT visualization | 15 |
| Existing parameter resolution | 3 |
| Existing contracts / stitching / core | 30 |
| Existing StageTrace | 22 |
| Legacy ND2 selection / duplicate guards | 6 |
| Original-ND2 well manifest / provenance controls | 23 |
| Graphical renderer | 10 |
| Claire stress packet | 8 |
| Terminal orchestration | 14 |

Each module can be reproduced with `PYTHONPATH=src:scripts python -B -m unittest discover -s tests/audit_v1 -p 'test_MODULE.py' -v`, using the actual module filenames in the JSON record. The new original-ND2 tests use controlled reader/command fixtures; they do not establish a real ND2 or complete-well execution.

The companion installer/publication controls also passed **14 separate deployment checks**: precondition conflicts, path traversal, symlinks, content hashes, rollback, idempotency, wrong baseline, source changes, missing/failed/skipped phases, unrelated staged data and private-log exclusion from the public summary. These operating checks are not microscopy tests.

The explicit `within_range` example was accepted by the current configuration validator. Both design diagrams rendered to SVG and PNG and were visually inspected for readable labels and complete arrows. The stress ZIP's manifest/file checksums were verified; no collaborator delivery occurred.

## Full execution attempted and blocked

The final Terminal runner actually generated its workflow diagrams and source-bound stress packet. It then stopped at `new_unit_controls` because this authoring runtime has **no pytest**. Full production unit/integration and ND2 supplemental phases did not run. Scientific dependencies including `scikit-image`, `tifffile` and `nd2` are also absent here; a scoped package installation attempt returned no available distributions.

No full integration pass, real ND2 pixel run, accepted biological track or GitHub push is claimed for this session. The Mac launcher installs the declared dependencies in a private environment and requires actual successful unit/integration counts before publication. It records failures and does not suppress missing tests or skips.

## Historical evidence

Earlier 129/58/98 and 616-test reports describe overlapping or historical checkpoints. They were not rerun here and are not included in the 131 cases above. Existing real 12-track and original-field registration receipts remain separate private evidence, with their reported scientific failures and exclusions retained.
