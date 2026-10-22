#!/usr/bin/env python3
"""Deterministic stage examples and before/after checks on explicit CYX frames."""
import argparse
import json
from pathlib import Path

import numpy as np

from tmem_align.audit_v1.commands import (
    context, dependency_check, emit_stages, input_record, read_cyx,
)
from tmem_align.audit_v1.display import LUT, longitudinal_lut, make_overlay, make_qc_panel
from tmem_align.audit_v1.evidence import Evidence, write_json
from tmem_align.audit_v1.fixtures import illumination_fixture, neuron_fixture
from tmem_align.audit_v1.reference import alignment_steps, phenotype_steps, preprocess_steps
from tmem_align.audit_v1.stitching import Tile, assemble_well


def alignment_evidence(out, ref, mov, provenance):
    _, stages, qc = alignment_steps(ref, mov)
    lut = longitudinal_lut(np.stack([ref[2], mov[2]]), source="reference+moving 488, shared")
    e = emit_stages(out, stages, lut, channel="488", provenance=provenance, diagnostics=qc)
    make_qc_panel([make_overlay(ref[2], mov[2], lut),
                   make_overlay(ref[2], stages["04_aligned_488"], lut)],
                  ["Before: 488 only", "After: 488 only"]).save(e.root / "before_after.png")
    return qc


def synthetic(args):
    out = Path(args.out); out.mkdir(parents=True, exist_ok=False)
    provenance = context("TMEM106B synthetic verification", "SYNTHETIC: not experimental data",
                         seed=0, well="synthetic", day=None, fov=None, neuron_id="synthetic")
    raw, moving, roi = neuron_fixture()
    np.savez_compressed(out / "fixtures.npz", reference_cyx=raw, moving_cyx=moving, roi=roi)
    # Spatial reconstruction has exact expected pixels in all three channels.
    truth = raw[:, :40, :64]
    mosaic, coverage, seams = assemble_well([
        Tile("FOV2", truth[:, :, :40], 0, 0), Tile("FOV10", truth[:, :, 24:], 0, 24)], (40, 64))
    np.testing.assert_array_equal(mosaic, truth)
    e = Evidence(out / "05_stitching", provenance)
    e.stage("00_tile_left_488", truth[2, :, :40], LUT(0, 1600), channel="488")
    e.stage("01_tile_right_488", truth[2, :, 24:], LUT(0, 1600), channel="488")
    e.stage("02_stitched_488", mosaic[2], LUT(0, 1600), channel="488")
    e.stage("03_stitched_561", mosaic[1], LUT(0, 1000), channel="561")
    e.stage("04_coverage", coverage, LUT(0, 2), channel="coverage")
    e.finish(dict(exact_reconstruction=True, seam_metrics=seams))
    if args.core_only:
        write_json(out / "status.json", {"core_fixture": "PASS", "reference_integrations": "NOT RUN"})
        return
    dependency_check()
    raw_ic, flat, dark = illumination_fixture()
    _, stages, qc = preprocess_steps(raw_ic, flatfield=flat, darkfield=dark)
    emit_stages(out / "01_preprocessing", stages, LUT(0, 1800), channel="synthetic",
                provenance=provenance, diagnostics=qc)
    alignment_evidence(out / "02_alignment", raw, moving, provenance)
    (metrics, _, _, _), stages = phenotype_steps(raw[1], roi)
    emit_stages(out / "03_phenotype", stages, LUT(0, 1100, "561"), channel="561",
                provenance=provenance, diagnostics=metrics)
    write_json(out / "status.json", {"core_fixture": "PASS", "reference_integrations": "PASS",
                                     "real_data": "NOT RUN"})


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("dependencies")
    s = sub.add_parser("synthetic"); s.add_argument("--out", required=True)
    s.add_argument("--core-only", action="store_true")
    a = sub.add_parser("alignment"); a.add_argument("--reference", required=True)
    a.add_argument("--moving", required=True); a.add_argument("--out", required=True)
    b = sub.add_parser("preprocess"); b.add_argument("--input", required=True)
    b.add_argument("--flatfield", required=True, help="NPY, independently calibrated per-channel CYX")
    b.add_argument("--darkfield", type=float, default=0)
    b.add_argument("--background-radius", type=int); b.add_argument("--out", required=True)
    for parser in [a, b]:
        parser.add_argument("--well", required=True); parser.add_argument("--day", type=int, required=True)
        parser.add_argument("--fov", required=True)
    args = p.parse_args()
    if args.command == "dependencies":
        print(json.dumps(dependency_check(), indent=2)); return
    if args.command == "synthetic":
        synthetic(args); return
    provenance = context(args.command, "REAL INPUT: audit pending manual review", well=args.well,
                         day=args.day, fov=args.fov, parameters=vars(args))
    if args.command == "alignment":
        provenance["inputs"] = [input_record(args.reference), input_record(args.moving)]
        qc = alignment_evidence(args.out, read_cyx(args.reference), read_cyx(args.moving), provenance)
        if not qc["qc_pass"]: raise SystemExit("Alignment QC failed; inspect saved diagnostics")
    elif args.command == "preprocess":
        array = read_cyx(args.input); flat = np.load(args.flatfield, allow_pickle=False)
        if flat.shape != array.shape:
            raise ValueError("Supply CYX flatfields for all three channels; no implicit broadcasting")
        provenance["inputs"] = [input_record(args.input), input_record(args.flatfield)]
        parent = Path(args.out); parent.mkdir(parents=True, exist_ok=False)
        corrected, _, _ = preprocess_steps(array, flatfield=flat, darkfield=args.darkfield,
                                            background_radius=args.background_radius)
        for c, label in enumerate(["405", "561", "488"]):
            _, stages, qc = preprocess_steps(array[c], flatfield=flat[c], darkfield=args.darkfield,
                                              background_radius=args.background_radius)
            # One joint before/after LUT makes IC changes visible without rescaling them away.
            lut = longitudinal_lut(np.stack([array[c], corrected[c]]),
                                   source="joint before/after IC, fixed for this comparison")
            emit_stages(parent / label, stages, lut, channel=label,
                        provenance=provenance, diagnostics=qc)
        import tifffile
        tifffile.imwrite(parent / "corrected_cyx.ome.tif", corrected, metadata={"axes": "CYX"})


if __name__ == "__main__":
    main()
