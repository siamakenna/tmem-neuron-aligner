#!/usr/bin/env python3
"""Prepare an offline human 488 workspace or validate private decisions; never export metrics."""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from tmem_align.audit_v1 import diagnostic_review as review


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "validate"))
    parser.add_argument("--benchmark", type=Path, required=True)
    parser.add_argument("--gallery", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--annotations", type=Path)
    parser.add_argument("--out", type=Path, help="NEW private validation JSON file")
    parser.add_argument("--csv-out", type=Path, help="Optional NEW private normalized CSV file")
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            if args.annotations or args.out or args.csv_out:
                parser.error("prepare does not take annotations/output flags")
            context = review.prepare(args.benchmark, args.gallery, args.workspace)
            print("Prepared blank human-only 488 workspace:", args.workspace / "index.html")
            print("Visits:", len(context["visits"]), "Accepted:0")
            return 0
        if not args.annotations or not args.out:
            parser.error("validate requires --annotations and --out")
        destination = review.output_path(args.out, [args.benchmark, args.gallery])
        if args.csv_out:
            review.output_path(args.csv_out, [args.benchmark, args.gallery])
        try:
            context = review.verify_workspace(args.workspace, args.benchmark, args.gallery)
        except (ValueError, KeyError, OSError) as error:
            # A stale source must never be rebound to old human decisions.
            recorded = review.read_json(args.workspace / "workspace.json")
            result = {
                "status": "EVIDENCE_STALE",
                "error": str(error),
                "real_accepted_ids": [],
                "tracks": [
                    {"neuron_id": c["neuron_id"], "status": "EVIDENCE_STALE", "accepted": False}
                    for c in recorded.get("cases", [])
                ],
                "scientific_inference_ready": False,
            }
            with destination.open("x") as stream:
                stream.write(json.dumps(result, indent=2) + "\n")
            print("EVIDENCE_STALE; no decisions rebound")
            return 2
        annotation_sha = review.sha(args.annotations)
        document = review.load_annotations(args.annotations)
        try:
            result = review.validate(document, context)
        except ValueError as error:
            stale = "EVIDENCE_STALE" in str(error) or "Stale" in str(error)
            result = {
                "status": "EVIDENCE_STALE" if stale else "ANNOTATION_INVALID",
                "error": str(error),
                "real_accepted_ids": [],
                "scientific_inference_ready": False,
                "annotation_file_sha256": review.sha(args.annotations),
                "tracks": [
                    {
                        "neuron_id": c["neuron_id"],
                        "status": "EVIDENCE_STALE" if stale else "REVIEW_PENDING",
                        "accepted": False,
                    }
                    for c in context["cases"]
                ],
            }
            with destination.open("x") as stream:
                stream.write(json.dumps(result, indent=2) + "\n")
            print(result["status"] + "; all tracks blocked; inspect private report")
            return 2
        if review.sha(args.annotations) != annotation_sha:
            raise ValueError("Annotation file changed during validation; no result is bound")
        result["annotation_file_sha256"] = annotation_sha
        result["workspace_sha256"] = context["workspace_sha256"]
        if args.csv_out:
            review.write_csv(args.csv_out, document)
        with destination.open("x") as stream:
            stream.write(json.dumps(result, indent=2, allow_nan=False) + "\n")
        print(
            f"Complete:{result['complete_decisions']}/{result['observations']}; unresolved:{result['unresolved_decisions']}; accepted:0"
        )
        return 0
    except (ValueError, KeyError, OSError, TypeError) as error:
        parser.exit(2, "REVIEW_BLOCKED: " + str(error) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
