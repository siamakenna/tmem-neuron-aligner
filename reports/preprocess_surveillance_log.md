# Preprocess (Illumination Correction) Surveillance Log

## Session Metadata

| Field | Value |
|-------|-------|
| Date started | 2026-07-06 |
| Date completed | 2026-07-06 |
| Branch | `preprocess` |
| Base branch | `csp-dev` |
| Base commit | `0e545f7` (Consolidate registration QC functions into library module (#1)) |
| Reference impl | BrieFlow v1.5.0 `workflow/lib/shared/illumination_correction.py` |
| Target file | `src/tmem_align/preprocess.py` |
| Status | **COMPLETED** |

## Decision Log

| # | Decision | Choice | Rationale | Status |
|---|----------|--------|-----------|--------|
| 1 | Source reference | BrieFlow v1.5.0 `illumination_correction.py` | Proven CellProfiler-style IC, already validated in production | Accepted |
| 2 | Architecture | Single file `src/tmem_align/preprocess.py` | Ponytail: fewest files. All IC logic in one module | Accepted |
| 3 | IC approach | Median-filter-of-averaged-images, division-based correction | CellProfiler standard. Supports per-well (default) and per-plate grouping | Accepted |
| 4 | Pipeline order | ND2 -> stitch -> preprocess(IC) -> register -> ROI -> quantify | IC must run on stitched images before registration aligns them | Accepted |
| 5 | Dependencies | scikit-image, numpy, scipy (existing only) | No new packages. Ponytail: already-installed deps | Accepted |
| 6 | Testing strategy | Unit tests (synthetic data) first, then integration with edge cases | Fast feedback loop, no dependency on real data for CI | Accepted |
| 7 | Demo | Jupyter notebook, before/after with actual ND2 data | Visual validation from `/Users/pmihack/claire/tmem_2026/data/` | Accepted |
| 8 | Multi-channel IC strategy | Per-channel recursion in `calculate_ic_field()` | CYX images get independent 2D IC field per channel (C,Y,X output). Each fluorescence channel has a different illumination profile | Accepted |
| 9 | ND2 support | Lazy `import nd2` in `io.py` `read_image()` | Optional dep already in pyproject.toml. IC can work directly on raw ND2 files without pre-conversion | Accepted |
| 10 | Ship readiness | All 90 tests pass, proceed to commit and PR | Full test coverage verified, no regressions, real data validated | Accepted |

## Architecture Decisions

### AD-1: Single-file module over multi-file package
IC correction is a self-contained transform: compute illumination function from a group of images, then divide each image by it. No need for a package directory. One file, importable functions.

### AD-2: Per-well default grouping
Per-well grouping uses images from the same well across all tiles to compute the illumination function. This matches the typical experimental setup where illumination varies by well position. Per-plate option available for cases with uniform illumination across the plate.

### AD-3: Division-based correction over subtraction
Division preserves relative intensity relationships between features. Subtraction can introduce negative values and distort signal ratios. Division is the CellProfiler standard.

### AD-4: Preprocessing before registration
Registration alignment (translation/rotation) should operate on corrected images so that intensity-based matching is not biased by illumination gradients. IC is a per-image operation with no spatial alignment dependency.

### AD-5: Per-channel IC recursion
For multi-channel (CYX) images, `calculate_ic_field()` recurses per channel, computing an independent 2D IC field for each. Returns a (C,Y,X) IC field. Biological rationale: each fluorescence channel (e.g. DAPI, GFP, mCherry) has a distinct illumination profile due to different excitation/emission optics.

### AD-6: ND2 lazy import
ND2 reading added to `io.py` via lazy `import nd2` inside `read_image()`. The `nd2` package is already listed in pyproject.toml as an optional dependency. This avoids import-time failures when nd2 is not installed (not needed for non-ND2 workflows).

## Risk Register

| # | Risk | Likelihood | Impact | Mitigation | Status |
|---|------|-----------|--------|------------|--------|
| R1 | Median filter too slow on large stitched images | Medium | Medium | Use scipy.ndimage.median_filter with reasonable kernel; profile if needed | Open (not yet profiled at scale) |
| R2 | Division by zero in illumination function | Low | High | Clip illumination function minimum, add epsilon | Mitigated (implemented in code) |
| R3 | Per-well grouping has too few images for reliable IC | Low | Medium | Warn if < 3 images; fall back to per-plate | Mitigated (single-image IC tested) |
| R4 | IC changes break downstream registration | Low | High | Run full pipeline test with known-good data | Open (integration test covers IC only, not full pipeline) |
| R5 | Memory pressure from loading all well images at once | Medium | Medium | Process images incrementally (running average) | Open (sample_fraction available as mitigation) |
| R6 | 1x1 pixel images raise ValueError | Very Low | Low | Documented as expected behavior; minimum viable size is 2x2 | Accepted |

## Output Tracking

### Files Created
| File | Purpose | Lines | Tests | Status |
|------|---------|-------|-------|--------|
| `src/tmem_align/preprocess.py` | IC module (calculate_ic_field, apply_ic_field, subtract_background, preprocess_image, well/plate wrappers) | 291 | - | Complete |
| `notebooks/02_preprocessing_before_after.ipynb` | 7-section demo (data load, IC calc, IC viz, before/after, intensity profiles, BG sub, stats) | - | - | Complete |
| `tests/test_preprocess.py` | Unit tests: _rescale_field(3), _load_image(4), _extract_channel(3), calculate_ic_field(9), apply_ic_field(8), subtract_background(5), preprocess_image(7), well_and_plate(4) | - | 43 | Complete |
| `tests/test_preprocess_integration.py` | Integration: end-to-end pipeline, per-well/plate IC, large images, edge cases (zero/saturated/small/mixed dtype), sample_fraction, BG sub idempotency, channel independence, TIFF I/O | - | 40 | Complete |
| `reports/preprocess_surveillance_log.md` | This file | - | - | Complete |

### Files Modified
| File | Change | Status |
|------|--------|--------|
| `src/tmem_align/io.py` | `read_image()` handles ND2 via lazy import; `find_images()` includes `.nd2` suffix | Complete |

### Pipeline Integration Points
| Integration | File | Status |
|-------------|------|--------|
| Snakemake rule for IC step | TBD | Not started |
| Config schema update | TBD | Not started |

### Test Summary

| Suite | Tests | Pass | Fail | Status |
|-------|-------|------|------|--------|
| Unit (`test_preprocess.py`) | 43 | 43 | 0 | Pass |
| Integration (`test_preprocess_integration.py`) | 40 | 40 | 0 | Pass |
| Existing suite | 7 | 7 | 0 | Pass (no regressions) |
| **Total** | **90** | **90** | **0** | **All pass** |

### Verification Results
| Test | Data | Result |
|------|------|--------|
| Synthetic 2D IC | Generated gradient + noise | Pass |
| Multi-channel CYX IC | Synthetic 3-channel | Pass |
| Real ND2 data loading | 192 wells, 3-channel 2868x2868 | Pass |
| Notebook smoke test | Real ND2 data, IC field range [1.00, 1.49] | Pass |
| End-to-end pipeline | Synthetic with CV% verification | Pass |
| Edge cases (15 scenarios) | Zero, saturated, small, mixed dtype, single image, shape mismatch | Pass |

## Progress Timeline

| Timestamp | Event | Notes |
|-----------|-------|-------|
| 2026-07-06 | Session started | Initial plan established, 7 decisions accepted |
| 2026-07-06 | Task 1 complete | Worktree created on `preprocess` branch from `csp-dev` |
| 2026-07-06 | Task 2 complete | `preprocess.py` implemented (291 lines): calculate_ic_field, apply_ic_field, subtract_background, preprocess_image, well/plate wrappers |
| 2026-07-06 | io.py updated | ND2 support added (lazy import nd2, .nd2 in find_images) |
| 2026-07-06 | Task 3 complete | Demo notebook `02_preprocessing_before_after.ipynb` with 7 sections |
| 2026-07-06 | Decisions 8-9 added | Multi-channel IC strategy (per-channel recursion), ND2 lazy import |
| 2026-07-06 | Task 4 complete | 43 unit tests passing in `tests/test_preprocess.py` |
| 2026-07-06 | Task 5 complete | 40 integration tests passing in `tests/test_preprocess_integration.py` (15 edge case scenarios) |
| 2026-07-06 | Full suite verified | 90/90 tests pass (43 unit + 40 integration + 7 existing). No regressions |
| 2026-07-06 | Notebook smoke test | Real ND2: IC field range [1.00, 1.49], 3-channel 2868x2868 correct |
| 2026-07-06 | Finding: 1x1 minimum | 1x1 pixel images raise ValueError; minimum viable size is 2x2. Documented as expected |
| 2026-07-06 | Decision 10 accepted | All tests pass, proceeding to commit and PR to csp-dev |
| 2026-07-06 | **SESSION COMPLETED** | All 5 tasks done. Ready for commit and PR |
