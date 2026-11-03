# Run directly in Terminal

No coding-agent installation or Biowulf session is required. The companion source-bound patch launcher creates its own fresh clone/continuation branch and private Python environment on the Mac. It refuses a different main commit or mismatching source rather than overwriting an existing project. Original images and prior checkouts remain in place.

## From an already prepared checkout/environment

Run `python scripts/run_terminal_completion.py --help` to inspect all options. Choose a new private output directory outside the repository and original-data tree:

```bash
python scripts/run_terminal_completion.py --out /absolute/private/new-run
```

This renders the workflow designs and prepares a stress packet before running new unit controls, production unit→integration verification and ND2/stitching regressions. Exit `2` with `software_passed_scientific_validation_pending` distinguishes completed software checks from pending experimental validation. A software failure has exit `1`; neither result grants scientific acceptance.

## Execute an original ND2 pair

Supply two original fluorescence acquisitions from the same intended well at different visits. Multi-position/time/Z observations require explicit selection; do not choose a convenient position implicitly.

```bash
python scripts/run_terminal_completion.py \
  --out /absolute/private/new-original-pair-run \
  --reference-nd2 /absolute/original/reference.nd2 \
  --moving-nd2 /absolute/original/moving.nd2
```

For non-singleton P/T/Z axes, add `--selection-json /absolute/private/selections.json`, whose `reference` and `moving` objects specify `position`, `time` and/or `z` indices. Reported channel order must agree with the implemented 405/561/488 interface. Contradictory optical metadata remains unresolved even when these labels match.

Extraction verifies selected original pixels against the OME-TIFF result. The field trace records raw/preprocessing/alignment arrays and previews; absent IC/background correction is marked skipped. To apply a genuine flatfield, use `--flatfield` and `--flatfield-provenance`; the latter must declare detector coordinates, source and the matching file hash. A scalar dark offset is explicitly declared rather than called a measured calibration.

## Reuse existing segmentation/tracking evidence

Add `--existing-trace /absolute/private/prior-stage-trace` to render verified recorded segmentation/tracking panels without rerunning the completed 12-track benchmark. The renderer labels the actual input kind; registered-stack evidence is not retroactively original-ND2 IC/stitching evidence.

## Whole-well route

Inspect `configs/original_nd2_well.template.json` and `scripts/trace_original_nd2_well.py --help`. The template deliberately contains unresolved evidence. Supply only real, source-bound geometry, channel mapping, correction provenance, every intended observation and all nine visits. Pass an actual manifest with `--well-manifest /absolute/private/well.json`; never set validation fields merely to make the program proceed. Read `STITCHING.md` for the current integer-placement model's limits.

## Inspect results and publish

- `RUN_STATUS.json`: separate software, original-image, graphics, stress-packet and scientific status.
- `STEP_STATUS.json`, `logs/` and JUnit XML: actual commands, exit codes and failures/skips.
- `production_verification/`: existing unit→integration report and labelled synthetic IC/alignment control.
- `workflow_graphics/`: generated designs; optional original-field/existing-trace graphics are separate.
- `Claire_stress_tests.zip`: prepared source-bound independent test request, not a delivery receipt.
- Original-pair output: extraction/source hashes, exact-pixel roundtrip, actual stages and image-linked graphics.

The companion launcher publishes only the declared code/tests/docs/designs and a path-free software summary after all required software, graphic, stress and source-immutability checks pass. Private images, arrays, logs, correction fields and original paths stay outside Git. A failed push retains the local commit and session; resume the recorded session instead of starting another run.

Read actual status before describing completion. Pending well geometry/IC/identity evidence remains pending after a verified software push.
