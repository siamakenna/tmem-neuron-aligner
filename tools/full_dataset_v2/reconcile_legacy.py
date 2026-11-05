#!/usr/bin/env python3
"""Read-only recovery inventory. Progress text never becomes a success receipt."""
import argparse
import csv
from pathlib import Path
import sys

from full_dataset import atomic_json, digest, disjoint


def reconcile(root, out, max_files=10000):
    root = Path(root).expanduser().resolve(strict=True)
    out = Path(out).expanduser().resolve()
    disjoint(root, out)
    if out.exists():
        raise ValueError("Recovery report exists; preserve previous evidence")
    records = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or not path.is_file() or path.suffix not in {".csv", ".json"}:
            continue
        if len(records) >= max_files:
            raise ValueError("Recovery scan exceeds file limit; select the precise old result directory")
        s = path.stat()
        row = {"path_private": str(path), "bytes": s.st_size, "sha256": digest(path),
               "reusable_without_revalidation": False}
        if path.suffix == ".csv" and s.st_size < 64 * 1024**2:
            with path.open(newline="", encoding="utf-8-sig") as stream:
                reader = csv.DictReader(stream)
                seen = set()
                count = 0
                for data in reader:
                    count += 1
                    well = data.get("well")
                    day = data.get("day", data.get("timepoint_day"))
                    site = data.get("site", "UNSPECIFIED")
                    if well and day:
                        seen.add((well, day, site))
                row.update(rows=count, distinct_well_day_site_keys=len(seen), columns=reader.fieldnames)
        records.append(row)
    result = {"scan_root_private": str(root), "existing_artifacts": records,
              "status": "existing files inventoried; not imported as new task successes",
              "no_raw_images_read": True, "source_config_position_provenance_reconciled": False,
              "reuse_policy": "Map exact original/config/code/output hashes to new tasks before importing; no automatic rerun or promotion",
              "legacy_progress_count_is_completion": False}
    atomic_json(out, result)
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    try:
        report = reconcile(args.root, args.out)
        print("Legacy artifacts inspected:", len(report["existing_artifacts"]))
        print("No existing result overwritten and no analysis resubmitted.")
    except Exception as exc:
        print("STOP:", exc, file=sys.stderr)
        raise SystemExit(2)
