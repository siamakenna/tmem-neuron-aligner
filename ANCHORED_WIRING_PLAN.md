# Anchored Registration — Validation + Wiring Plan

Wire the calibrated **anchored/masked** temporal registration mode into the canonical batch
aligner (`register_stack`), after confirming on real data that it recovers the late timepoints
that the current "register everything to day 0" (to-first) mode drops.

Minimal-diff ethos: the anchored logic **already exists and is validated** in
`scripts/plot_day_shift_overlay.py::register_anchored` and
`scripts/compare_alignment_methods.py::run_method(ref_mode="anchored")`. We reuse that logic
verbatim; we do not rebuild an aligner. Default behavior stays `to_first` so nothing changes
unless a caller opts in.

---

## 0. Ground truth verified in this worktree (file:line)

Branch: `feat/alignment-method-comparison` (worktree `.claude/worktrees/understand-alignment`).

- **Canonical aligner:** `scripts/run_260213_longitudinal_pilot.py::register_stack`
  (**lines 277–332**). Signature (line 277):
  ```python
  def register_stack(stack, *, well, rows, alignment_channel_index,
                     alignment_channel_label) -> (registered_stack, qc_rows, common_crop)
  ```
  Loop at **305–329** registers every `time_index` to `reference = stack[0]` (to-first),
  builds one `qc_rows` dict per timepoint, appends `(dy,dx)` to `shifts`, and returns
  `common_overlap_crop(stack.shape[-2:], shifts)` (**line 332**).
- **Two callers, both keyword-only:**
  - `run_260213_longitudinal_pilot.py::_process_one_well_pilot` **lines 69–74**.
  - `run_260213_all_wells_batch.py::_process_one_well` **lines 85–91**.
- **Engine:** `src/tmem_align/register.py::register_translation` **lines 13–52**. Masked variant
  = `robust_preprocess=False, mask_percentile=20.0` → integer-pixel, `error=nan` (**35–45**).
- **QC lib:** `src/tmem_align/registration_qc.py`.
  `classify_registration_qc` **82–110** (has an optional `post_correlation` /
  `min_post_correlation` gate, default `DEFAULT_MIN_POST_CORRELATION=0.02` at **line 12**);
  `common_overlap_crop` **43–74** (`robust=` clips shift outliers at p90); `correlation`
  **34–40**; `overlap_fraction` **25–31**.
- **Reference anchored implementation (reuse this):**
  `scripts/plot_day_shift_overlay.py::register_anchored` **lines 56–80**. It:
  - starts `anchor = stable[0]`, `anchor_net = (0,0)`, `last_good = stable[0]`;
  - registers `mov` to the current anchor with the masked engine (`_masked`, **36–41**);
  - if `post_corr < thresh` **and** `t >= 2`, re-anchors to the **last good** frame
    (never the current one), re-registers;
  - composes `net = anchor_net + pairwise_shift` and applies `apply_shift(mov, *net)`;
  - only frames with `post >= thresh` become eligible future anchors.
  Same logic, with an added fixed-stride option, in
  `scripts/compare_alignment_methods.py::run_method` **lines 260–274**.

### 0.1 PREREQUISITE — this branch's `register_stack` is behind main (must fix first)

In **this worktree**, `register_stack` (277–332) still uses the **old broken preprocessing**:
`robust_registration_image` clip+blur on both frames (**285, 306**), `register_translation(...
robust_preprocess=False)` **without** `mask_percentile`, **no** `robust_crop`, and **no**
`post_correlation` gate in the `classify_registration_qc` call (**326**).

The masked/robust-crop/post-corr-gate version described as canonical already lives on the
`feat/cell-segmentation-exploration` branch (repo HEAD, commit `771dbd4`): masked engine
(`mask_percentile=20.0`), `robust_crop` param, and `post_correlation=post_corr` in the QC call.

**Step 0 of Phase 2 is to land that masked baseline here** (rebase/merge, or port the ~15-line
diff) *before* adding anchored. Anchored is defined only for the masked engine — the comparison
scripts already prove unmasked decorrelates. Do not build anchored on top of the clip+blur path.

### 0.2 Config reality check

`src/tmem_align/config.py` is a thin dict wrapper (`ExperimentConfig.raw`, `.resolve()`); the
pilot/batch scripts are **argparse-driven and never load the YAML** for registration. So "config
wiring" = **argparse flags** on the two scripts, plus documenting the knobs in the
`registration:` block of `configs/template_experiment.yaml` (**currently lines ~ "registration:"
→ well_registration**). Do **not** invent a config-loading path for these scripts — YAGNI.

---

## Phase 1 — Confirm anchored on more wells

**Goal:** decide, quantitatively, whether anchored is safe to wire in. No source changes; runs
the existing scripts on real data at
`/Users/pmihack/claire/tmem_2026/data/260213_Feb16recopy_HYdiff_landingpadlines_survival_384well1`.

### 1.1 Well sample (12 wells)

Span both conditions and a range of drift severity. Use the 05 column already exercised plus a
second, well-separated column (e.g. 20) so we're not overfitting one stage neighborhood:

| Purpose | Wells |
|---|---|
| mCherry reporter control (E/I/M) | `E05`, `I05`, `M20` |
| mCherry primary (F/J/N) | `F05`, `J05`, `N20` |
| no-mCherry morphology-only (C/D/G/H) | `C05`, `D05`, `G20`, `H20` |
| known-hard drift (from prior finding) | `F05` (day~32 break), plus `E05` |

That is ~10–12 distinct wells across 6 rows and 2 columns, mixing all four condition classes.
The no-mCherry wells matter: registration uses 488 only, so C/D/G/H are valid registration test
subjects even though they're invalid for mCherry biology — they check anchored on the stable
channel independent of phenotype.

Run the **full month** (`--max-timepoints 10`) so the day~32 decorrelation is actually reached;
the default of 6 stops before the break.

### 1.2 Commands (existing scripts, no code changes)

```bash
source .venv/bin/activate
DATA=/Users/pmihack/claire/tmem_2026/data/260213_Feb16recopy_HYdiff_landingpadlines_survival_384well1

# (a) Per-well anchored vs to-first, full month. Prints the per-day table
#     (day, first_px, first_corr, anch_px, anch_corr, reanchored) and net drift, and writes
#     day-overlay PNGs. This is the primary Phase-1 evidence.
for THRESH in 0.07 0.10 0.12; do
  python scripts/plot_day_shift_overlay.py \
    --data-root "$DATA" \
    --wells E05 F05 I05 J05 M20 N20 C05 D05 G20 H20 \
    --max-timepoints 10 \
    --anchor-corr-thresh $THRESH \
    | tee reports/alignment_comparison/real_data/anchored_sweep_thresh${THRESH}.txt
done

# (b) To-first baseline + A/B montages + the real post-corr distribution used to set the QC gate.
python scripts/validate_alignment_real.py \
  --data-root "$DATA" \
  --wells C05 E05 F05 I05 J05 M20 N20 \
  --max-timepoints 10
```

### 1.3 Metrics (already emitted by 1.2a per day, per well)

- `first_corr`, `anch_corr` — post-registration Pearson to the reference (to-first vs anchored).
- `first_px`, `anch_px` — net shift magnitude vs day 0 (garbage = 500–1840 px).
- `reanchored` (YES/blank) → **re-anchor count** per well.
- **#timepoints recovered** = count of late timepoints where `first_corr < gate` but
  `anch_corr >= gate`.
- Net drift day0→last (printed): anchored should track real cumulative drift, not explode.

Tabulate per well: `n_timepoints`, `n_late_tofirst_fail`, `n_recovered_by_anchored`,
`n_reanchors`, `min_early_corr_tofirst`, `min_early_corr_anchored`.

### 1.4 Acceptance criteria (go/no-go for Phase 2)

Anchored is **safe to wire in** iff, across the sample:

1. **Recovery:** on timepoints where to-first fails (`first_corr < 0.07`), anchored reaches
   `anch_corr >= 0.10` on **≥ 80%** of them, in **≥ 5 of 6** wells that exhibit a late break.
2. **No early regression:** on early timepoints where to-first already passes
   (`first_corr >= 0.10`), anchored's `anch_corr` is within **−0.01** of to-first (i.e. no
   meaningful loss on days that were already fine). Equivalently: anchored never turns a passing
   early day into a failing one.
3. **Drift sanity:** anchored net drift day0→last is monotone-ish and **< 100 px** on wells
   whose raw stage drift is modest; it must **not** produce the 500–1840 px explosions to-first
   shows at the break.
4. **Bounded churn:** median re-anchor count **≤ 2** per 10-timepoint well. A well needing a
   re-anchor almost every frame means the field decorrelated beyond rescue — that's a QC-fail
   well (Phase 2 §2.6), not a reason to reject the mode.

If (1) or (3) fails broadly → do **not** wire; revisit threshold or the mode itself.
If only isolated wells fail → wire it, and let QC flag those wells.

### 1.5 Picking the final re-anchor threshold

From the 3-threshold sweep (1.2a) and the post-corr distribution (1.2b):

- Real "good" post-corr ≈ 0.15; garbage ≈ 0.005 (established). The threshold must sit in the
  valley between them, biased low enough to fire *before* a day collapses to garbage.
- Choose the **largest** threshold in `{0.07, 0.10, 0.12}` that satisfies §1.4 on the most wells
  without triggering spurious early re-anchors (criterion 2 + 4). Prior single-well work put this
  at **0.10–0.12**; confirm on the wider sample. Record the chosen value as
  `DEFAULT_ANCHOR_CORR_THRESH` for Phase 2 (expected **0.10**).
- Separately, the QC **gate** (`min_post_correlation`) should rise from the library default
  `0.02` to **~0.07** for this assay — the value below which a day is untrustworthy even if it
  didn't trigger a re-anchor. Read it off the 1.2b distribution (the point separating the "good"
  cluster from the degrading tail). The re-anchor threshold and the QC gate are related but
  distinct: re-anchor threshold triggers a *retry*; the QC gate decides *pass/fail after* the
  retry.

Deliverable of Phase 1: a short results table + the chosen `(anchor_corr_thresh, qc gate)` pair.

---

## Phase 2 — Wire anchored/masked mode into `register_stack`

Precondition: §0.1 masked baseline is present in this branch.

### 2.1 Signature change (minimal, backward-compatible)

`scripts/run_260213_longitudinal_pilot.py::register_stack` (line 277) gains three keyword args
with defaults that preserve today's behavior byte-for-byte:

```python
def register_stack(
    stack, *, well, rows, alignment_channel_index, alignment_channel_label,
    robust_crop: bool = True,                 # from masked baseline (§0.1)
    ref_mode: str = "to_first",               # "to_first" | "anchored"
    anchor_corr_thresh: float = 0.10,         # from Phase 1
    min_post_correlation: float = 0.07,       # QC gate, from Phase 1 (was lib default 0.02)
) -> tuple[np.ndarray, list[dict[str, Any]], dict[str, int]]:
```

`ref_mode="to_first"` keeps the existing loop untouched → **regression-safe default**.

### 2.2 Anchored branch — reuse `register_anchored` logic

Factor the anchor bookkeeping so both scripts share one implementation. Two lazy options,
pick the higher rung that holds:

- **Preferred:** import `register_anchored` from `scripts/plot_day_shift_overlay.py` is awkward
  (it returns 2D `reg` frames on the stable channel only, not TCYX). Instead, **lift the ~20-line
  anchor loop into a small helper** next to `register_stack` that returns just the per-timepoint
  **net shifts + post-corr + reanchored flags** (no image application):

  ```python
  def _anchored_shifts(stable_frames, thresh):  # stable_frames = stack[:, alignment_channel_index]
      """Net (dy,dx)-to-t0, post-corr, reanchored per timepoint. Mirrors
      plot_day_shift_overlay.register_anchored (never anchors on a failed frame; carries
      last-good net forward; composes across hops)."""
      # ... exact body of register_anchored 56-80, minus building reg[] images ...
      return shifts, post, reanchored
  ```
  Then `register_stack` applies each net shift to **all channels** via
  `apply_shift(stack[t], dy, dx)` — same call it already makes at line 311 — and writes the
  returned `post`/`reanchored` into the QC rows. This keeps the anchor math in exactly one place
  and lets both the diagnostic script and the aligner stay consistent.

- Feed `common_overlap_crop(stack.shape[-2:], shifts, robust=robust_crop)` the **net anchored
  shifts** (line 332), unchanged otherwise — the robust p90 clip already handles the one large
  jump at a re-anchor hop.

`to_first` branch = the current loop verbatim.

### 2.3 QC rows

Per timepoint, in addition to today's fields:

- `post_registration_correlation` = anchored `post` (to the anchor it actually used).
- new `reanchored: bool` and `anchor_ref_day` (the day of the frame used as anchor) — cheap and
  makes QC auditable.
- `qc_note = "anchored_masked_phase_cross_correlation"` when `ref_mode="anchored"`.
- Pass `post_correlation=post, min_post_correlation=min_post_correlation` into
  `classify_registration_qc` (**line 326 call**) — this is the calibrated gate from Phase 1.

### 2.4 Common-overlap crop interaction

No change to `common_overlap_crop`. It already accepts arbitrary shifts and (with `robust=True`)
clips outliers at p90, so a single large re-anchor hop won't shrink the crop for the good days.
Just ensure the **net** shifts (not per-anchor pairwise) are passed — they represent
displacement back to t0, which is what the crop geometry needs.

### 2.5 Config + CLI/pilot exposure

- **argparse** on **both** scripts (`run_260213_longitudinal_pilot.py::parse_args` ~line 44 and
  `run_260213_all_wells_batch.py::parse_args` line 50):
  ```
  --ref-mode {to_first,anchored}   default: to_first
  --anchor-corr-thresh FLOAT       default: 0.10
  --min-post-correlation FLOAT     default: 0.07
  ```
  Thread them through the worker tuples (`well_args`, `_process_one_well_pilot` line 62 /
  `_process_one_well` line 69) into the `register_stack` call (**pilot 69–74, batch 85–91**).
- **YAML doc only:** add commented keys under `registration:` in
  `configs/template_experiment.yaml` (`well_registration.ref_mode`, `anchor_corr_thresh`,
  `min_post_correlation`) so the knobs are discoverable. Note in a comment that the batch/pilot
  scripts read these from CLI, not the YAML (until/unless the CLI path is unified). No
  config-loading code added.

### 2.6 QC flag for wells where anchored still fails (churning anchors)

Anchored can still fail if the field decorrelates past rescue. Add a **per-well** QC verdict
(computed after the loop, written to the QC frame / a small per-well summary):

- `n_reanchors` = sum of `reanchored`.
- `anchor_churn` = `n_reanchors / (n_timepoints - 1)`.
- Flag `well_registration_qc_pass = False` when **either** `anchor_churn > 0.5` (re-anchoring
  more than every other frame) **or** any timepoint still has
  `post_registration_correlation < min_post_correlation` **after** its re-anchor retry. Surface
  this in the existing `summary_stats` / all-wells QC CSV so churning wells are visible without
  reading every row.

### 2.7 Test plan (`tests/test_register.py` or `tests/test_260213_pilot.py`)

Framework already configured (`pyproject.toml`: ruff line-length 100, pytest `-p no:napari`).
Keep tests synthetic and fast — no ND2, no real data.

1. **Anchored composition (unit).** Build a small `stable` list of 2D frames with a known
   cumulative drift and a mid-series decorrelation (reuse the `blob` + `_drift_shifts` pattern
   from `compare_alignment_methods.py`). Assert `_anchored_shifts` returns net shifts that
   recover the applied drift within a couple px on the recoverable frames, and that
   `reanchored[t]` is True exactly at the injected break.
2. **Never anchors on a failed frame (unit).** Inject one garbage frame; assert the anchor used
   for the *next* frame is the last **good** frame's net, not the garbage frame's (check via the
   composed net matching last-good + pairwise, not garbage + pairwise).
3. **Re-anchor trigger (unit).** With `anchor_corr_thresh` set just above a frame's true
   post-corr, assert that frame flips `reanchored=True`; set it just below, assert `False`.
4. **Regression: `to_first` unchanged (golden).** Run `register_stack` on a fixed synthetic
   TCYX stack with `ref_mode="to_first"` and assert the returned `shifts`/`registered`/`crop`
   are identical (allclose) to the pre-change behavior — i.e. adding the params changed nothing
   on the default path. This is the safety net for backward compatibility.
5. **QC gate (unit).** One timepoint with post-corr between 0.02 and 0.07: assert it passes under
   the old lib default but fails under `min_post_correlation=0.07`.

Run: `pytest tests/test_register.py -q` and `ruff check scripts/ src/ tests/`.

---

## Risks & mitigations

- **Branch behind main (§0.1).** Highest risk: building anchored on the clip+blur `register_stack`
  would inherit the axis-lock garbage. Mitigation: land the masked baseline first; the anchored
  helper calls the masked engine explicitly.
- **Threshold overfit to column 05.** Mitigation: Phase 1 sample spans a second column (20) and
  all four condition classes; accept only if criteria hold across ≥5/6 breaking wells.
- **Re-anchor on a marginally-good frame** propagates a slightly-off anchor. Mitigation: the
  "eligible anchor only if `post >= thresh`" rule (already in `register_anchored`) plus the
  churn QC flag (§2.6) surface it rather than hide it.
- **Two copies of the anchor loop** (helper vs `plot_day_shift_overlay`). Mitigation: the helper
  is the single source; the diagnostic script can import it later if desired (not required now).
- **Integer-pixel masked shifts** (engine returns `error=nan`). Expected and fine for this assay;
  `registration_error` stays `nan` in anchored rows — document in the QC note.

## Minimal-diff summary

- +1 masked-baseline merge (§0.1, pre-existing code from main).
- +1 helper `_anchored_shifts` (~20 lines, lifted from `register_anchored`).
- `register_stack`: +3 kwargs, +1 `if ref_mode == "anchored"` branch, QC rows gain 2 fields.
- +3 argparse flags × 2 scripts, threaded through worker tuples.
- YAML: commented doc keys only.
- +5 synthetic tests, incl. one golden regression proving `to_first` is untouched.

No new modules, no new dependencies, no config-loading machinery, default behavior unchanged.
