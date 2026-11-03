# Metadata-only acquisition inventory

From the source checkout, use an environment with the existing optional `nd2` extra to inspect genuine ND2 headers. No new production dependency is required.

```bash
python scripts/inventory_acquisition_sources.py --root ORIGINAL_ACQUISITION_DIRECTORY --root DERIVED_IMAGE_DIRECTORY --out NEW_PRIVATE_INVENTORY_DIRECTORY
```

The command never reads pixels or hashes image contents. It records missing/unreadable roots, symlink exclusions, bounded-scan truncation, metadata errors, actual header axes/channels, reported calibration and frame-zero stage coordinates. Git/environment/cache directories are excluded. Missing ND2 support is a per-file error. Generic TIFF axis inference is not acquisition-axis proof. Filename hints are explicitly unverified and never authorize source coverage or geometry.

Private outputs are `acquisition_inventory.json` and the 54-row `source_coverage.csv`. The separate `source_coverage_summary.json` is path-free and a candidate for sanitized publication only after audit. Detailed files belong outside Git. Output must be a new directory outside scan roots and the repository; private permissions are applied.

Optional `--declarations PRIVATE_JSON` uses schema `tmem.acquisition_declarations.v1`, with a `sources` list containing exact `path`, `well`, integer `day`, `processing_stage`, `evidence_reference`, and `identity_source`; optional `site_id` and `derived_from` claims are retained. Relative paths resolve beside the declaration file. Declarations are labeled claims, not independent review. Accepted stages are RAW_DETECTOR, CORRECTED, STITCHED, REGISTERED and UNKNOWN. Never commit populated declarations.

No inventory row becomes COMPLETE_AND_VERIFIED. Declared readable raw sources remain MISSING_GEOMETRY; incomplete/unassigned evidence remains DEFERRED. A single scene does not prove complete well coverage, and reported pixel size does not independently validate calibration. Real extraction, stitching, seam/landmark inspection and registration must be verified separately.
