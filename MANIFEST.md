# MANIFEST — tmem-neuron-aligner

**v0.1.0** · Ward Lab · ND2/TIFF → stitch → register → crop ROIs → quantify mCherry

## Package (`src/tmem_align/`, 1394 LOC)

| Module | LOC | Purpose | Key exports |
|---|---|---|---|
| `cli.py` | 245 | Click CLI (`tmem-align`) | `main`, 8 subcommands |
| `config.py` | 72 | YAML config → `ExperimentConfig` dataclass | `load_config`, `load_plate_map`, `load_roi_annotations`, `ensure_dirs`, `validate_config` |
| `nd2_tools.py` | 174 | ND2 metadata, manifest, lazy extraction | `inspect_nd2`, `print_nd2_report`, `build_manifest`, `extract_nd2_selection` |
| `stitch.py` | 67 | Grid tile stitching → OME-TIFF | `stitch_grid`, `stitch_folder_to_ometiff`, `estimate_tile_shift` |
| `register.py` | 52 | Phase cross-correlation alignment | `register_translation`, `apply_shift`, `register_file_to_reference` |
| `roi.py` | 69 | ROI crop + local re-registration | `Roi`, `crop_xy`, `roi_from_table`, `build_roi_timeseries` |
| `quantify.py` | 222 | Puncta vs diffuse (Otsu, morphology) | `quantify_puncta_vs_diffuse`, `quantify_puncta_vs_diffuse_roi`, `quantify_puncta_vs_diffuse_frame` |
| `stage_qc.py` | 167 | ND2 stage-coordinate prefiltering | `read_nd2_stage_coordinates`, `stage_distance_xy_um`, `classify_stage_prefilter`, `build_stage_prefilter_rows` |
| `io.py` | 43 | TIFF read/write, `normalize_to_2d` | `find_images`, `read_image`, `write_ome_tiff`, `normalize_to_2d` |
| `export_zarr.py` | 35 | OME-Zarr multiscale export | `export_ome_zarr` |
| `convert_nd2.py` | 19 | Bulk ND2 → OME-TIFF | `convert_nd2_to_ometiff` |
| `viewer_napari.py` | 20 | Quick napari viewer | `open_in_napari` |
| `analysis/mcherry_metrics.py` | 204 | Higher-level mCherry analysis | `MCherryMetricConfig`, `quantify_mcherry_timeseries`, `quantify_mcherry_frame`, `detect_puncta` |

## CLI subcommands (`tmem-align`)

`inspect-nd2` · `build-manifest` · `extract-nd2` · `validate-config` · `stitch` · `register-well` · `make-roi-stack` · `quantify` · `export-zarr`

## Scripts (`scripts/`, 17 files, ~5700 LOC)

| Script | Purpose |
|---|---|
| `inventory_260213_dataset.py` | Inventory raw ND2 dataset |
| `build_applicable_nd2_manifest.py` | Build filtered ND2 manifest |
| `build_mcherry_stage_prefilter.py` | Stage-coordinate pre-QC |
| `run_260213_longitudinal_pilot.py` | Full longitudinal pilot pipeline |
| `run_260213_all_wells_batch.py` | Batch all wells |
| `run_f05_longitudinal_pilot.py` | F05 well pilot |
| `run_ef05_mcherry_pilot.py` | EF05 mCherry pilot |
| `run_mcherry_roi_pilot.py` | mCherry ROI pilot |
| `compare_ef05_longitudinal.py` | Cross-well longitudinal comparison |
| `plot_mcherry_pilot_analysis.py` | mCherry analysis plots |
| `make_registration_qc_montages.py` | Registration QC montage images |
| `make_mcherry_timeseries_videos.py` | Time-series MP4 videos |
| `create_scrollthrough_video.py` | Scroll-through video generation |
| `create_single_neuron_alignment_examples.py` | Single-neuron alignment demo |
| `create_meeting_presentation.py` | Meeting presentation builder |
| `build_github_pages_dashboard.py` | GitHub Pages QC dashboards |
| `build_overlap_only_audit.py` | Overlap-only dashboard audit |
| `build_mcherry_qc_report.py` | mCherry QC report |
| `export_report_stacks_to_omezarr.py` | Export report stacks |
| `synthetic_alignment_smoketest.py` | Synthetic data smoke test |

## Tests (`tests/`, 4 files, 132 LOC)

`test_quantify.py` · `test_stage_qc.py` · `test_nd2_tools.py` · `test_260213_pilot.py`

## Configs (`configs/`)

`template_experiment.yaml` · `plate_map_template.csv` · `roi_annotations_template.csv` · `manual_alignment_offsets_template.csv`

## Notebooks

`notebooks/01_local_nd2_pilot.ipynb` — local ND2 pilot exploration

## Docs (`docs/`)

- 23 markdown guides (alignment methods, dashboard, execution plans, QC workflows)
- 687 HTML files: GitHub Pages dashboards for per-well and per-ROI QC review
  - `docs/wells/` — 64 well-level dashboards (E/F/I/J/M/N rows, columns 05–20)
  - `docs/rois/{WELL}/` — 5 ROIs × 64 wells = 320 ROI dashboards + 64 well indices
  - `docs/summaries/`, top-level QC summaries, audit pages

## Dependencies

**Core:** numpy, pandas, scipy, scikit-image, tifffile, zarr (<3), ome-zarr, dask, pyyaml, tqdm, matplotlib, imageio, click

**Optional:** `[nd2]` nd2 · `[bioformats]` bioio + bioio-nd2 · `[viewer]` napari · `[dev]` pytest, ruff, jupyterlab, ipykernel
