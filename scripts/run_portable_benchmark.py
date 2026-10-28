#!/usr/bin/env python3
"""Run a bounded six-well diagnostic panel locally, without NIH connectivity.

Selection uses identifiers and the presence of the nine original visits. It
never ranks phenotype values, changes anchors, adopts parameter proposals, or
approves measurements. A complete software run remains pending scientific
review. The panel is not called held out: prior review history is incomplete.
"""
from __future__ import annotations

import argparse
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import csv
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
WELLS = ("E05", "F05", "I05", "J05", "M05", "N05")
DAYS = (8, 12, 16, 20, 25, 29, 32, 36, 39)
ID_RE = re.compile(r"(?:E05|F05|I05|J05|M05|N05)_N\d{3}\b")
FIXED_EXCLUSIONS = {"E05_N006", "F05_N007", "J05_N015", "F05_N025", "N05_N011", "N05_N012"}
DEFAULT_SELECTION = ROOT / "configs" / "panels" / "portable_20261027_v1.json"


def atomic_json(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    os.replace(temporary, path)


def sha256(path):
    before = Path(path).stat()
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    after = Path(path).stat()
    if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
        raise ValueError("Dataset input changed while hashing: " + str(path))
    return digest.hexdigest()


def local_file(root, relative):
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute() or ".." in Path(relative).parts:
        raise ValueError("Dataset paths must be relative without traversal")
    path = root / relative
    current = path
    while current != root:
        if current.is_symlink():
            raise ValueError("Dataset paths cannot contain symbolic links")
        current = current.parent
    if not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("Missing dataset file: " + str(path))
    return path


def load_dataset(root):
    root = Path(root).resolve()
    manifest_path = local_file(root, "dataset_manifest.json")
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("schema_version") != "tmem.portable_dataset.v1":
        raise ValueError("Unsupported portable dataset schema")
    if manifest.get("days") != list(DAYS) or manifest.get("channels") != ["405", "561", "488"]:
        raise ValueError("Dataset must declare nine visits and C0=405/C1=561/C2=488")
    stacks = manifest.get("stacks")
    if not isinstance(stacks, dict) or set(stacks) != set(WELLS):
        raise ValueError("Dataset requires all six declared wells")
    records = {"master": manifest.get("master"), **stacks}
    actual = {}
    for name, record in records.items():
        if not isinstance(record, dict) or not re.fullmatch(r"[a-f0-9]{64}", str(record.get("sha256", ""))):
            raise ValueError("Every dataset file requires its expected SHA256")
        path = local_file(root, record.get("path"))
        digest = sha256(path)
        if digest != record["sha256"]:
            raise ValueError("Dataset checksum mismatch: " + name)
        actual[name] = {"path": str(path), "sha256": digest, "bytes": path.stat().st_size}
    with Path(actual["master"]["path"]).open(newline="") as stream:
        reader = csv.DictReader(stream)
        required = {"neuron_id", "well", "day", "time_index", "anchor_y", "anchor_x", "tracking_valid"}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError("Master is missing required frozen-track columns")
        rows = list(reader)
    return manifest, actual, rows


def verify_frozen_dataset(root):
    """Public CLI requires the exact frozen master/source transfer contract."""
    script = ROOT / "scripts" / "prepare_portable_dataset.py"
    spec = importlib.util.spec_from_file_location("portable_dataset_contract", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.verify_local_dataset(root)


def mentioned_ids(root=ROOT):
    """Historical inventory helper only; never used by benchmark execution."""
    excluded = set(FIXED_EXCLUSIONS)
    for directory in (Path(root) / "docs", Path(root) / "configs"):
        if not directory.exists():
            continue
        for path in sorted(directory.rglob("*")):
            if path.is_file() and not path.is_symlink() and path.suffix.lower() in {".md", ".txt", ".csv", ".json", ".yaml", ".yml"}:
                excluded.update(ID_RE.findall(path.read_text(errors="replace")))
    return excluded


def _integer(value):
    number = float(value)
    if not math.isfinite(number) or number != int(number):
        raise ValueError("Expected an integer visit index")
    return int(number)


def select_panel(rows, count, exclusions, seed="portable-20261027"):
    grouped = {}
    for row in rows:
        nid = str(row.get("neuron_id", ""))
        if ID_RE.fullmatch(nid) and row.get("well") in WELLS and nid.startswith(row["well"] + "_"):
            grouped.setdefault(nid, []).append(row)
    eligible = {well: [] for well in WELLS}
    ineligible = {}
    for nid, visits in sorted(grouped.items()):
        if nid in exclusions:
            continue
        try:
            ordered = sorted(visits, key=lambda r: _integer(r["time_index"]))
            valid = (len(ordered) == 9 and [_integer(r["day"]) for r in ordered] == list(DAYS)
                     and [_integer(r["time_index"]) for r in ordered] == list(range(9))
                     and len({r["well"] for r in ordered}) == 1)
            valid = valid and all(math.isfinite(float(r[key])) for r in ordered for key in ("anchor_y", "anchor_x"))
            valid = valid and all(str(r["tracking_valid"]).strip().lower() in {"true", "false", "0", "1", "0.0", "1.0"} for r in ordered)
        except (ValueError, KeyError, TypeError, OverflowError):
            valid = False
        if valid:
            eligible[ordered[0]["well"]].append(nid)
        else:
            ineligible[nid] = "Missing/invalid frozen visit records; no anchor or QC repair attempted"
    for well in WELLS:
        eligible[well].sort(key=lambda nid: (hashlib.sha256((seed + "|" + nid).encode()).hexdigest(), nid))
    # Round-robin order gives every well a first opportunity within the budget.
    selected = [eligible[well][rank] for rank in range(count) for well in WELLS if len(eligible[well]) > rank]
    return selected, {well: len(eligible[well]) for well in WELLS}, ineligible


def frozen_selection(path, files, rows, *, count, seed, extra_exclusions=()):
    """Reconstruct an explicitly declared panel, independent of prose changes."""
    policy = json.loads(Path(path).read_text())
    if (policy.get("schema_version") != "tmem.panel_selection.v1"
            or not policy.get("version") or policy.get("days") != list(DAYS)
            or policy.get("wells") != list(WELLS)
            or policy.get("seed") != seed or policy.get("tracks_per_well") != count
            or policy.get("tracking_validity_preserved") is not True
            or policy.get("biological_acceptance_granted") is not False):
        raise ValueError("Selection parameters require a matching versioned panel manifest")
    records = policy.get("historical_exclusions", [])
    exclusions = {r["neuron_id"] for r in records}
    if (len(records) != len(exclusions) or not FIXED_EXCLUSIONS.issubset(exclusions)
            or any(not r.get("reason") or not r.get("provenance") for r in records)
            or not set(extra_exclusions).issubset(exclusions)):
        raise ValueError("Exclusions require explicit provenance and a new manifest for changes")
    expected = policy.get("input_sha256")
    if expected != {k: v["sha256"] for k, v in files.items()}:
        raise ValueError("Selection dataset/master checksum binding is stale")
    selected, eligible, invalid = select_panel(rows, count, exclusions, seed)
    if selected != policy.get("selected_neuron_ids") or len(selected) != count * len(WELLS):
        raise ValueError("Frozen selection cannot be reconstructed from supplied master")
    return policy, selected, eligible, invalid


def compact_case(trace):
    trace = Path(trace)
    summary = json.loads((trace / "summary.json").read_text())
    if (summary.get("software_execution_complete") is not True or summary.get("real_accepted_ids") != []
            or summary.get("scientific_inference_ready") is not False or summary.get("production_eligible") is not False):
        raise ValueError("Diagnostic summary does not preserve execution and acceptance safeguards")
    tracking = json.loads((trace / "tracking_comparison.json").read_text())
    sensitivity = json.loads((trace / "parameter_sensitivity.json").read_text())
    if tracking.get("all_proposals_unadopted") is not True or sensitivity.get("all_settings_unadopted") is not True:
        raise ValueError("Unexpected adopted diagnostic proposal")
    radii = {}
    for radius, rows in tracking.get("results_by_radius", {}).items():
        distances = [float(r["displacement_from_stored_anchor_px"]) for r in rows]
        if not distances or not all(math.isfinite(v) and v >= 0 for v in distances):
            raise ValueError("Invalid tracking displacement evidence")
        radii[str(radius)] = {
            "max_proposal_departure_from_stored_anchor_px": max(distances),
            "visits_with_departure_over_20px": sum(v > 20 for v in distances),
            "departure_20px_is_descriptive_only": True,
        }
    return {
        "diagnostic_status": summary["diagnostic_status"],
        "valid_488_visit_count": summary.get("valid_488_visit_count"),
        "core_area_px": summary.get("core_area_px"),
        "core_constructed": summary.get("core_constructed"),
        "automated_secondary_soma_single_pass": summary.get("automated_secondary_soma_single_pass"),
        "tracking_by_search_radius_px": radii,
        "segmentation_sensitivity": [{k: setting.get(k) for k in ("segmentation_min_area_px", "valid_visit_count", "core_constructed", "core_area_px", "core_rejection")}
                                     for setting in sensitivity.get("settings", [])],
        "all_proposals_unadopted": True,
        "reviewed_or_accepted": False,
        "scientific_inference_ready": False,
    }


def run_case(nid, files, out, config, timeout_seconds, python=sys.executable):
    destination = Path(out) / "tracks" / nid
    destination.parent.mkdir(parents=True, exist_ok=True)
    command = [python, str(ROOT / "scripts" / "trace_tmem_pipeline.py"), "registered-track",
               "--stack", files[nid.split("_")[0]]["path"], "--master", files["master"]["path"],
               "--neuron-id", nid, "--config", str(config), "--out", str(destination)]
    start = time.monotonic()
    result = {"neuron_id": nid, "well": nid.split("_")[0], "command": command,
              "trace_path": "tracks/" + nid, "status": "failed", "real_accepted_ids": [],
              "scientific_inference_ready": False}
    log_path = Path(out) / "logs" / (nid + ".log")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w") as log:
        try:
            process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
            try:
                result["returncode"] = process.wait(timeout=max(0.1, timeout_seconds))
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
                result.update(status="timeout", returncode=process.returncode,
                              reason="Time budget reached; partial trace preserved and cannot grant acceptance")
            else:
                if process.returncode == 0:
                    result["diagnostics"] = compact_case(destination)
                    result["status"] = "software_completed"
                else:
                    result["reason"] = "Diagnostic CLI returned a software/input failure; inspect log"
        except Exception as error:
            result.update(status="failed", reason=type(error).__name__ + ": " + str(error))
    result["elapsed_seconds"] = round(time.monotonic() - start, 3)
    result["log_path"] = "logs/" + nid + ".log"
    return result


def _write_report(out, state):
    lines = ["# Portable six-well diagnostic benchmark", "", "This is a diagnostic sample, not a held-out or accepted biological cohort.",
             "Original anchors and measurement policies remain unchanged. All tracking, LUT and parameter proposals remain unadopted.",
             "Historical raw IC, stitching and registration are unavailable from these registered stacks.", "",
             "| Neuron | Execution | Valid 488 visits | Core pixels |", "|---|---|---:|---:|"]
    for nid in state["selected_neuron_ids"]:
        result = state["results"][nid]
        details = result.get("diagnostics", {})
        lines.append(f"| {nid} | {result['status']} | {details.get('valid_488_visit_count', '—')} | {details.get('core_area_px', '—')} |")
    lines += ["", "Numeric tracking departures and segmentation sensitivity are recorded in `benchmark_summary.json`.",
              "A matching score, completed execution or automated soma-screen pass cannot establish soma identity or ROI ownership.", "",
              "No parameter setting was selected from phenotype results. No accepted metrics were exported.", ""]
    (Path(out) / "BENCHMARK_RESULTS.md").write_text("\n".join(lines))


def execute(dataset, out, *, minutes=35.0, workers=2, tracks_per_well=2, case_timeout_minutes=12.0,
            config=None, excluded_ids=(), seed="portable-20261027", case_runner=run_case,
            selection_manifest=DEFAULT_SELECTION):
    if not (math.isfinite(minutes) and 0 < minutes <= 55 and workers in {1, 2}
            and 1 <= tracks_per_well <= 10 and math.isfinite(case_timeout_minutes) and 0 < case_timeout_minutes <= 30):
        raise ValueError("Require minutes in (0,55], workers1..2, tracks-per-well1..10, and case timeout in (0,30]")
    started = time.monotonic()
    deadline = started + minutes * 60
    manifest, files, rows = load_dataset(dataset)
    config = Path(config or ROOT / "configs" / "tmem_stage_diagnostics.json").resolve()
    if not config.is_file():
        raise ValueError("Missing diagnostic configuration")
    policy, selected, eligible, ineligible = frozen_selection(
        selection_manifest, files, rows, count=tracks_per_well, seed=seed,
        extra_exclusions=excluded_ids)
    exclusions = {r["neuron_id"] for r in policy["historical_exclusions"]}
    if policy.get("configuration_sha256") != sha256(config):
        raise ValueError("Frozen primary configuration has changed")
    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=False)
    state = {
        "schema_version": "tmem.portable_benchmark.v1", "status": "running",
        "panel_scope": "deterministic diagnostic sample; prior-review history incomplete; not claimed held out",
        "selection_basis": "Identifier hashing and exact nine frozen visits; no 561 values, outcome ranking, or tracking-validity optimization",
        "seed": seed, "days": list(DAYS), "wells": list(WELLS),
        "selection_manifest_sha256": sha256(selection_manifest),
        "selection_manifest_version": policy["version"],
        "requested_tracks_per_well": tracks_per_well, "eligible_counts_after_exclusions": eligible,
        "excluded_documented_ids": sorted(exclusions), "invalid_visit_records": ineligible,
        "selected_neuron_ids": selected, "input_files": files,
        "configuration": {"path": str(config), "sha256": sha256(config)},
        "budget_minutes": minutes, "workers": workers,
        "scientific_inference_ready": False, "real_accepted_ids": [],
        "historical_ic_and_stitching_validated": False, "all_proposals_unadopted": True,
        "results": {nid: {"neuron_id": nid, "status": "pending"} for nid in selected},
    }
    summary_path = out / "benchmark_summary.json"
    atomic_json(summary_path, state)
    pending = list(selected)
    running = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        while pending or running:
            while pending and len(running) < workers and deadline - time.monotonic() > 1.0:
                nid = pending.pop(0)
                timeout = min(case_timeout_minutes * 60, max(0.1, deadline - time.monotonic()))
                running[pool.submit(case_runner, nid, files, out, config, timeout)] = nid
                state["results"][nid] = {"neuron_id": nid, "status": "running"}
                atomic_json(summary_path, state)
            if not running:
                break
            done, _ = wait(running, timeout=0.25, return_when=FIRST_COMPLETED)
            for future in done:
                nid = running.pop(future)
                try:
                    state["results"][nid] = future.result()
                except Exception as error:
                    state["results"][nid] = {"neuron_id": nid, "status": "failed", "reason": type(error).__name__ + ": " + str(error)}
                atomic_json(summary_path, state)
    for nid in pending:
        state["results"][nid] = {"neuron_id": nid, "status": "deferred_budget", "reason": "No new process launched after the local budget"}
    state["elapsed_seconds"] = round(time.monotonic() - started, 3)
    counts = {}
    for result in state["results"].values():
        counts[result["status"]] = counts.get(result["status"], 0) + 1
    state["execution_counts"] = counts
    state["selected_well_coverage"] = {well: sum(n.startswith(well + "_") for n in selected) for well in WELLS}
    state["completed_well_coverage"] = {well: sum(n.startswith(well + "_") and r["status"] == "software_completed"
                                                    for n, r in state["results"].items()) for well in WELLS}
    state["all_selected_wells_represented"] = all(state["selected_well_coverage"].values())
    state["all_requested_wells_represented"] = all(state["completed_well_coverage"].values())
    state["full_requested_panel_selected"] = all(sum(n.startswith(w + "_") for n in selected) == tracks_per_well for w in WELLS)
    state["status"] = "completed_pending_scientific_review" if (
        selected and all(r["status"] == "software_completed" for r in state["results"].values())
        and state["full_requested_panel_selected"]) else "partial_or_blocked"
    # Bind the finished report to the same supplied master/config bytes. The
    # existing per-track CLI independently verifies stack bytes before/after.
    state["master_and_configuration_unchanged"] = (
        sha256(files["master"]["path"]) == files["master"]["sha256"]
        and sha256(config) == state["configuration"]["sha256"])
    if not state["master_and_configuration_unchanged"]:
        state["status"] = "unusable_source_changed"
    atomic_json(summary_path, state)
    _write_report(out, state)
    return state


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True, help="New output directory; existing results are never overwritten")
    parser.add_argument("--minutes", type=float, default=35.0)
    parser.add_argument("--workers", type=int, choices=[1, 2], default=2)
    parser.add_argument("--tracks-per-well", type=int, default=2)
    parser.add_argument("--case-timeout-minutes", type=float, default=12.0)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--exclude-id", action="append", default=[])
    parser.add_argument("--seed", default="portable-20261027")
    parser.add_argument("--selection-manifest", type=Path, default=DEFAULT_SELECTION)
    args = parser.parse_args(argv)
    try:
        verify_frozen_dataset(args.dataset)
        result = execute(args.dataset, args.out, minutes=args.minutes, workers=args.workers,
                         tracks_per_well=args.tracks_per_well, case_timeout_minutes=args.case_timeout_minutes,
                         config=args.config, excluded_ids=args.exclude_id, seed=args.seed,
                         selection_manifest=args.selection_manifest)
    except Exception as error:
        parser.exit(2, "PORTABLE_BENCHMARK_BLOCKED: " + type(error).__name__ + ": " + str(error) + "\n")
    print("TMEM_PORTABLE_STATUS=" + result["status"])
    print("TMEM_PORTABLE_SUMMARY=" + str((args.out / "benchmark_summary.json").resolve()))
    print("No accepted cohort, measurement export or historical IC validation was granted.")
    return 0 if result["status"] == "completed_pending_scientific_review" else 2


if __name__ == "__main__":
    raise SystemExit(main())
