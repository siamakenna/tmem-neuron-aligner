#!/usr/bin/env python3
"""Describe evidence-accepted neurons within six wells and three matched pairs."""

import argparse

from tmem_align.audit_v1.matched_analysis import analyze


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--inputs", required=True, help="Versioned input manifest; see analysis README"
    )
    parser.add_argument("--out", required=True, help="New output directory")
    args = parser.parse_args()
    try:
        _, _, warnings = analyze(args.inputs, args.out)
    except (ValueError, KeyError, OSError) as error:
        parser.exit(2, f"BLOCKED: {error}\n")
    print(f"Descriptive tables written; {len(warnings)} warnings. Biological unit: well/pair.")


if __name__ == "__main__":
    main()
