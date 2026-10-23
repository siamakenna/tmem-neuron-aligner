#!/usr/bin/env python3
"""Generate verified analysis figures, or an explicitly synthetic demonstration."""

import argparse
from pathlib import Path

from tmem_align.audit_v1.analysis_example import create_example
from tmem_align.audit_v1.matched_analysis import analyze
from tmem_align.audit_v1.scientific_figures import generate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--synthetic", action="store_true")
    mode.add_argument("--analysis", type=Path)
    parser.add_argument("--out", required=True, type=Path, help="New output directory")
    args = parser.parse_args()
    try:
        if args.synthetic:
            args.out.mkdir(parents=True, exist_ok=False)
            manifest = create_example(args.out / "synthetic_inputs")
            analyze(manifest, args.out / "analysis")
            generate(args.out / "analysis", args.out / "figures", image_examples=True)
        else:
            generate(args.analysis, args.out)
    except (ValueError, KeyError, OSError) as error:
        parser.exit(2, f"BLOCKED: {error}\n")
    print(f"Figures written to {args.out}; Figure 6 awaits confirmed fate/censoring evidence.")


if __name__ == "__main__":
    main()
