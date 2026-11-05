#!/usr/bin/env python3
"""Convert a normalized authentic microscope site table into a checked map.

Required CSV columns: path,position,site. Paths must refer to the actual ND2
files in this inventory. This never invents site IDs from position indices.
"""
import argparse
import csv
from pathlib import Path

from full_dataset import SCHEMA, atomic_json, disjoint, load
from preview_originals import channel_map


def prepare(inventory, profile, acquisition_csv, reason):
    if not reason.strip():
        raise ValueError("Explain how the acquisition table establishes cross-day site correspondence")
    by_path = {h["path"]: h for h in inventory["headers"]}
    observations = []
    with Path(acquisition_csv).open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        if not {"path", "position", "site"}.issubset(reader.fieldnames or []):
            raise ValueError("Acquisition CSV needs path,position,site columns")
        for row in reader:
            path = str(Path(row["path"]).expanduser().resolve(strict=True))
            if path not in by_path:
                raise ValueError("Acquisition map references a source outside this inventory")
            h = by_path[path]
            if h["modality"] != "fluorescence":
                raise ValueError("Brightfield belongs to a separate modality plan")
            observations.append({"path": path, "position": int(row["position"]), "site": row["site"],
                                 "well": h["well"], "day": h["day"], "time": 0, "z": 0,
                                 "channel_map": channel_map(h, profile),
                                 "evidence": {"path": str(Path(acquisition_csv).resolve()), "reason": reason}})
    if not observations:
        raise ValueError("Empty acquisition site table")
    return {"schema": SCHEMA, "observations": observations}


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for name in ["inventory", "profile", "acquisition-csv", "out"]:
        p.add_argument("--" + name, type=Path, required=True)
    p.add_argument("--reason", required=True)
    args = p.parse_args()
    if args.out.exists():
        p.error("Output exists; preserve it")
    inventory = load(args.inventory)
    disjoint(args.out, inventory["raw_root"])
    result = prepare(inventory, load(args.profile), args.acquisition_csv, args.reason)
    atomic_json(args.out, result)
    print("Mapped source-position rows:", len(result["observations"]))
