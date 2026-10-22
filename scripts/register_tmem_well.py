#!/usr/bin/env python3
"""Run existing anchored registration on explicit whole-well OME-TIFF visits."""
import argparse
import csv
import json
from pathlib import Path

import numpy as np

from tmem_align.audit_v1.commands import context, input_record, read_cyx
from tmem_align.audit_v1.contracts import strict_overlap
from tmem_align.audit_v1.display import longitudinal_lut, make_overlay, make_qc_panel
from tmem_align.audit_v1.evidence import Evidence, write_json


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--visits", type=Path, required=True)
    p.add_argument("--well", required=True); p.add_argument("--out", type=Path, required=True)
    p.add_argument("--days", nargs="+", type=int, default=[8,12,16,20,25,29,32,36,39])
    p.add_argument("--max-input-gib", type=float, default=2)
    args = p.parse_args()
    import pandas as pd
    import tifffile
    from run_260213_longitudinal_pilot import register_stack
    with args.visits.open(newline='') as handle:
        rows = [r for r in csv.DictReader(handle) if r["well"] == args.well]
    rows.sort(key=lambda r: int(r["day"]))
    if [int(r["day"]) for r in rows] != args.days or len(set(args.days)) != len(args.days):
        raise ValueError("Need each requested day exactly once, in chronological order")
    arrays, inputs, geometry = [], [], None
    ic_status = None
    for row in rows:
        folder = Path(row["assembly_directory"])
        if not folder.is_absolute(): folder = args.visits.parent / folder
        current = json.loads((folder / "geometry.json").read_text())
        status = json.loads((folder / "provenance.json").read_text())["ic_status"]
        if geometry is not None and current != geometry:
            raise ValueError("Different well geometry/origin across visits; reconcile before registration")
        if ic_status is not None and status != ic_status:
            raise ValueError("IC status differs across visits")
        geometry, ic_status = current, status
        if geometry["well"] != args.well: raise ValueError("Assembly belongs to another well")
        coverage = tifffile.imread(folder / "coverage_yx.tif")
        if np.any(coverage == 0): raise ValueError("Missing tile support cannot enter registration")
        path = folder / "well_cyx.ome.tif"
        with tifffile.TiffFile(path) as tif:
            estimated = int(np.prod(tif.series[0].shape)) * np.dtype(tif.series[0].dtype).itemsize
        if sum(a.nbytes for a in arrays) + estimated > args.max_input_gib * 1024**3:
            raise ValueError("Input stack exceeds memory guard; use a larger allocated job and explicit limit")
        a = read_cyx(path)
        if a.shape[-2:] != coverage.shape or list(coverage.shape) != geometry["canvas_yx"]:
            raise ValueError("Coverage/geometry/image dimensions disagree")
        if np.std(a[2]) == 0: raise ValueError("Blank 488 visit needs explicit exclusion/review")
        arrays.append(a); inputs.append(input_record(path))
    stack = np.stack(arrays); del arrays
    out = args.out; out.mkdir(parents=True, exist_ok=False)
    registered, qc, legacy_crop = register_stack(
        stack, well=args.well, rows=[{"day": int(r["day"])} for r in rows],
        alignment_channel_index=2, alignment_channel_label="488", robust_crop=False,
        ref_mode="anchored", anchor_corr_thresh=.10, min_post_correlation=.07)
    pd.DataFrame(qc).to_csv(out / "registration_qc.csv", index=False)
    write_json(out / "legacy_crop_for_comparison.json", legacy_crop)
    shifts = [(q["estimated_y_shift"], q["estimated_x_shift"]) for q in qc]
    bounds = strict_overlap(stack.shape[-2:], shifts)
    provenance = context(f"{args.well} whole-well alignment", "REAL INPUT: QC pending",
                         well=args.well, inputs=inputs, geometry=geometry, ic_status=ic_status,
                         parameters=dict(ref_mode="anchored", anchor_corr_thresh=.10,
                                         min_post_correlation=.07, robust_crop=False),
                         common_bounds=vars(bounds))
    write_json(out / "provenance.json", provenance)
    # Use one reference-derived LUT for every visit, sampling only for display limits.
    lut = longitudinal_lut(stack[0, 2, ::4, ::4], source="Day8 488 subsample; fixed across visits")
    for i, row in enumerate(rows):
        e = Evidence(out / f"day_{int(row['day']):02d}", {**provenance, "day": int(row["day"])})
        e.stage("reference_488", stack[0, 2], lut, channel="488")
        e.stage("before_488", stack[i, 2], lut, channel="488")
        e.stage("after_488", registered[i, 2], lut, channel="488")
        make_qc_panel([make_overlay(stack[0, 2], stack[i, 2], lut),
                       make_overlay(stack[0, 2], registered[i, 2], lut)],
                      ["Before: Day8 comparison", "After: Day8 comparison"]).save(e.root / "overlay.png")
        e.finish(qc[i])
    if any(not q["qc_pass"] or not q["well_registration_qc_pass"]
           or not np.isfinite(q["post_registration_correlation"]) for q in qc):
        raise SystemExit("Registration QC failed. Diagnostics saved; no accepted stack exported.")
    common = bounds.crop(registered)
    tifffile.imwrite(out / f"{args.well}_registered_common_overlap_tcyx.ome.tif", common,
                     photometric="minisblack", metadata={"axes": "TCYX",
                     "PhysicalSizeX": geometry["pixel_size_um"], "PhysicalSizeY": geometry["pixel_size_um"],
                     "PhysicalSizeXUnit": "µm", "PhysicalSizeYUnit": "µm"})
    print("Whole-well registration exported. New coordinate system: do not reuse old atlas anchors.")


if __name__ == "__main__":
    main()
