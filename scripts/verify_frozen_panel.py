#!/usr/bin/env python3
"""Reconstruct selection from frozen master only; never rerun images/benchmark."""

import argparse
import csv
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "portable_selection", ROOT / "scripts/run_portable_benchmark.py"
)
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


def verify(dataset, policy):
    metadata = json.loads((dataset / "dataset_manifest.json").read_text())
    files = {"master": metadata["master"], **metadata["stacks"]}
    master = runner.local_file(dataset.resolve(), metadata["master"]["path"])
    if runner.sha256(master) != metadata["master"]["sha256"]:
        raise ValueError("Frozen master checksum mismatch")
    with master.open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    declared = json.loads(policy.read_text())
    _, ids, eligible, invalid = runner.frozen_selection(
        policy, files, rows, count=declared["tracks_per_well"], seed=declared["seed"]
    )
    return {
        "selection_verified": True,
        "version": declared["version"],
        "selected_neuron_ids": ids,
        "eligible_counts": eligible,
        "invalid_record_count": len(invalid),
        "registered_stacks_rehashed": False,
        "microscopy_reprocessed": False,
        "note": "Selection and master verified; original registered-stack verification is reused, not rerun",
        "real_accepted_ids": [],
        "scientific_inference_ready": False,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--selection-manifest", type=Path, default=runner.DEFAULT_SELECTION)
    args = parser.parse_args()
    try:
        print(json.dumps(verify(args.dataset, args.selection_manifest), indent=2))
    except (ValueError, KeyError, OSError) as error:
        parser.exit(2, str(error) + "\n")
