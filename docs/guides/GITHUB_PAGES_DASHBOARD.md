# GitHub Pages Dashboard

This repo can publish a lightweight, sanitized TMEM106B dashboard from the `docs/` folder using GitHub Pages.

## What Is Included

The GitHub Pages build includes browser-safe dashboard files:

- `index.html`
- well pages under `wells/`
- ROI pages under `rois/`
- ROI review queue pages
- overlap-only QC summary page
- first-pass summary pages
- optimized preview PNGs under `previews/` and `roi_previews/`
- sanitized summary CSV/JSON/HTML files under `summaries/`
- a site size report

The preview images are resized/optimized copies of the local dashboard previews so the site is practical to browse in GitHub Pages.

## What Is Excluded

The build intentionally excludes:

- raw ND2 files
- OME-TIFF files
- OME-Zarr directories
- MP4/GIF files
- full processed microscopy output folders
- local absolute paths such as `LOCAL_USER_HOME/...`

When a large microscopy output path appears in a local dashboard page, the public build replaces it with a safe label such as:

```text
Large microscopy file stored locally/shared drive
```

Other local roots are replaced with labels such as:

```text
LOCAL_PROCESSED_OUTPUT/
LOCAL_RAW_DATA/
LOCAL_REPO/
LOCAL_USER_HOME/
```

## Rebuild The GitHub Pages Dashboard

From the repo root:

```bash
python scripts/build_github_pages_dashboard.py
```

The default input dashboard is:

```text
LOCAL_PROCESSED_OUTPUT/dashboard
```

The default review summary input is:

```text
LOCAL_PROCESSED_OUTPUT/full_mcherry_valid_defg_pass5/review_summaries
```

The default overlap-only audit input is:

```text
LOCAL_PROCESSED_OUTPUT/full_mcherry_valid_queue_abc/overlap_only_audit
```

The default output is:

```text
docs/
```

The build script:

1. Cleans previously generated dashboard files in `docs/`.
2. Copies only web-safe files.
3. Optimizes preview PNGs.
4. Sanitizes local absolute paths.
5. Copies summary CSV/JSON/HTML files.
6. Copies overlap-only QC summary CSV/JSON files.
7. Writes `docs/site_size_report.txt` and `docs/site_size_report.json`.
8. Reports the largest files and any forbidden file types.

## Update After Manual ROI Review

First edit the working review CSV:

```text
LOCAL_PROCESSED_OUTPUT/full_mcherry_valid_defg_pass5/review_summaries/full_mcherry_valid_pass5_roi_identity_review_working.csv
```

Then rebuild local review summaries:

```bash
python scripts/build_roi_review_workflow.py
```

Then rebuild the GitHub Pages bundle:

```bash
python scripts/build_github_pages_dashboard.py
```

This sequence preserves manual review edits because `build_roi_review_workflow.py` reads the existing working CSV as the source of truth.

## Enable GitHub Pages

After reviewing the generated `docs/` folder and committing it:

1. Open the GitHub repository settings.
2. Go to **Pages**.
3. Set **Source** to **Deploy from a branch**.
4. Select the target branch, usually `main`.
5. Set the folder to `/docs`.
6. Save.

GitHub will provide a Pages URL after the first successful deployment.

## Lab Use

Lab members should start at:

```text
index.html
```

Recommended review pages:

- `roi_review_queue.html`
- `roi_review_priority_wells.html`
- `roi_review_unreviewed.html`
- `roi_review_confirmed_same_neuron.html`
- `roi_review_poor_registration_or_exclude.html`
- `roi_review_saturation_clipping_warnings.html`
- `roi_first_pass_metric_summary.html`
- `overlap_only_qc_summary.html`

All ROI metrics remain preliminary until ROI identity has been manually reviewed.

## Before Committing

Run:

```bash
python scripts/build_github_pages_dashboard.py
du -sh docs
find docs -type f | sort
```

Check:

- `docs/site_size_report.txt`
- no `.nd2`, `.ome.tif`, `.ome.tiff`, `.zarr`, `.mp4`, or `.gif` files
- no remaining absolute local home-directory paths
- largest files are preview PNGs or normal web assets

Do not commit or push until the generated size and file list look acceptable.
