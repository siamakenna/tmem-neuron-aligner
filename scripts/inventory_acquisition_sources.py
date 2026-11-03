#!/usr/bin/env python3
"""Inventory explicit local ND2/TIFF headers privately; never certify whole-well assembly."""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from tmem_align.audit_v1.acquisition_inventory import aggregate, run


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, action="append", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--declarations", type=Path)
    parser.add_argument("--max-files", type=int, default=10000)
    args = parser.parse_args(argv)
    try:
        report = run(args.root, args.out, declarations=args.declarations, max_files=args.max_files)
    except (ValueError, TypeError, KeyError, OSError) as error:
        parser.exit(2, "INVENTORY_BLOCKED: " + str(error) + "\n")
    import json

    print(json.dumps(aggregate(report), indent=2))
    return 0 if report["scan_complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
