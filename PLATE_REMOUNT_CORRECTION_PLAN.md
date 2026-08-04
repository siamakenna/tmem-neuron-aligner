# Plate-wise Remount Correction — Implementation Plan

Estimate **one** global rigid transform (shared translation + small rotation about the plate
center) at the physical-remount timepoint, fit from the confident wells' own registration shifts
pooled against their stage XY positions, then **apply it to every well** — including the weak /
decorrelated wells that cannot self-register. This complements (does not replace) the per-well
anchored/masked mode from `ANCHORED_WIRING_PLAN.md`: apply the plate transform first to remove the
systematic jump, then per-well fine registration handles residual drift.

Branch: `feat/alignment-method-comparison` (worktree `.claude/worktrees/understand-alignment`).
Minimal-diff ethos: reuse the existing masked engine, QC lib, and stage reader; vendor ~60 lines of
already-working rigid math; add **one** small module + a pre-pass hook in the batch driver.

---

## 0. Ground truth verified in this worktree (file:line)

### 0.1 The evidence the fit consumes
`reports/alignment_comparison/real_data/anchored_sweep_thresh0.10.txt` — per-well, per-day shift
table (`day, first_px, first_corr, anch_px, anch_corr, reanchored`). The day-32 remount is
unambiguous and **column-clustered**, the rotation fingerprint:

| well | day-32 net-to-first px | day8→day39 net px |
|---|---|---|
| E05 | 524 | 901 |
| C05 | 536 | 900 |
| D05 | 534 | 892 |
| I05 | 514 | 1580 (to-first) / 883 (anchored) |
| **col-05 cluster** | **~514–536** | **~880–900** |
| M20 | 331/332 | 532/535 |
| N20 | 1831 (to-first) / 323 (anchored) | 528 (anchored) |
| G20 | 350/352 | 532/521 |
| H20 | 351/352 | 531/527 |
| **col-20 cluster** | **~323–352** | **~520–535** |

Within a column the day-32 jump is tight (~±10 px); between columns it differs by ~180 px at
day 32 (~350 px net). A pure translation shifts all wells equally — the column dependence is the
signature of **rotation about the plate center** (displacement grows with distance from the pivot).
Every well jumps at the *same* day (32), coherently: a plate-wide event, not biology. This is
exactly the raw material the global fit pools.

Note the two `anch_px` columns where anchored already rescues (N20 1831→323, I05 1580→883): those
are wells where per-well *anchored* recovers. The plate transform must additionally rescue wells
where even anchored fails (churning / decorrelated) — those are absent from this 12-well sweep and
are the target population (§5).

### 0.2 Stage-coordinate reader (the well-position map) — `src/tmem_align/stage_qc.py`
- `read_nd2_stage_coordinates(path)` **line 11** → dict `{stage_x_um, stage_y_um, stage_z_um,
  stage_coordinate_source}`, metadata-only (no pixels). Tries `frame_metadata` first
  (`stage_coordinates_from_frame_metadata` **line 35**, reads `channel.position.stagePositionUm.x/y/z`
  **lines 43–45**), falls back to unstructured `SLxPictureMetadata` `XPos/YPos/ZPos` **lines 55–57**,
  else `empty_stage_coordinates("unavailable")` **line 64** with `None` values.
- Per-file (= per well per day) XY. A well's plate position = its stage XY at a pre-remount
  reference day. Already exercised on 260213 by `scripts/build_mcherry_stage_prefilter.py`
  (`read_nd2_stage_coordinates` at **line 89**) and `scripts/run_f05_longitudinal_pilot.py`
  (**line 208**), and `tests/test_stage_qc.py` covers the distance/prefilter helpers.
- **NOT yet confirmed populated for 260213**: no `stage_x_um` CSV exists under `reports/` or
  `outputs/` in this worktree. Phase 0 (§ below) is a cheap metadata-only check that XY is present
  and varies per well **before** any pixel work — the entire method depends on real per-well XY.

### 0.3 Per-well aligner + engine + QC (reused verbatim)
- `scripts/run_260213_longitudinal_pilot.py::register_stack` **lines 326–400**: to-first loop, per
  timepoint calls `register_translation(reference, moving, robust_preprocess=False,
  mask_percentile=20.0)` **lines 360–365**, `apply_shift(stack[t], dy, dx)` **line 367**, appends
  `(dy,dx)` to `shifts` **368**, builds one QC dict per timepoint (**341–393**, incl.
  `post_registration_correlation` via `correlation()` **370**), returns
  `common_overlap_crop(stack.shape[-2:], shifts, robust=robust_crop)` **line 399**.
- Engine `src/tmem_align/register.py`: `register_translation` **13–30** (skimage
  `phase_cross_correlation`), `apply_shift(image, dy, dx)` **33–39** (`scipy.ndimage.shift`,
  `order=1`, broadcasts `(0,)*(ndim-2)+(dy,dx)` over leading axes — works on CYX/TCYX).
- QC lib `src/tmem_align/registration_qc.py`: `common_overlap_crop` **39–50**, `correlation`
  **30–36**, `overlap_fraction` **21–27**, `classify_registration_qc` **58–76**.
- Plate-scale driver `scripts/run_260213_all_wells_batch.py`: `_process_one_well` **69–134**
  (calls `register_stack` **85–91**, wraps in try/except and records `error` **122–134**), `main`
  **137–214** (ProcessPoolExecutor fan-out **162–181**), `select_all_well_files` **217–234**
  (groups `*.nd2` by well+day, keeps wells with all requested days), `infer_well` **476–480**
  (`Well([C-N]\d{2})`). Plate grid already hard-coded for heatmaps: rows `"CDEFGHIJKLMN"`,
  columns `05..20` (**lines 325–326**). **This driver is where the pre-pass lives** — it is the
  only place that sees all wells at once.

### 0.4 CRITICAL PRECONDITION — masked baseline not yet landed in `src/` on this branch
The scripts call an API the `src/` modules in **this worktree** do not yet expose:
- `register_translation(..., mask_percentile=20.0)` — but `register.py` signature (**13–19**) has
  **no** `mask_percentile` (`grep`: zero hits in `src/`).
- `common_overlap_crop(..., robust=robust_crop)` — but `registration_qc.py` (**39–50**) has **no**
  `robust` param.
- `classify_registration_qc(..., post_correlation=...)` — but the src version (**58–76**) has **no**
  `post_correlation`/`min_post_correlation` and there is no `DEFAULT_MIN_POST_CORRELATION`.

So `register_stack` / the Phase-1 scripts would `TypeError` if run against this worktree's `src/`.
This is the same "branch behind" precondition as `ANCHORED_WIRING_PLAN.md` §0.1 (the masked
baseline lives on `feat/cell-segmentation-exploration`, repo HEAD `771dbd4`). **Land the masked
baseline first** (rebase/merge or port the ~15-line diff). The plate fit consumes the *masked*
per-well shifts, so it shares this precondition with the anchored work — do not duplicate the fix,
just depend on it. (`ANCHORED_WIRING_PLAN.md`'s cited line numbers describe the post-merge state;
the numbers above are this worktree's actual current state.)

### 0.5 Config reality (from ANCHORED plan §0.2, re-verified)
`configs/template_experiment.yaml` has a `registration:` block (**line 64**, `well_registration`
**66**, `roi_registration` **70**) and `stitching.use_stage_positions: true` (**58**). But
`config.py` is a thin dict wrapper and the batch/pilot scripts are **argparse-driven and never load
the YAML** for registration. So "config exposure" = **argparse flags** + commented doc keys in the
YAML. No config-loading machinery — YAGNI.

### 0.6 Known-working rigid math to vendor — `/Users/pmihack/claire/tmem_2026/align-channels-petrucelli/msrigid/__init__.py`
Separate repo, **not** a dependency of tmem-neuron-aligner. Pure numpy + `scipy.ndimage` (imports
verified **lines 20–24**; scikit-image only a warp fallback). Reuse, don't re-derive:
- `rigid_from_points_ls(moving_pts, fixed_pts)` **line 271** — Kabsch/SVD least-squares rigid fit
  (R, t), no scaling, needs ≥3 points, reflection-guarded (`det(R)<0` fix **288–290**). **This is
  the core plate fit.** Convention: **`fixed = R*moving + t`** (`to_jsonable` **line 89**), (x,y)
  with x→right, y→down (ImageJ).
- `RigidTransformTurbo` **line 41** — transform dataclass; `.theta_deg` **68**, `.as_matrix3x3()`
  **52**, `.to_jsonable()` **82** (JSON audit record).
- `rms_error(rt, moving_pts, fixed_pts)` **line 320** — residual; drives RANSAC/robust rejection
  and fit-quality reporting.
- `apply_transform(image, rt, order=1)` **line 346** — warp last-2-axes (Y,X) via
  `scipy.ndimage.affine_transform`; optional per-FOV path (§4).
- `compose_transforms` **304**, `invert_transform` **313** — for composing plate + per-well and for
  sign handling.

**Vendor decision (preferred): copy** `rigid_from_points_ls`, a minimal `RigidTransformTurbo`
(only `m00..m12`, `theta_rad/deg`, `as_matrix3x3`, `to_jsonable`), `rms_error`, and (only if the
per-FOV warp path is needed, §4) `apply_transform` + `_ndimage_matrix_and_offset` into a new
`src/tmem_align/plate_align.py` (~60–90 lines). Keeps tmem self-contained, no cross-repo import,
no new dependency (numpy + scipy.ndimage already present). Cite the source path + line at the top of
the vendored functions. **Do not** import from the other repo (fragile path, not installable).

---

## The fit math

Each well `i` images a fixed stage location `p_i = (x_i, y_i)` (its plate XY, in **pixels** — see
unit note). At the remount the *sample* underwent one global rigid transform `G = (R(θ), t)` about
the plate center. The per-well image shift `s_i = (dx_i, dy_i)` that `register_stack` measured to
realign the post-remount frame back to pre-remount is a **point sample of that global displacement
field** at `p_i`:

```
displacement(p) = t + (R(θ) - I) · (p - c)            # c = plate center (mean of well positions)
s_i ≈ displacement(p_i)                                # measured per confident well
```

That is a 3-parameter model (`t_x, t_y, θ`) sampled at ~100+ wells → hugely over-determined.

**Fit via `rigid_from_points_ls`** (Kabsch), which returns exactly `(R, t)` under
`fixed = R·moving + t`. Feed correspondences built from position + measured shift:

```
fixed_pts[i]  = p_i                     # where the feature should be (pre-remount, stage frame)
moving_pts[i] = p_i + s_i               # where that feature is post-remount (empirical sign; §validation)
```

Recover `G`; read `θ = rt.theta_deg`, `|t|`, and `rms_error(rt, moving, fixed)`. The sign of `s_i`
relative to `apply_shift`'s convention is fixed **empirically** by the leave-one-out check (§5) —
if applying the fit *increases* residual, flip `moving/fixed` (equivalently `invert_transform`).

**Unit note:** `p_i` from stage_qc is in microns; `s_i` from register is in pixels. Convert stage
µm→px with the pixel size `px_um` (from ND2 `nd2.ND2File.voxel_size()` / metadata; add a
`--pixel-size-um` override flag as a calibration knob since real optics drift). Fit entirely in
pixels so `(R-I)·(p-c)` and `s_i` share units. (Alternative if `voxel_size` is unreliable: use the
column/row grid indices scaled by the measured well pitch — positions need only be **affine in
physical space**, which grid indices are; document which was used.)

**Rigid vs affine:** start **rigid** (R orthonormal, no scale/shear) — matches the physical cause.
After the fit, inspect `rms_error`. If residuals are structured (systematic, not random) and large
(> a few px), the remount had scale/shear/non-rigid focus tilt → escalate to affine (least-squares
`A, t` via `np.linalg.lstsq` on `[p_i|1] → p_i + s_i`). Do **not** start affine: 6 params invite
overfitting the noise. Rigid first, test residuals, escalate only on evidence.

**Robust fit (outlier rejection):** confident wells still include some whose shift is biology or a
mis-lock. Use RANSAC-lite over `rigid_from_points_ls` + `rms_error`:
1. Sample 3+ wells, fit, score all wells by per-well residual `|s_i − displacement(p_i)|`.
2. Inliers = residual < `median + k·MAD` (k≈3, robust, no distribution assumption).
3. Keep the fit with the most inliers; refit on all inliers.
Weight the final refit by post-corr (higher post-corr = more trustworthy shift) — a diagonal
weighted Kabsch, or simply restrict to `post_corr ≥ gate` (simplest, lazy; the over-determination
makes weighting a second-order refinement). Huber weights are the escalation if plain
inlier-restriction leaves visible structure.

---

## Phase 0 — Cheap metadata-only prerequisites (no pixels, no registration)

**0a. Confirm stage XY exists and varies per well** (the method's load-bearing assumption). Reuse
`read_nd2_stage_coordinates` over ~one day's ND2 files for a spread of wells/columns; assert
`stage_x_um`/`stage_y_um` are non-`None` and `stage_coordinate_source != "unavailable"`, and that
XY spans the plate (distinct per well, monotone with column/row). This is the same call
`build_mcherry_stage_prefilter.py` already makes — a ~20-line throwaway script or a REPL check, no
new module. **Go/no-go gate:** if XY is unavailable or constant, the fit is impossible → fall back
to per-well anchored only, stop here.

**0b. Get pixel size** `px_um` from `nd2.ND2File.voxel_size()` on one file; record it; expose
`--pixel-size-um` override.

**0c. Confirm the masked baseline is landed** (§0.4) — `register_stack` runs without `TypeError`.

---

## Phase 1 — Detect the plate event(s)

Goal: find the timepoint(s) where a large fraction of wells jump coherently (plate-wide) vs
per-well biology/drift. Handle possibly **>1** remount across days 8–39.

Input: the per-well net-shift-by-day already produced by the batch run / the Phase-1 anchored sweep
(`register_stack` QC rows carry `estimated_y_shift`, `estimated_x_shift`,
`post_registration_correlation` per day per well).

Detection (per candidate day `d`, computed on the *day-to-day* increment `Δs_i(d) = s_i(d) −
s_i(d−1)`, so accumulated drift doesn't mask the jump):
1. **Coherence:** fraction of wells whose `|Δs_i(d)|` exceeds a plate-jump threshold (e.g. > 150 px
   — well above normal day-to-day drift ~40–130 px seen in the sweep, below the 300–530 px remount).
2. **Column-structure test:** regress `Δs_i(d)` on `(p_i − c)`; a plate event yields a strong linear
   fit (high R², the rotation-about-center signature). Biology/mis-lock is scattered, low R².
3. A day is a **plate event** iff coherent fraction ≥ `min_event_fraction` (e.g. 0.5) **and** the
   linear fit R² ≥ `min_event_r2` (e.g. 0.7). This distinguishes a real remount from many wells
   coincidentally drifting.

Multiple events: run the test over all days independently; each qualifying day gets its own global
fit (§ below), applied at that day and carried forward (net composition, `compose_transforms`).
Days 8–39 sampled at the batch `--days` cadence; the sweep shows a single event at day 32, but the
detector must not assume exactly one.

Output: list of `(event_day, n_coherent_wells, fit_r2)`; log it. If zero events detected, the
plate transform is a no-op and the pipeline reduces to per-well registration (safe default).

---

## Phase 2 — Fit the global transform (per event)

Vendored `plate_align.py`. For each detected `event_day`:
1. Build `p_i` (pixels) from stage XY (reference/pre-event day) for **all** wells; `c = mean(p_i)`.
2. Candidate wells = **confident**: `post_registration_correlation(event_day) ≥ qc_gate` (from
   ANCHORED Phase 1, ≈0.07–0.10) **and** `|Δs_i| < plate_jump_max` (drop absurd mis-locks).
3. Correspondences from confident wells → RANSAC-lite `rigid_from_points_ls` + `rms_error` (§fit).
4. Record `PlateEvent{day, theta_deg, tx, ty, center, n_inliers, n_confident, rms_px, transform}`
   via `RigidTransformTurbo.to_jsonable()` → a `plate_transform.json` audit file.
5. **Acceptance:** proceed to apply only if `rms_px` < a few px on inliers and `n_inliers` ≥ ~30
   (over-determination sanity). Else log and skip application for that event (fall back to per-well).

---

## Phase 3 — Application + rescue

For **every** well `i` at each accepted `event_day` (confident AND weak alike):
- **Primary (minimal-diff, preferred):** evaluate the global field at the well center to get a
  per-well translation `ŝ_i = displacement(p_i) = t + (R−I)(p_i − c)`, then apply it with the
  existing `apply_shift(stack[t], dy, dx)` (`register.py` **33–39**) — the *same* call
  `register_stack` already makes at line 367. Weak wells inherit `ŝ_i` from the plate fit; they
  never needed to self-register. This adds a plate-shift to the per-well shift the well would
  otherwise (fail to) compute.
- **Optional per-FOV warp (escalation only):** if the intra-FOV rotation is non-negligible — check
  `θ_rad · FOV_px` (2868) against ~1 px; a rotation big enough to matter across a 2868 px FOV — use
  vendored `apply_transform(stack[t], rt)` per FOV instead of a pure translation. Expected small
  (θ tiny), so default to the translation path; the check gates the upgrade.

**Composition / order with the anchored/masked step** (the key integration):
1. **Plate transform first.** At `event_day` and all later days, apply `ŝ_i` (or the composed
   net over multiple events via `compose_transforms`) to remove the systematic remount jump.
2. **Per-well residual second.** Run the existing masked/anchored `register_stack` on the
   plate-corrected stack; it now sees only the *residual* per-well drift (small), which it handles
   well — and for weak wells the residual after plate correction is small enough to register or to
   pass QC even if it can't.

Concretely, the pre-pass computes `ŝ_i` and either (a) pre-shifts frames before `register_stack`,
or (b) passes `ŝ_i` as a per-well, per-day **prior/offset** that `register_stack` composes into its
net shift before `apply_shift` and before `common_overlap_crop`. Option (b) is cleaner (one warp,
not two) and keeps `common_overlap_crop` (**registration_qc 39–50**) fed the *total* net shift so
the crop geometry stays correct. Thread `plate_offsets: dict[day→(dy,dx)] | None = None` into
`register_stack` (default `None` = today's behavior, regression-safe).

---

## Phase 4 — Where it lives (minimal diff)

- **New module `src/tmem_align/plate_align.py`** (~120–160 lines total): vendored rigid math (§0.6)
  + `detect_plate_events(shift_table) -> list[PlateEvent-candidates]` (§1) + `fit_plate_transform(
  positions, shifts, post_corr, ...) -> PlateEvent` (§2) + `plate_offset_for_well(event, p_i) ->
  (dy,dx)` (§3). Pure functions over numpy arrays / dicts — testable without ND2.
- **Hook in the batch driver** `scripts/run_260213_all_wells_batch.py::main` (**137–214**): a
  pre-pass *after* file selection (`select_all_well_files` **217–234**), *before* the per-well fan-out
  (**162–195**). The pre-pass: reads stage XY per well (`read_nd2_stage_coordinates`), runs the
  cheap per-well shift estimate at the candidate days (or reuses a first quick pass), detects events,
  fits, writes `plate_transform.json`, and passes `plate_offsets[well]` into `_process_one_well`
  (**69–134**) → `register_stack` (**85–91**). The pilot driver stays untouched (it's 2 wells; a
  plate fit needs many).
- **`register_stack`** gains one kwarg `plate_offsets=None` (default preserves behavior). This
  composes with the ANCHORED plan's `ref_mode` kwarg — orthogonal params, no conflict; plate offset
  is applied first, `ref_mode` governs the residual per-well step.
- **CLI/config:** argparse flags on the batch driver (`--plate-correction {off,on}` default `off`,
  `--plate-jump-px`, `--min-event-fraction`, `--min-event-r2`, `--pixel-size-um`,
  `--plate-fit-post-corr-gate`); commented doc keys under `registration:` in
  `configs/template_experiment.yaml` (no config-loading code, per §0.5). Default `off` = fully
  regression-safe.

---

## Phase 5 — Validation & success criteria

**5a. Leave-one-out (LOO) on confident wells.** For each confident well `j`: fit the plate
transform excluding `j`, predict `ŝ_j`, compare to `j`'s own measured `s_j`. Report residual
distribution. **Success:** median LOO residual < ~5 px and 90th-percentile < ~15 px — proves the
pooled 3-param fit predicts a held-out well's shift as well as the well found it itself. This also
fixes the sign convention (if residuals are ~`2·|s_j|`, the sign is flipped → `invert_transform`).

**5b. Rescue test (the headline claim).** Identify wells that **failed** per-well registration at
the event (post-corr < gate after anchored, or flagged by `register_stack` QC / landed in
`all_wells_failures.csv`). Apply the plate transform (fit from the *other*, confident wells), then
re-register the residual. **Success:** ≥ 80% of previously-failed wells reach post-corr ≥ gate
after plate correction + residual registration, and their day8→last net drift stops exploding
(no 1500–1840 px garbage; compare to the sweep's to-first failures like N20 1787→ and I05 1580→).

**5c. No harm to good wells.** On wells that already passed per-well: plate-corrected post-corr is
within −0.01 of their per-well post-corr (mirrors ANCHORED §1.4 criterion 2). Plate correction must
not degrade wells that were fine.

**5d. Physical plausibility.** Fitted `θ` is small and consistent across events/columns; `|t|` and
`θ` reproduce the observed column clustering (predict col-05 ≈ col-20 + the measured ~180 px
day-32 offset). If the fit can't reproduce §0.1's cluster gap, something is wrong.

Report a short table: `event_day, n_confident, n_inliers, theta_deg, |t|_px, rms_px,
LOO_median_px, n_rescued/n_failed`.

---

## Phase 6 — Test plan (synthetic, fast, no ND2)

`tests/test_plate_align.py`. Framework already configured (ruff line-length 100, pytest
`-p no:napari`). One runnable check per non-trivial function.

1. **Fit recovery (unit).** Generate N=120 well positions on a grid; apply a **known** rigid plate
   transform (θ=0.4°, t=(30,−20) px about center) to produce `s_i = displacement(p_i)`; add
   Gaussian noise (σ=2 px). Assert `fit_plate_transform` recovers θ within ~0.02° and t within
   ~1 px, `rms_px` ≈ noise σ.
2. **Outlier rejection (unit).** Inject 15 wells with random garbage shifts (biology/mis-lock).
   Assert RANSAC-lite excludes them (they're not inliers) and the recovered θ/t match the clean fit.
3. **Weak-well rescue (unit/integration).** Mark ~20 wells "too weak to self-register" (their `s_i`
   withheld / post-corr below gate). Fit from the confident wells only; predict `ŝ` for the weak
   wells; assert prediction matches the ground-truth transform's displacement at those positions
   within ~2 px — i.e. a well that can't self-register is correctly rescued by the plate fit.
4. **Event detection (unit).** Build a synthetic per-well shift table: normal drift on most days,
   one day where all wells jump coherently with column structure. Assert `detect_plate_events`
   flags exactly that day (high fraction + high R²) and not the drift days; add a second injected
   event, assert both found.
5. **No-event / no-op (regression).** A shift table with only per-well drift (no coherent jump) →
   `detect_plate_events` returns empty → `plate_offsets=None` path → `register_stack` output
   identical (allclose) to today's. Safety net for the default-off behavior.
6. **Sign convention (unit).** Assert applying `plate_offset_for_well` to a synthetically
   remounted stack *reduces* the shift back toward zero (guards the fixed/moving sign).

Run: `pytest tests/test_plate_align.py -q` and `ruff check scripts/ src/ tests/`.

---

## Risks & mitigations

- **Stage XY unavailable/constant for 260213.** Kills the method. Mitigation: Phase 0a metadata-only
  gate *before* any pixel work; fall back to per-well anchored if it fails.
- **Stage-coordinate units / pixel-size accuracy.** µm→px conversion is load-bearing for mixing
  positions and shifts. Mitigation: read `voxel_size` from ND2, expose `--pixel-size-um` calibration
  override (real optics drift a few %); LOO residual (§5a) catches a wrong scale (structured, not
  random, residual). Grid-index positions are a scale-free fallback.
- **Non-rigid remount (focus/z tilt, scale, shear).** A pure rigid fit leaves structured residuals.
  Mitigation: start rigid, inspect `rms_error`; escalate to affine (`np.linalg.lstsq`) only on
  evidence of structured residual. `stage_z_um` is available (§0.2) as a z-tilt diagnostic.
- **Multiple / mis-detected events.** A biology-heavy day masquerading as coherent. Mitigation: the
  column-structure R² test (§1.2) plus the per-event acceptance gate (§2.5) — a real remount has
  strong linear position structure; scattered biology does not.
- **Intra-FOV rotation ignored by the translation path.** Mitigation: the `θ·FOV_px` check (§3)
  gates the per-FOV `apply_transform` upgrade; expected negligible (θ tiny), but checked not assumed.
- **Interaction with `common_overlap_crop`.** Feed it the **net** (plate + residual) shift so the
  crop geometry stays correct (§3 option b); `robust=True` (masked baseline) already clips the one
  large event hop at p90 so good days aren't over-cropped.
- **Integer-pixel masked shifts** (masked engine returns `error=nan`, integer px). The plate fit is
  continuous (subpixel θ/t); applying via `apply_shift` (`order=1` interp) or `apply_transform`
  gives subpixel correction — an improvement over the per-well integer path, not a limit. Document
  in the QC note.
- **Cross-repo drift of vendored math.** Mitigation: copy (not import) with a source-path+line
  citation comment; `msrigid` is stable pure-numpy math (Kabsch), unlikely to change.

## Minimal-diff summary

- Precondition: land the masked baseline in `src/` (shared with ANCHORED §0.1) — not new work here.
- +1 module `src/tmem_align/plate_align.py`: ~60–90 lines vendored rigid math (cite align-channels-
  petrucelli `msrigid`) + `detect_plate_events` + `fit_plate_transform` + `plate_offset_for_well`.
- +1 pre-pass block in `run_260213_all_wells_batch.py::main`; +1 kwarg `plate_offsets=None` in
  `register_stack` (regression-safe default), composes with ANCHORED's `ref_mode`.
- +6 argparse flags on the batch driver (default `--plate-correction off`); commented YAML doc keys.
- +6 synthetic tests incl. a no-event regression proving the default path is byte-identical.
- No new dependency (numpy + scipy.ndimage present), no config-loading machinery, pilot driver
  untouched, default behavior unchanged.
