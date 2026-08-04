# Alignment Completion Plan — `feat/alignment-method-comparison`

Branch: `feat/alignment-method-comparison` → PR target: `csp-dev`  
Written: 2026-07-21  
Source files: `scripts/run_260213_all_wells_batch.py`, `scripts/run_260213_longitudinal_pilot.py`,
`src/tmem_align/cli.py`, `src/tmem_align/plate_align.py`, `src/tmem_align/registration_qc.py`

---

## Step 1 — Run `--plate-correct` on real full-plate batch, compare vs pure anchored

### What to run

Two sequential invocations with output going to separate directories so you can diff them
side-by-side. Run from the repo root with the `.venv` active.

**Run A — anchored only (no plate correction):**
```bash
source .venv/bin/activate
git checkout feat/alignment-method-comparison

python scripts/run_260213_all_wells_batch.py \
  --data-root /Users/pmihack/claire/tmem_2026/data/260213_Feb16recopy_HYdiff_landingpadlines_survival_384well1 \
  --output reports/260213_all_wells_anchored \
  --days 8 12 16 20 25 29 32 36 39 \
  --channels 488 561 \
  --ref-mode anchored \
  --anchor-corr-thresh 0.10 \
  --min-post-correlation 0.07 \
  --workers 10
```

**Run B — anchored + plate correction:**
```bash
python scripts/run_260213_all_wells_batch.py \
  --data-root /Users/pmihack/claire/tmem_2026/data/260213_Feb16recopy_HYdiff_landingpadlines_survival_384well1 \
  --output reports/260213_all_wells_plate_corrected \
  --days 8 12 16 20 25 29 32 36 39 \
  --channels 488 561 \
  --ref-mode anchored \
  --anchor-corr-thresh 0.10 \
  --min-post-correlation 0.07 \
  --plate-correct \
  --pixel-size-um 0.647676 \
  --workers 10
```

Both runs write `plate_transform.json` (Run B only), `all_wells_registration_qc.csv`,
`all_wells_mcherry_measurements.csv`, `all_wells_failures.csv`, `all_wells_summary_stats.csv`,
and heatmaps under `figures/`.

### Outputs to examine and how to interpret them

**First check: did the plate correction detect the expected event?**
```bash
cat reports/260213_all_wells_plate_corrected/plate_transform.json
```
Expect 1 event at day 32 with a translation of ~(880, 0) px for column 05 wells and ~(530, 0) px
for column 20 wells. If `[]` (empty), the plate pre-pass QC gate filtered everything — re-examine
with `--min-post-correlation 0.05` or inspect which wells self-registered in pass 1.

**Compare QC-pass rates at days 32, 36, 39:**
```bash
python - <<'EOF'
import pandas as pd
a = pd.read_csv("reports/260213_all_wells_anchored/all_wells_registration_qc.csv")
b = pd.read_csv("reports/260213_all_wells_plate_corrected/all_wells_registration_qc.csv")
for label, df in [("anchored", a), ("plate_corrected", b)]:
    late = df[df["timepoint_day"] >= 32]
    print(f"\n{label} — days 32+")
    print(late.groupby("timepoint_day")["qc_pass"].agg(["sum","count"]))
EOF
```

**Compare per-well shifts at day 32 across columns:**
```bash
python - <<'EOF'
import pandas as pd
a = pd.read_csv("reports/260213_all_wells_anchored/all_wells_registration_qc.csv")
b = pd.read_csv("reports/260213_all_wells_plate_corrected/all_wells_registration_qc.csv")
for label, df in [("anchored", a), ("plate_corrected", b)]:
    d32 = df[df["timepoint_day"] == 32][["well","column","estimated_y_shift","estimated_x_shift","post_registration_correlation","qc_pass"]]
    print(f"\n{label} day 32 — col05 wells:")
    print(d32[d32["column"] == "05"].sort_values("well").to_string(index=False))
    print(f"\n{label} day 32 — col20 wells:")
    print(d32[d32["column"] == "20"].sort_values("well").to_string(index=False))
EOF
```

**Compare late-timepoint mCherry measurements:**
```bash
python - <<'EOF'
import pandas as pd
a = pd.read_csv("reports/260213_all_wells_anchored/all_wells_mcherry_measurements.csv")
b = pd.read_csv("reports/260213_all_wells_plate_corrected/all_wells_mcherry_measurements.csv")
for label, df in [("anchored", a), ("plate_corrected", b)]:
    late = df[df["timepoint_day"] >= 32]
    print(f"\n{label} — days 32+ mCherry (mean diffuse_to_punctate_ratio by condition/day):")
    print(late.groupby(["condition","timepoint_day"])["diffuse_to_punctate_ratio"].agg(["mean","count"]).round(3))
EOF
```

### Decision criteria (pass/fail for plate correction)

| Criterion | Target | Fail signal |
|-----------|--------|-------------|
| `plate_transform.json` event count | 1 event at day 32 | 0 events = pre-pass filtered; >1 = spurious |
| Per-well shift scatter at day 32 after correction | residuals < 50 px (1 FOV width ÷ 57) | >200 px residuals = prior wrong sign |
| QC-pass rate improvement at day 32+ | plate_corrected ≥ anchored | regression = prior hurts |
| mCherry ratio difference (anchored vs plate-corrected) at day 32+ | < 10% relative change | large swing = prior changes biology conclusions |

If plate correction is neutral (same QC pass rate, <5% mCherry change) that is also acceptable —
it means anchored alone already handles the plate remount and the plate prior just adds complexity.

---

## Step 2 — Decide the default

After examining the Step 1 comparison, apply this decision tree:

**Option A — flip default to anchored, plate-correct opt-in (recommended if plate correction
improves ≥2 wells at days 32+):**
- `ref_mode` default in `run_260213_all_wells_batch.py` `parse_args()`: change `default="to_first"` to `default="anchored"`
- `--anchor-corr-thresh` default stays `0.10`
- `--plate-correct` stays opt-in (it doubles runtime, requires two passes)
- Update `--ref-mode` help string to label `anchored` as the new default

**Option B — anchored + plate-correct both on by default (if plate correction rescues ≥5 weak
wells that anchored alone leaves failing):**
- Set `default="anchored"` and `default=True` for `plate_correct` in `parse_args()`, but add
  a `--no-plate-correct` flag to allow disabling it:
  ```python
  parser.add_argument("--no-plate-correct", dest="plate_correct", action="store_false")
  parser.set_defaults(plate_correct=True)
  ```

**Option C — keep to_first as default (if anchored regresses any early timepoints vs to_first):**
- Add a `# ponytail: to_first default; flip to anchored once biology re-run validated` comment
- Open a follow-up issue

The file to edit for all options: `scripts/run_260213_all_wells_batch.py`, `parse_args()` at the
`--ref-mode` argument, approximately line 43.

---

## Step 3 — Re-run `reports/260213_all_wells_all_days/` with anchored mode and compare

Once the default decision is made in Step 2, generate the canonical replacement report. Output
to a fresh directory; do not overwrite the old one until the comparison is confirmed good.

**Run (assumes anchored chosen as default, plate-correct opt-in):**
```bash
python scripts/run_260213_all_wells_batch.py \
  --data-root /Users/pmihack/claire/tmem_2026/data/260213_Feb16recopy_HYdiff_landingpadlines_survival_384well1 \
  --output reports/260213_all_wells_anchored_final \
  --days 8 12 16 20 25 29 32 36 39 \
  --channels 488 561 \
  --ref-mode anchored \
  --anchor-corr-thresh 0.10 \
  --min-post-correlation 0.07 \
  --workers 10
```

**Compare late-timepoint biology vs committed `to_first` results:**
```bash
python - <<'EOF'
import pandas as pd
old = pd.read_csv("reports/260213_all_wells_all_days/all_wells_mcherry_measurements.csv")
new = pd.read_csv("reports/260213_all_wells_anchored_final/all_wells_mcherry_measurements.csv")

for label, df in [("to_first (old)", old), ("anchored (new)", new)]:
    print(f"\n{label} — diffuse_to_punctate_ratio by condition/day:")
    print(
        df.groupby(["condition","timepoint_day"])["diffuse_to_punctate_ratio"]
        .agg(["mean","count"]).round(3)
    )
EOF
```

**Decision criteria:**
- Early days (8–29): anchored ratios should be within ±5% of `to_first` (byte-identical before
  the first re-anchor, which only triggers on low post-corr)
- Late days (32–39): expect differences for high-drift wells; document the magnitude
- If any biology conclusion reverses (e.g., TMEM106B effect disappears or direction flips at day
  32+), flag this in the PR description — it means the `to_first` results were unreliable and
  anchored is correcting them

Once the new report is confirmed correct:
```bash
# Replace the canonical report
cp -r reports/260213_all_wells_anchored_final/ reports/260213_all_wells_all_days_anchored/
# Keep the old one for auditing
# Do NOT delete reports/260213_all_wells_all_days/ — it stays as the to_first audit record
```

Commit the new report (CSVs + PNGs) on the branch before opening the PR.

---

## Step 4 — PR `feat/alignment-method-comparison` → `csp-dev`

### Pre-PR checklist
```bash
# from branch feat/alignment-method-comparison
pytest                        # must be 34/34 (or more after any new tests)
ruff check src/ tests/ scripts/
ruff format --check src/ tests/ scripts/
git log --oneline csp-dev..HEAD | head -20   # review commits going into the PR
```

### PR description outline

Title: `Registration overhaul: anchored mode + plate-remount correction`

Body sections:
1. **Problem** — `to_first` breaks at ~day 32: post-corr collapses, shifts explode to 500–1957 px
   for high-drift wells; `register-well` CLI was silently broken (mCherry max-projection path)
2. **Solution A — anchored mode** — re-anchors to the last good frame when post-corr drops below
   thresh 0.10; recovers 100% of late timepoints in 10/10 tested wells, 0 early regressions;
   `ref_mode="anchored"` in `register_stack`, byte-identical default
3. **Solution B — plate-remount correction** — detects the plate remount at day 32 via coherent
   column-clustered jumps, fits one global Kabsch rigid transform, applies per-well priors to ALL
   wells (rescues weak wells that can't self-register); `--plate-correct` batch flag, two-pass
4. **CLI guard** — `register-well` now raises a `ClickException` with an actionable message
5. **Results** — attach `figures/all_wells_registration_qc_pass_fraction.png` from the new report
6. **Tests** — 34 → [N] tests, all pass

```bash
gh pr create \
  --base csp-dev \
  --head feat/alignment-method-comparison \
  --title "Registration overhaul: anchored mode + plate-remount correction" \
  --body "$(cat <<'EOF'
## Summary
- `to_first` registration fails at ~day 32 (post-corr collapse, 500–1957 px drift) — confirmed on 10+ wells
- `ref_mode="anchored"` wired into `register_stack`: re-anchors to last good frame at thresh 0.10, recovers 100% of late timepoints, 0 regressions, byte-identical default
- `plate_align.py` (Kabsch fit): detects plate remount, fits global rigid, supplies priors to all wells including weak ones
- `--plate-correct` batch pre-pass in `run_260213_all_wells_batch.py`
- `register-well` CLI guarded with a `ClickException` (was silently producing garbage)

## Changed files
- `src/tmem_align/register.py` — `mask_percentile` param on `register_translation`
- `src/tmem_align/plate_align.py` — new module (Kabsch, `fit_plate_transform`, `plate_offset_for_well`, `detect_plate_events`)
- `scripts/run_260213_longitudinal_pilot.py` — `register_stack` with `ref_mode` + `plate_offsets`
- `scripts/run_260213_all_wells_batch.py` — `--ref-mode`, `--plate-correct`, `--plate-correct` pre-pass
- `src/tmem_align/cli.py` — `register-well` guard
- `src/tmem_align/registration_qc.py` — `common_overlap_crop` robust mode, `DEFAULT_MIN_POST_CORRELATION`

## Test plan
- [ ] `pytest` → all N tests pass
- [ ] `ruff check src/ tests/ scripts/` clean
- [ ] Inspect `plate_transform.json` in the new batch run — 1 event at day 32
- [ ] Compare day 32+ mCherry ratios: old (`to_first`) vs new (`anchored`) and document delta

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Step 5 — CLI guard on `register-well`

### What to add and where

File: `src/tmem_align/cli.py`  
Function: `register_well_command` (~line 125 on the branch)

The command calls `register_file_to_reference` on stitched OME-TIFFs using a config-specified
channel index. The known failure mode: `io.normalize_to_2d` silently takes `axis=0` max-projection
when the input is multi-channel, so whichever channel is channel 0 in the stitched stack (often
mCherry) drives registration instead of the stable 488 nm channel. This produces axis-locked
garbage shifts.

The guard should do two things:
1. Emit a visible `click.echo` warning that `register-well` uses the config-specified channel
   but has not been validated against the masked `register_stack` path
2. Raise a `ClickException` with an actionable redirect message so no one silently uses it

Minimal diff (edit `src/tmem_align/cli.py` at line ~125):

```python
@main.command("register-well")
@click.argument("config_path")
@click.option("--plate", required=True)
@click.option("--well", required=True)
@click.option("--reference-day", default=None)
def register_well_command(config_path: str, plate: str, well: str, reference_day: str | None) -> None:
    """DEPRECATED — this path is known-broken for multi-channel stitched stacks.

    Use run_260213_all_wells_batch.py with --ref-mode anchored instead.
    See docs/design/alignment_investigation_report.md for root-cause analysis.
    """
    raise click.ClickException(
        "register-well is disabled: it max-projects all channels into registration "
        "(normalize_to_2d axis=0), producing axis-locked garbage shifts (~0.005 post-corr) "
        "on multi-channel stitched stacks. Use scripts/run_260213_all_wells_batch.py "
        "with --ref-mode anchored instead."
    )
```

This is the cleanest guard: it fails loudly, names the root cause, and redirects to the working
path. If the stitched-stack pipeline is ever fixed to pass a single-channel image, remove the
guard and re-validate.

**Test to add** (`tests/test_cli.py` or alongside existing CLI tests):
```python
from click.testing import CliRunner
from tmem_align.cli import main

def test_register_well_command_is_guarded():
    runner = CliRunner()
    result = runner.invoke(main, ["register-well", "dummy.yaml", "--plate", "P", "--well", "E05"])
    assert result.exit_code != 0
    assert "disabled" in result.output or "disabled" in str(result.exception)
```

Run after editing:
```bash
pytest tests/ -k "register_well"
```

---

## Quick reference: file-level edit map

| File | What changes |
|------|-------------|
| `src/tmem_align/cli.py` | `register_well_command` body → replace with `ClickException` guard |
| `scripts/run_260213_all_wells_batch.py` | `parse_args()` `--ref-mode` `default=` → `"anchored"` (if Step 2 goes Option A) |
| `scripts/run_260213_all_wells_batch.py` | `--plate-correct` `default=True` + `--no-plate-correct` (if Option B) |
| `tests/test_cli.py` (new or existing) | 1-test guard for `register-well` |

---

## Completion checklist

- [ ] Step 1: both batch runs complete, `plate_transform.json` inspected
- [ ] Step 2: default decided, `parse_args()` updated if needed
- [ ] Step 3: new `reports/260213_all_wells_anchored_final/` generated, late-timepoint biology documented
- [ ] Step 4: PR open against `csp-dev`
- [ ] Step 5: `register-well` guard committed + 1 test
- [ ] `pytest` green, `ruff` clean after all edits
