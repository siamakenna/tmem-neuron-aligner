# Actual registered-FOV processing figures

Use saved registered-track traces, their source portable dataset and a fresh private output directory:

```bash
python scripts/render_actual_fov_figures.py --traces EXISTING_TRACKS_DIRECTORY \
  --dataset EXISTING_DATASET_DIRECTORY --render-case E05_N057 \
  --render-case J05_N029 --days 8 16 32 --lut-low 200 --lut-high 2000 \
  --out NEW_PRIVATE_FIGURE_DIRECTORY
```

All discovered cases contribute all nine visits to tables. Only explicit cases/days receive large image sheets. Recorded numeric/preview hashes and live FOV-to-crop/master mappings are verified; no benchmark, segmentation, tracking or registration is rerun. Original-ND2 coordinates remain separate from historical registered atlas coordinates.

PNG and embedded-image SVG sheets show the actual winning threshold/morphology sequence, selected soma, tracking template/search/correlation/peak, consensus core and fixed ROI. An HTML index links each card's original parameters, parents, coordinate frame, source hashes and purpose. Missing/failed records are explicitly unavailable, never fake masks. Source images and masks remain unchanged.

Same-crop viewing proposals call existing `propose_lut_bbox`: `visible` means pixel>low; `within_range` means low<pixel<=high. The paired table measures area reduction and loss of frozen core/ROI support. Smaller views are not accuracy improvements; neither proposal changes measurement geometry. The example200..2000ADU range explores above-background viewing and deliberately tests bright-signal exclusion; it is not an optimized setting or calibration. Recorded raw LUTs, normalized0..1, Boolean, categorical and correlation displays remain distinct.

Area140/180/220 and radius40/60/80 tables reuse saved actual masks/surfaces. Per-case gained, lost and neutral flags remain visible; newly passing diagnostic flags never replace primary failures. Larger search scores, changed peaks, proximity to another stored anchor and smaller components do not establish identity accuracy without independent labels.

Outputs include `figure_manifest.json`, `index.html`, PNG/SVG sheets, `figure_index.csv`, three measured comparison CSVs, `case_summary.json`, `WHAT_WHY_RESULTS.md` and `IMPLEMENTED_EXECUTED_VALIDATED.csv`. Detailed arrays, source paths, images and private measured tables stay outside Git. Private schema publication is blocked by the auditor.

Genuine detector-coordinate IC fields, acquisition geometry, original-to-atlas mapping, human488 identity/ROI review, separate final561 review and all-nine QC remain scientific prerequisites. No accepted export or biological inference is created. Regenerate the source-bound Claire request after source changes; request preparation is not delivery or independent execution.
