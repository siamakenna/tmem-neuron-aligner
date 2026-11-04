"""Explicit future checkpoint run. Never invoke against the active legacy output."""

import argparse
import csv
from pathlib import Path

from tmem_align.audit_v1.full_plate import load_contract, sha, validate_tables
from tmem_align.audit_v1.plate_preflight import (
    PARAMETERS,
    build_run_binding,
    canonical_digest,
    preflight_selection,
    runtime_fingerprint,
    source_tree_fingerprint,
    validate_legacy_contract,
)
from tmem_align.audit_v1.well_checkpoints import run_jobs


def aggregate_tables(receipts, jobs):
    import pandas as pd
    from run_260213_all_wells_batch import build_all_well_summary

    qc = [row for receipt in receipts for row in receipt["result"]["qc"]]
    metrics = [row for receipt in receipts for row in (receipt["result"]["metrics"] or [])]
    errors = [r["result"]["error"] for r in receipts if r["result"]["error"]]
    summary = build_all_well_summary(pd.DataFrame(qc), pd.DataFrame(metrics), pd.DataFrame(errors))
    tables = {
        "all_wells_selected_files.csv": [r for job in jobs for r in job["rows"]],
        "all_wells_registration_qc.csv": qc,
        "all_wells_mcherry_measurements.csv": metrics,
        "all_wells_failures.csv": errors,
        "all_wells_summary_stats.csv": summary.to_dict(orient="records"),
    }
    validation = validate_tables(
        {
            name.removeprefix("all_wells_").removesuffix(".csv"): rows
            for name, rows in tables.items()
        },
        jobs[0]["contract"],
    )
    if validation["issues"]:
        raise ValueError("Aggregate validation failed: " + repr(validation))
    return tables


def worker(job, *, legacy=None, inspect_header=None):
    """Recheck headers immediately before delegation and guard actual loader output."""
    contract = validate_legacy_contract(job["contract"])
    if (
        job.get("well") not in contract["wells"]
        or job.get("days") != contract["visits"]
        or any(type(d) is not int for d in job["days"])
        or job.get("channels")
        != [contract["channels"]["alignment"], contract["channels"]["phenotype"]]
        or {r.get("well") for r in job["rows"]} != {job["well"]}
        or [r.get("day") for r in job["rows"]] != contract["visits"]
    ):
        raise ValueError("Per-well task identity/schedule/channel mismatch")
    if (
        job.get("source_tree_sha256") is not None
        and source_tree_fingerprint(Path(__file__).resolve().parents[1])
        != job["source_tree_sha256"]
    ):
        raise ValueError("Scientific source tree changed before execution")
    for path, expected_sha in job.get("input_document_sha256", {}).items():
        if sha(path) != expected_sha:
            raise ValueError("Processing configuration/selection changed")
    if job.get("runtime") is not None and runtime_fingerprint() != job["runtime"]:
        raise ValueError("Execution runtime changed")
    if legacy is None:
        import run_260213_all_wells_batch as legacy
    fresh = preflight_selection(
        job["rows"], job["contract"], inspect_header=inspect_header, complete=False
    )
    if canonical_digest(fresh) != job["preflight_sha256"]:
        raise ValueError("Preflight changed before execution")
    expected = {r["path"]: r for r in fresh["observations"]}
    loader = legacy.load_nd2_cyx

    def checked_loader(path, *args, **kwargs):
        value = loader(path, *args, **kwargs)
        record = expected[str(Path(path).absolute())]
        array = value["array"]
        if (
            list(array.shape) != record["header"]["shape"]
            or str(array.dtype) != record["header"]["dtype"]
            or value["channel_names"] != record["ordered_channel_names"]
        ):
            raise ValueError("Loaded image differs from source-bound header")
        return value

    legacy.load_nd2_cyx = checked_loader
    try:
        result = legacy._process_one_well(
            job["well"],
            [{**r, "path": Path(r["path"])} for r in job["rows"]],
            job["days"],
            job["channels"],
            PARAMETERS["max_sites"],
            PARAMETERS["max_read_bytes"],
            ref_mode=PARAMETERS["ref_mode"],
            anchor_corr_thresh=PARAMETERS["anchor_corr_thresh"],
            min_post_correlation=PARAMETERS["min_post_correlation"],
            plate_offsets=None,
        )
    finally:
        legacy.load_nd2_cyx = loader
    if (
        job.get("source_tree_sha256") is not None
        and source_tree_fingerprint(Path(__file__).resolve().parents[1])
        != job["source_tree_sha256"]
    ):
        raise ValueError("Scientific source tree changed during execution")
    for path, expected_sha in job.get("input_document_sha256", {}).items():
        if sha(path) != expected_sha:
            raise ValueError("Processing configuration/selection changed during execution")
    if job.get("runtime") is not None and runtime_fingerprint() != job["runtime"]:
        raise ValueError("Execution runtime changed during processing")
    metrics = result.get("metrics")
    if (
        job["well"] not in job["contract"]["reporter_wells"]
        and metrics is not None
        and len(metrics)
    ):
        raise ValueError("Nonreporter phenotype output prohibited")
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for k in ("dataset-config", "selection", "out"):
        p.add_argument("--" + k, type=Path, required=True)
    p.add_argument("--workers", type=int, default=1)
    p.add_argument("--resume", action="store_true")
    a = p.parse_args()
    config_sha, selection_sha = sha(a.dataset_config), sha(a.selection)
    c = load_contract(a.dataset_config)
    validate_legacy_contract(c)
    with a.selection.open() as f:
        rows = list(csv.DictReader(f))
    preflight_selection(rows, c)
    jobs = []
    for well in c["wells"]:
        series = sorted([r for r in rows if r["well"] == well], key=lambda r: int(r["day"]))
        for r in series:
            r["day"] = int(r["day"])
        preflight = preflight_selection(series, c, complete=False)
        jobs.append(
            {
                "well": well,
                "rows": series,
                "sources": [r["path"] for r in series],
                "days": c["visits"],
                "channels": [c["channels"]["alignment"], c["channels"]["phenotype"]],
                "sites": c["sites"],
                "contract": c,
                "preflight": preflight,
                "preflight_sha256": canonical_digest(preflight),
            }
        )
    root = Path(__file__).resolve().parents[1]
    binding = build_run_binding(root, a.dataset_config, a.selection, c)
    if sha(a.dataset_config) != config_sha or sha(a.selection) != selection_sha:
        raise ValueError("Contract/selection changed during preflight")
    for job in jobs:
        job["source_tree_sha256"] = binding["source_tree_sha256"]
        job["input_document_sha256"] = binding["input_document_sha256"]
        job["runtime"] = binding["runtime"]
    result = run_jobs(
        jobs,
        worker,
        a.out,
        binding,
        workers=a.workers,
        resume=a.resume,
        aggregate_tables=aggregate_tables,
    )
    print("Durable well receipts:", len(result), "(not scientific acceptance)")


if __name__ == "__main__":
    main()
