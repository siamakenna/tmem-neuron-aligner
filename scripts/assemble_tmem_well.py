#!/usr/bin/env python3
"""Assemble one explicit well/day from reviewed CYX tile coordinates."""
import argparse
import csv
import json
from pathlib import Path

import numpy as np

from tmem_align.audit_v1.commands import context, input_record, read_cyx
from tmem_align.audit_v1.display import LUT, longitudinal_lut
from tmem_align.audit_v1.evidence import Evidence, write_json
from tmem_align.audit_v1.stitching import Tile, assemble_well


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--tiles", type=Path, required=True); p.add_argument("--geometry", type=Path, required=True)
    p.add_argument("--well", required=True); p.add_argument("--day", type=int, required=True)
    p.add_argument("--out", type=Path, required=True); p.add_argument("--max-pixels", type=int, default=40000000)
    args = p.parse_args()
    geometry = json.loads(args.geometry.read_text())
    if geometry["well"] != args.well or geometry["orientation_validated"] is not True:
        raise ValueError("Require reviewed geometry for this well")
    if geometry["channel_order"] != ["405", "561", "488"]:
        raise ValueError("Require explicit 405/561/488 channel order")
    if not geometry.get("geometry_id") or not geometry.get("coordinate_evidence"):
        raise ValueError("Record geometry ID and orientation/calibration evidence")
    pixel = float(geometry["pixel_size_um"])
    if not np.isfinite(pixel) or pixel <= 0: raise ValueError("Invalid pixel size")
    rows = list(csv.DictReader(args.tiles.open()))
    selected = [r for r in rows if r["well"] == args.well and int(r["day"]) == args.day]
    expected = geometry["expected_tile_ids"]
    if len(expected) != len(set(expected)) or sorted(r["tile_id"] for r in selected) != sorted(expected):
        raise ValueError("Missing/duplicate/unexpected tile ID; cannot claim complete well")
    if len(set(r["ic_status"] for r in selected)) != 1:
        raise ValueError("Mixed IC status within well/day")
    if not selected or selected[0]["ic_status"] not in ["not_applied", "applied_with_provenance"]:
        raise ValueError("Declare IC status explicitly")
    tiles, inputs = [], []
    for row in selected:
        path = Path(row["path"])
        if not path.is_absolute(): path = args.tiles.parent / path
        image = read_cyx(path)
        tiles.append(Tile(row["tile_id"], image, int(row["y_px"]), int(row["x_px"])))
        inputs.append(input_record(path))
        if row["ic_status"] == "applied_with_provenance":
            sidecar = Path(row["ic_provenance"])
            if not sidecar.is_absolute(): sidecar = args.tiles.parent / sidecar
            inputs.append(input_record(sidecar))
    stitched, coverage, seams = assemble_well(tiles, geometry["canvas_yx"], max_pixels=args.max_pixels)
    provenance = context(f"{args.well} Day {args.day} assembly", "REAL INPUT: geometry review required",
                         well=args.well, day=args.day, fov="all listed tiles", inputs=inputs,
                         geometry=geometry, tile_rows=selected, parameters=vars(args),
                         ic_status=selected[0]["ic_status"])
    e = Evidence(args.out, provenance)
    for c, label in enumerate(["405", "561", "488"]):
        lut = longitudinal_lut(stitched[c], source="well/day QC only; not longitudinal comparison")
        e.stage(f"stitched_{label}", stitched[c], lut, channel=label)
    e.stage("coverage", coverage, LUT(0, max(1, int(coverage.max()))), channel="coverage")
    gaps = int((coverage == 0).sum())
    e.finish(dict(gap_pixels=gaps, seam_metrics=seams, geometry_id=geometry["geometry_id"],
                  overlap_method="arithmetic mean, float32 output", registration_ready=gaps == 0))
    import tifffile
    tifffile.imwrite(args.out / "well_cyx.ome.tif", stitched, photometric="minisblack",
                     metadata={"axes": "CYX", "PhysicalSizeX": pixel, "PhysicalSizeY": pixel,
                               "PhysicalSizeXUnit": "µm", "PhysicalSizeYUnit": "µm"})
    tifffile.imwrite(args.out / "coverage_yx.tif", coverage)
    write_json(args.out / "geometry.json", geometry)
    if gaps: raise SystemExit("Assembly has missing support; saved for QC, blocked for registration")
    print(args.out / "well_cyx.ome.tif")


if __name__ == "__main__":
    main()
