# Scientific figure workflow

Command: `python scripts/generate_scientific_figures.py --synthetic --out NEW_DEMO`.
Example artifacts stay in ignored `outputs/friday_independent_completion/`.
Each PNG/PDF has the prominent watermark **SYNTHETIC EXAMPLE — NOT EXPERIMENTAL
RESULTS**. `figures/figure_index.json` records evidence type, paths and hashes.

| Figure | Implemented function | Current output | Real-data readiness |
|---|---|---|---|
| 1 Registration | registration_figure | Synthetic reference/before/after 488 with shift, overlap and QC | Needs verified image arrays and registration diagnostics |
| 2 Segmentation | segmentation_figure | Synthetic neighboring-cell example; detected mask vs construction truth | Needs independently reviewed comparison mask and source |
| 3 Nine-day tracking | tracking_figure | Synthetic trajectories and distinct nonaccepted status panel | Accepted analysis outputs and cohort ledger required |
| 4 Puncta/diffuse | phenotype_figure | Synthetic 561, 488-derived ROI, background, puncta and diffuse support | Needs actual intermediate arrays and fixed-region evidence |
| 5 Matched wells | matched_figure | Synthetic E05/F05, I05/J05, M05/N05 well means/counts | Sufficient accepted matched data required |
| 6 Survival | Deliberately not implemented | No plot; explicit blocked index entry | Confirmed fate/events/loss/censoring evidence required |
| 7 QC | qc_figure | Synthetic status counts/reasons and expected denominator | Accepted analysis plus complete cohort ledger required |

Real-analysis CLI renders 3/5/7 after recomputing source/review validity and
checking analysis table bytes. It indexes unavailable 1/2/4 as blocked rather
than deriving images from CSVs. Image plotting APIs support an evidence-supplied
caller; automatic real-image intake remains pending the required inputs.

The synthetic segmentation example deliberately shows a mask that includes
neighboring structure. Its IoU describes constructed truth only; it is not
real-neuron segmentation accuracy. Synthetic expression curves are prescribed
software inputs, never treatment estimates.
