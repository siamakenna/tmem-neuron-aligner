#!/usr/bin/env python3
"""Reconcile private diagnostic/final review evidence; never approve or export metrics."""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from tmem_align.audit_v1.review_reconciliation import run


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("workspace", "benchmark", "gallery", "annotations", "out"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--final-links", type=Path)
    parser.add_argument("--analysis-inputs", type=Path)
    parser.add_argument("--analysis", type=Path)
    args = parser.parse_args(argv)
    try:
        result = run(
            args.workspace,
            args.benchmark,
            args.gallery,
            args.annotations,
            args.out,
            final_links=args.final_links,
            analysis_inputs=args.analysis_inputs,
            analysis=args.analysis,
        )
    except (ValueError, KeyError, OSError, TypeError) as error:
        parser.exit(2, "RECONCILIATION_BLOCKED: " + str(error) + "\n")
    print("Private readiness report:", args.out)
    print("Verified pre-existing exports:", len(result["verified_existing_export_ids"]))
    print("New accepted measurements:0; treatment effects:0; survival analysis:0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
