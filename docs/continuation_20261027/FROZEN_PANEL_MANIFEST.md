# Frozen diagnostic selection policy

Manifest: [portable_20261027_v1.json](../../configs/panels/portable_20261027_v1.json), schema `tmem.panel_selection.v1`, version `portable-20261027.v1`.

It preserves the original October 27 panel rather than retrospectively selecting a more favorable sample. Its historical benchmark-summary hash binds the original record; master and all six declared stack checksums bind the dataset. The primary configuration hash preserves area=180/radius=60 and other parameters.

The exact selection order is:

1. E05_N057
2. F05_N005
3. I05_N052
4. J05_N029
5. M05_N009
6. N05_N010
7. E05_N066
8. F05_N061
9. I05_N006
10. J05_N028
11. M05_N022
12. N05_N022

Eligibility requires exactly days 8, 12, 16, 20, 25, 29, 32, 36, 39 and original time indices 0–8, finite unchanged 488-derived anchors and valid Boolean tracking flag syntax. Both true and false tracking flags are preserved; validity is not optimized away. Selection uses SHA256(seed + separator + ID), ascending within each well, rank-first round robin. Seed is fixed in the manifest. No 561 measurements, image outcomes or biological acceptance enter selection.

Historical exclusions are explicit with provenance. They distinguish prior diagnostic examples from known exclusion/technical cases; being previously documented is not itself a biological exclusion judgment. The conservative N05_N012 selection exclusion does not resolve the separately ambiguous N012 packet identity required by the scientific release policy.

Reconstruct selection without reading registered stacks:

```bash
../.venv-local/bin/python scripts/verify_frozen_panel.py --dataset ../dataset
```

This rechecks the small master table, reconstructs all selected IDs/order and compares the versioned policy to declared dataset checksums. It intentionally reuses completed stack verification; its output says stacks were not rehashed or reprocessed.

Future benchmark execution defaults to this explicit manifest. A different dataset, seed, count, exclusion set or configuration requires an intentionally versioned matching manifest and frozen selected IDs. Undeclared additional exclusions are rejected. The historical `mentioned_ids` helper is retained only for audit compatibility and is not called by execution. Editing documentation cannot alter this policy.

The original completed benchmark is not rewritten and must not be rerun simply to exercise the fix. This is not a held-out panel or an accepted biological cohort.

## Freeze a separate future diagnostic panel

After separately verifying the dataset, declare a new version and seed, and write a **new** policy file:

```bash
../.venv-local/bin/python scripts/freeze_diagnostic_panel.py \
  --dataset ../dataset --prior configs/panels/portable_20261027_v1.json \
  --version portable-next.v1 --seed explicitly-declared-next-seed \
  --tracks-per-well 2 --out ../private-next-panel-policy.json
```

The freezer reads the small master only, inherits every explicit historical exclusion, excludes all prior selected IDs with provenance, and refuses an existing output. It never scans documentation, reads 561 outcomes, repairs QC, or declares the new panel held out/biologically accepted. Review and version the resulting source-safe policy deliberately before execution. Do not execute another panel merely to test this command. A different master/data contract requires its own separately verified provenance; this project's original transfer contract remains frozen.
