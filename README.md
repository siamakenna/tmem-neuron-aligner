# TMEM106B Neuron Aligner

Longitudinal neuron identity uses **488 only**. The **561/mCherry channel**
supports phenotype measurement after identity and ROI geometry have been fixed.

The current review snapshot adds portable software verification, inspectable
processing stages, fixed longitudinal display limits and a manual-review export
gate. It preserves the historical candidate atlas and registered crops.

## Current instructions

The [October 27 processing-stage guide](docs/diagnostics_20261027/PIPELINE_GUIDE.md)
documents numerical outputs and fixed-LUT previews from the actual preprocessing,
registration, soma tracking, segmentation, consensus and phenotype functions.
Each recorded step saves its pixels or mask, parameters, purpose and fingerprints.
Registered-track diagnostics preserve stored geometry and label missing historical
IC/stitching/alignment evidence explicitly. LUT-derived boxes are viewing proposals.

Run unit checks followed by production integration and affected regression tests:

```bash
PYTHONPATH=src:. python scripts/verify_stage_pipeline.py --out /path/to/new-verification
```

The verification report records actual results and blocks success on failures,
missing dependencies or skipped required tests. Its known-truth image example
tests software behavior. Real diagnostic reports and biological improvement
require their own source images and evidence; completion does not approve tracks.

The [Friday analysis and collaborator handoff](docs/friday_completion_20261023/README.md)
adds evidence-checked matched-well summaries and clearly labeled synthetic
figure examples. Actual biological comparisons still require accepted data
from the matched wells and the current review decisions. The completed Mac
baseline is preserved as prior verification; only new additions were retested.

Read [the implementation and scope guide](docs/audit_v1/IMPLEMENTATION.md).
An extracted Claire handoff has top-level `CLAIRE_README.md` and `index.html`
with exact environment, verification, review and return commands. These are the
authoritative handoff instructions. A Git checkout is unnecessary for its runner.

Current entry points:

- [Portable verification](scripts/run_claire_verification.py)
- [Review workspace generation](scripts/build_review_workspace.py)
- [Manual-review metric export](scripts/export_reviewed_metrics.py)
- [Stage diagnostics](scripts/run_tmem_audit.py)
- [Production intermediate traces](scripts/trace_tmem_pipeline.py)
- [Unit-to-integration verification](scripts/verify_stage_pipeline.py)
- [Explicit-coordinate well assembly](scripts/assemble_tmem_well.py)
- [Whole-well longitudinal registration](scripts/register_tmem_well.py)

## Scientific scope

The handoff includes three candidate examples across nine visits each:
`J05_N015`, `N05_N011`, and the known multi-neuron exclusion `F05_N025`.
Historical positive-reference labels do not constitute renewed approval.
All three are from TMEM106B wells and cannot establish a control comparison.

The biological replicate structure is three matched well pairs: E05/F05,
I05/J05, and M05/N05. Individual neurons provide measurements within wells and
do not increase the number of independent biological replicates.

Punctate and diffuse mCherry are a computational phenotype decomposition. They
do not establish rupture, fibrils, or another specific mechanism.

## Data policy

Large ND2 images, registered TIFF stacks, and MP4 reviews remain in the data
layer. The source and handoff contain code, configuration, compact fixtures,
diagnostics, exact fingerprints and clearly labeled verification evidence.
Original acquisition tile geometry and independently reviewed physical
calibration require their supporting inputs.
