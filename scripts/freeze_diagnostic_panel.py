#!/usr/bin/env python3
"""Freeze a new nonoverlapping diagnostic selection without reading image stacks."""

import argparse
import csv
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "freeze_runner", ROOT / "scripts/run_portable_benchmark.py"
)
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


def freeze(dataset, prior, version, seed, count, config, out):
    if out.exists():
        raise FileExistsError("Existing policy preserved")
    previous = json.loads(prior.read_text())
    if (
        not version
        or version == previous["version"]
        or not seed
        or seed == previous["seed"]
        or type(count) is not int
        or not 1 <= count <= 10
    ):
        raise ValueError("Declare a new version, new seed and count1..10")
    dataset = dataset.resolve()
    manifest = json.loads((dataset / "dataset_manifest.json").read_text())
    if (
        manifest.get("days") != list(runner.DAYS)
        or manifest.get("channels") != ["405", "561", "488"]
        or set(manifest.get("stacks", {})) != set(runner.WELLS)
    ):
        raise ValueError("Require six wells and original nine visits/channel order")
    files = {"master": manifest["master"], **manifest["stacks"]}
    master = runner.local_file(dataset, manifest["master"]["path"])
    if runner.sha256(master) != manifest["master"]["sha256"]:
        raise ValueError("Master checksum mismatch")
    with master.open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    records = {r["neuron_id"]: r for r in previous["historical_exclusions"]}
    if not runner.FIXED_EXCLUSIONS.issubset(records):
        raise ValueError("Prior manifest omitted required historical exclusions")
    for nid in previous["selected_neuron_ids"]:
        records[nid] = {
            "neuron_id": nid,
            "reason": "Previously selected diagnostic example; not biological exclusion",
            "provenance": "Prior version "
            + previous["version"]
            + " SHA256:"
            + runner.sha256(prior),
        }
    ids, eligible, invalid = runner.select_panel(rows, count, set(records), seed)
    if len(ids) != count * len(runner.WELLS):
        raise ValueError("Insufficient eligible candidates after explicit prior-panel exclusions")
    policy = {
        "schema_version": "tmem.panel_selection.v1",
        "version": version,
        "seed": seed,
        "tracks_per_well": count,
        "days": list(runner.DAYS),
        "wells": list(runner.WELLS),
        "historical_exclusions": list(records.values()),
        "selected_neuron_ids": ids,
        "input_sha256": {k: r["sha256"] for k, r in files.items()},
        "configuration_sha256": runner.sha256(config),
        "tracking_validity_preserved": True,
        "biological_acceptance_granted": False,
        "held_out_claimed": False,
        "algorithm": previous.get("algorithm", "SHA256(seed|ID), per-well rank-first round robin"),
        "eligibility": previous.get(
            "eligibility",
            ["Exactly nine visits, finite anchors; preserve true/false tracking flags"],
        ),
        "prior_manifest_sha256": runner.sha256(prior),
        "eligible_counts": eligible,
        "invalid_record_count": len(invalid),
        "registered_stacks_rehashed": False,
        "stack_integrity_policy": "Reuse separately verified dataset; this selection freezer reads master only",
    }
    with out.open("x") as stream:
        stream.write(json.dumps(policy, indent=2, allow_nan=False) + "\n")
    return policy


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--prior", type=Path, default=runner.DEFAULT_SELECTION)
    parser.add_argument("--version", required=True)
    parser.add_argument("--seed", required=True)
    parser.add_argument("--tracks-per-well", type=int, default=2)
    parser.add_argument("--config", type=Path, default=ROOT / "configs/tmem_stage_diagnostics.json")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = freeze(
            args.dataset,
            args.prior,
            args.version,
            args.seed,
            args.tracks_per_well,
            args.config,
            args.out,
        )
    except (ValueError, KeyError, OSError) as error:
        parser.exit(2, "SELECTION_BLOCKED: " + str(error) + "\n")
    print(
        "Frozen",
        len(result["selected_neuron_ids"]),
        "diagnostic IDs; no images processed; not held out or accepted",
    )
