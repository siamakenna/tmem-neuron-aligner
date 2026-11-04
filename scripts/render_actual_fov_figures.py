#!/usr/bin/env python3
"""Render actual saved segmentation/tracking evidence; no measurement adoption."""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from tmem_align.audit_v1.actual_fov_figures import run


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("traces", "dataset", "out"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--render-case", action="append", required=True, dest="render_cases")
    parser.add_argument("--days", type=int, nargs="+")
    parser.add_argument("--lut-low", type=float)
    parser.add_argument("--lut-high", type=float)
    args = parser.parse_args(argv)
    try:
        result = run(
            args.traces,
            args.dataset,
            args.out,
            render_cases=args.render_cases,
            days=args.days,
            lut_low=args.lut_low,
            lut_high=args.lut_high,
        )
    except (ValueError, KeyError, TypeError, OSError) as error:
        parser.exit(2, "ACTUAL_FOV_FIGURES_BLOCKED: " + str(error) + "\n")
    print("Source-bound cases:", len(result["sources"]))
    print("Figure manifest:", args.out / "figure_manifest.json")
    print("Accepted tracks:0; geometry changes:0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
