#!/usr/bin/env python3
"""Export small synthetic challenge inputs and declared truth for independent review."""
from __future__ import annotations

import argparse
import hashlib
import html
import json
from pathlib import Path

import numpy as np

from tmem_align.audit_v1.display import LUT, apply_lut_for_display, make_qc_panel
from tmem_align.audit_v1.stress_fixtures import CASE_IDS, DEFAULT_SEED, stress_fixture


def generate(out: Path, *, seed: int = DEFAULT_SEED) -> dict:
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    records = []
    for case_id in CASE_IDS:
        fixture = stress_fixture(case_id, seed=seed)
        folder = out / case_id
        folder.mkdir()
        arrays = {k: v for k, v in fixture.items() if isinstance(v, np.ndarray)}
        original_hashes = {k: hashlib.sha256(v.tobytes()).hexdigest() for k, v in arrays.items()}
        np.savez_compressed(folder / "fixture.npz", **arrays)
        for name in ("parameters", "expected_result"):
            (folder / f"{name}.json").write_text(
                json.dumps(fixture[name], indent=2, allow_nan=False) + "\n")
        cyx, reference = arrays["cyx"], arrays["reference_cyx"]
        identity_high = 60 if case_id == "low_488_nonblank" else 1000
        phenotype_high = 2600 if case_id in {"puncta_rich", "exposure_change"} else 200
        identity_lut = LUT(0, identity_high, "488", scope="fixed-within-synthetic-case",
                           source="explicit synthetic challenge display range")
        phenotype_lut = LUT(0, phenotype_high, "561", scope="fixed-synthetic-before-after-pair",
                            source="explicit range shared by reference and challenged 561")
        identity = apply_lut_for_display(cyx[2], identity_lut)
        marked = identity.copy()
        # Synthetic truth is visibly distinct from a computed detector overlay.
        marked[arrays["labels"] > 0] = [0, 160, 255]
        roi = arrays["phenotype_roi"]
        padded = np.pad(roi, 1)
        interior = (padded[:-2, 1:-1] & padded[2:, 1:-1]
                    & padded[1:-1, :-2] & padded[1:-1, 2:])
        marked[roi & ~interior] = [255, 255, 255]
        make_qc_panel([
            identity, marked, apply_lut_for_display(reference[1], phenotype_lut),
            apply_lut_for_display(cyx[1], phenotype_lut),
        ], [f"488 (0..{identity_high})", "TRUTH labels + ROI", "561 reference", "561 challenged"],
            cell=192).save(folder / "preview.png")
        if any(hashlib.sha256(v.tobytes()).hexdigest() != original_hashes[k]
               for k, v in arrays.items()):
            raise AssertionError("Display export mutated a synthetic quantitative input")
        records.append({
            "case_id": case_id, "fixture": f"{case_id}/fixture.npz",
            "parameters": f"{case_id}/parameters.json",
            "expected_result": f"{case_id}/expected_result.json",
            "preview": f"{case_id}/preview.png", "array_sha256": original_hashes,
            "display_luts": {"488": identity_lut.metadata(), "561": phenotype_lut.metadata()},
            "manual_review": "NOT_PERFORMED",
        })
    result = {"schema_version": "tmem.synthetic_stress.v1", "seed": seed,
              "evidence_type": "SYNTHETIC_NOT_EXPERIMENTAL", "cases": records,
              "scientific_validation": "PENDING_INDEPENDENT_REVIEW"}
    (out / "manifest.json").write_text(json.dumps(result, indent=2) + "\n")
    sections = []
    for row in records:
        name = html.escape(row["case_id"])
        sections.append(f'<section><h2>{name}</h2><img src="{row["preview"]}" '
                        f'alt="Synthetic {name}"><p><a href="{row["parameters"]}">Parameters</a> '
                        f'<a href="{row["expected_result"]}">Declared truth and limitations</a> '
                        f'<a href="{row["fixture"]}">Numeric fixture</a></p></section>')
    page = '''<!doctype html><meta charset="utf-8"><title>TMEM106B synthetic stress examples</title>
<style>body{font:18px system-ui;background:#102127;color:white;padding:30px;max-width:1200px;margin:auto}
img{max-width:100%;image-rendering:pixelated}a{color:#70ead8;margin-right:15px}section{margin:40px 0}</style>
<h1>TMEM106B synthetic stress examples</h1><p>These deterministic images have declared construction truth.
They are not experimental neurons, independent reviewer results, or evidence of validated longitudinal identity.
Blue masks are synthetic soma labels. White outlines show a prescribed truth ROI, not a production segmentation.</p>'''
    (out / "index.html").write_text(page + "".join(sections))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    args = parser.parse_args()
    generate(args.out, seed=args.seed)
    print(f"Saved nine synthetic stress examples to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
