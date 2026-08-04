# Alignment Method Comparison & Test Plan

**Branch:** `worktree-understand-alignment`
**Goal:** Objectively compare the two registration/alignment code paths in this
repo, establish which is more accurate/robust and where each fails, and leave
behind runnable evidence — not opinions.

All file:line references below were verified directly against the code on this
branch (not inferred).

---

## 0. The core finding this plan is built on

There are **two independent registration implementations** that share one engine
(`register.register_translation`, `register.py:13-52`) but drive it with
different settings. They differ on **five axes at once**, which is exactly why a
naïve "A vs B" number would be uninterpretable — we have to ablate the axes.

| Axis | Path A — CLI (`tmem-align`, documented in CLAUDE.md) | Path B — pilot script (produced the `reports/`) |
|---|---|---|
| **Entry point** | `register_file_to_reference` (`register.py:64-78`), called by `cli.py:143-157` | `register_stack` (`run_260213_longitudinal_pilot.py:326-400`) |
| **Reference channel** | `normalize_to_2d` **max-projects across ALL channels** incl. mCherry (`io.py:40-42`) | Explicitly selects a stable channel (488) via `alignment_channel_index`, feeds `stack[t, ch]` — single channel (`:338, :359`) |
| **Preprocessing** | `robust_preprocess=True` → percentile-clip + Gaussian blur σ=1 (`registration_qc.py:15-22`) | `robust_preprocess=False`, `mask_percentile=20` → masked phase-corr on raw signal (`:363-364`) |
| **Subpixel** | Yes — `upsample_factor=10` (`cli.py:154`) | **No** — masked path is integer-pixel, `upsample_factor` ignored, `error=nan` (`register.py:35-45`) |
| **Reference timepoint** | Config `reference_day` (Day01), each day → that day (`cli.py:143-157`) | Timepoint 0, `stack[0]` (`:338`) |
| **Common-overlap crop** | ❌ never called | ✅ `common_overlap_crop(..., robust=True)` (`:399`) |
| **QC written** | ❌ shifts CSV only (`cli.py:160`) | ✅ full QC + correlation gate active (`:383-391`) |
| **ROI/neuron-level** | Fixed-box crop + local reg, `robust_preprocess=False`, **no mask**, no QC (`roi.py:49-64`) | n/a (script is well-level) |

**Decisive claim to test:** the CLI (Path A) can register on mCherry — the exact
thing the design says never to do (`io.py:42` max-projects the phenotype channel
in). Path B avoids it. Everything else is a knob.

---

## 1. Approach: ablate the engine, don't black-box the paths

Because both paths call the same `register_translation`, we get clean isolation
almost for free. Rather than only comparing A-vs-B end to end (which confounds 5
variables), we sweep the engine's knobs **one at a time** on shared fixtures:

| Knob | Settings to sweep |
|---|---|
| Preprocessing | `robust_preprocess=True` (A) vs `mask_percentile=20` (B) vs plain |
| Channel input | max-projection (A) vs single stable channel (B) |
| Subpixel | `upsample_factor` 1 / 10 / 20 |

Each fixture has **known ground-truth shifts**, so accuracy is `|estimated −
true|` — an objective number, no proxy needed. This is the backbone of the
evidence.

Reuse, don't rebuild: `scripts/synthetic_alignment_smoketest.py` already builds a
shifted synthetic stack and reports recovery error. Extend it into the harness
rather than writing a new framework.

---

## 2. Synthetic experiments (ground truth → accuracy numbers)

One harness (`scripts/compare_alignment_methods.py`), each experiment a fixture
generator + the knob sweep. Output: a tidy CSV `method, experiment, true_dy,
true_dx, est_dy, est_dx, abs_err, post_corr, overlap, qc_pass`.

**E1 — Baseline subpixel accuracy.** Dense-ish frame, known subpixel shifts
(e.g. 3.4, 7.7). Expect: A recovers subpixel (<0.25 px, matches
`test_register.py`); B rounds to integer (≈0.3–0.5 px error). *Establishes the
subpixel-vs-robust tradeoff quantitatively.*

**E2 — Sparse neurons (the axis-lock failure).** Few point-like blobs on dark
background, known shift. Expect: A's clip+blur locks onto edges → large
axis-aligned error (reproduces the 500–1400 px garbage in the stale reports);
B's masked path recovers. *This is the reason Path B exists — prove it.*

**E3 — mCherry contamination (the decisive test).** 2-channel stack: stable
channel truly static (shift=0), mCherry channel has a **bright blob that moves**
by a known amount. Feed each method its real input:
- A → `normalize_to_2d` max-projection → should chase the mCherry blob (nonzero est).
- B → stable channel only → should report ≈0.
*Directly tests the "never register on mCherry" rule. If A chases the blob, the
documented CLI is measuring biology as motion.*

**E4 — Illumination gradient / weak reference.** Add a low-freq gradient + faint
signal. Tests which preprocessing survives low-texture days (relevant to the
0.02 correlation-gate calibration question).

**E5 — Multi-timepoint drift + common-overlap crop.** 5–9 timepoints, cumulative
known drift. Run B end-to-end; verify `common_overlap_crop` keeps only the shared
region and measure **area retained** vs drift magnitude. Confirm the "pop-in/out"
edge artifact is gone in the crop and present without it. (A has no crop — show
the zero-padded edges it leaves.)

Each experiment leaves an `assert`-based check so it fails loudly if a method
regresses.

---

## 3. QC calibration (is a "pass" trustworthy?)

The committed `reports/` are **stale** — every CSV has the pre-fix
`qc_note="phase_cross_correlation_on_stable_channel"` and the correlation gate
was never applied (garbage shifts marked `qc_pass=True`). So step one is a clean
baseline, not analysis of the old files.

1. **Regenerate one well** with current code (Path B) and diff `qc_pass` against
   the committed CSV — watch the gate flip the garbage rows to fail. This alone
   proves the fix landed.
2. **Threshold ROC.** Using E2/E3/E4 (we know which are truly aligned), sweep
   `min_post_correlation` and plot separation. Current default 0.02 is justified
   by a comment citing ~0.09 good / ~0.004 garbage (`registration_qc.py:9-11`),
   but real 488 post-corr medians in the reports sit ~0.005 *even for "good"
   rows*. Determine the real operating point — this decides whether the gate, once
   on, flags legitimate wells.
3. **Coverage gap:** add a test for `common_overlap_crop`/`crop_tcyx` (currently
   untested) and one asserting mCherry is excluded from registration (would have
   caught E3).

---

## 4. Real-data head-to-head (no ground truth → proxy + eyeball)

Only after synthetic accuracy is established. Needs ND2 data
(`/Users/pmihack/claire/tmem_2026/data`, `[nd2]` extra).

- Pick 3–4 wells spanning easy → hard (a clean well, a known QC-flagged one).
- Run **both** paths on identical stitched inputs; record shift estimates, QC
  verdicts, and before/after montages side by side.
- Compare on proxy metrics (no ground truth): post-registration correlation,
  overlap fraction, and visual neuron-centering stability across days.
- Explicitly flag any well where A and B **disagree on the shift by > a few px**
  — those are where the channel/preprocessing choice actually changes the science.

Start with `--dry-run` (inventory only, loads no pixels), then a 3-timepoint run
before scaling.

---

## 5. Metrics & acceptance criteria

- **Accuracy:** RMS `|est − true|` shift per method per experiment (synthetic only).
- **Robustness:** failure rate (err > 5 px) across E1–E4.
- **Subpixel cost:** E1 error gap between A and B (quantifies what B trades away).
- **mCherry safety:** E3 estimated shift for A vs B (should be ~blob-motion vs ~0).
- **QC calibration:** correlation threshold that separates aligned/garbage in E2–E4.
- **Crop:** area retained vs drift in E5.

**Success = a one-page table** answering: which method is more accurate (and by
how much), which is more robust, whether A leaks mCherry in practice, and whether
the 0.02 gate is calibrated for this assay.

---

## 6. Deliverables

```
scripts/compare_alignment_methods.py     # harness: fixtures + knob sweep + CSV
tests/test_common_overlap_crop.py        # fills the crop coverage gap
tests/test_no_mcherry_in_registration.py # asserts channel selection excludes mCherry
reports/alignment_comparison/
    synthetic_accuracy.csv               # E1–E5 raw results
    qc_threshold_sweep.csv               # §3.2
    real_data_head_to_head.csv           # §4 (if data available)
    montages/                            # before/after side-by-side
ALIGNMENT_COMPARISON_FINDINGS.md         # the one-page verdict table
```

---

## 7. Execution order

1. Extend the synthetic harness; run E1–E5 → `synthetic_accuracy.csv`. *(no data needed — do first)*
2. Add the two missing tests; run full `pytest`.
3. QC threshold sweep + regenerate one well's report for baseline diff.
4. Real-data head-to-head (only if ND2 data is available this session).
5. Write `ALIGNMENT_COMPARISON_FINDINGS.md`.

Steps 1–3 need no imaging data and produce the bulk of the evidence. Step 4 is
gated on data access.

---

## 8. Open questions for you (Claire)

- **Which path is meant to be canonical?** CLAUDE.md documents the CLI (Path A),
  but every real result came from Path B. The comparison assumes both are
  candidates; if the CLI is being retired, E3/E4 become "confirm before delete"
  rather than "choose."
- **Is the stitched TIFF the CLI reads actually multi-channel?** The mCherry leak
  (E3) only bites if it is. If stitched output is single-channel, A is safe in
  practice and this drops in priority.
- **Real 488 post-corr baseline** — do you have a well you *know* aligned well?
  That anchors the QC threshold calibration (§3.2) better than synthetic alone.
