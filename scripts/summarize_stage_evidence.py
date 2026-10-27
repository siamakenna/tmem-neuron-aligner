#!/usr/bin/env python3
"""Audit a returned stage-results ZIP and save small, source-bound evidence notes.

This is a standard-library file-integrity and recorded-results reader. It does
not rerun microscopy, approve tracks, or establish biological validity.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import stat
import tempfile
import xml.etree.ElementTree as ET
import zipfile


MAX_FILES = 50000
MAX_MEMBER = 256 * 1024 * 1024
MAX_EXPANDED = 768 * 1024 * 1024
CASES = ("E05_N006", "F05_N007", "J05_N015")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def safe_name(name):
    path = PurePosixPath(name)
    if (not name or path.is_absolute() or ".." in path.parts or
            "\\" in name or "\x00" in name or str(path) != name.rstrip("/")):
        raise ValueError(f"Unsafe archive path: {name!r}")
    return path


def validated_archive(data):
    """Return a verified archive and member digests; caller closes the archive."""
    archive = zipfile.ZipFile(io.BytesIO(data))
    try:
        entries = archive.infolist()
        if len(entries) > MAX_FILES or sum(i.file_size for i in entries) > MAX_EXPANDED:
            raise ValueError("Archive exceeds the evidence-reader size limit")
        all_names = [i.filename for i in entries]
        if len(all_names) != len(set(all_names)):
            raise ValueError("Duplicate archive member")
        files = {}
        roots = set()
        for info in entries:
            path = safe_name(info.filename)
            roots.add(path.parts[0])
            mode = info.external_attr >> 16
            if stat.S_ISLNK(mode) or (stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR)):
                raise ValueError("Archive links and special files are forbidden")
            if info.flag_bits & 1 or info.file_size > MAX_MEMBER:
                raise ValueError("Encrypted or oversized member")
            if not info.is_dir():
                files[info.filename] = info
        if len(roots) != 1:
            raise ValueError("Require one archive root directory")
        prefix = roots.pop() + "/"
        sums_name = prefix + "SHA256SUMS"
        if sums_name not in files:
            raise ValueError("Missing SHA256SUMS")
        if files[sums_name].file_size > 16 * 1024 * 1024:
            raise ValueError("Oversized SHA256SUMS")
        wanted = {}
        for line in archive.read(sums_name).decode("utf-8").splitlines():
            match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
            if not match:
                raise ValueError("Malformed SHA256SUMS line")
            sha, relative = match.groups()
            safe_name(relative)
            name = prefix + relative
            if name in wanted or name == sums_name:
                raise ValueError("Duplicate or self-referential checksum entry")
            wanted[name] = sha
        if set(wanted) != set(files) - {sums_name}:
            raise ValueError("Archive contains unlisted or missing members")
        for name, expected in wanted.items():
            h = hashlib.sha256()
            with archive.open(name) as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    h.update(chunk)
            if h.hexdigest() != expected:
                raise ValueError(f"Checksum mismatch: {name}")
        return archive, prefix, wanted
    except Exception:
        archive.close()
        raise


def read_json(archive, name):
    if archive.getinfo(name).file_size > 64 * 1024 * 1024:
        raise ValueError("Oversized JSON evidence")
    return json.loads(archive.read(name))


def phase_result(xml_bytes, log_bytes):
    """Reconcile pytest's distinct tests/subtests with its JUnit execution count."""
    if len(xml_bytes) > 4 * 1024 * 1024 or b"<!DOCTYPE" in xml_bytes.upper():
        raise ValueError("Unsupported XML evidence")
    root = ET.fromstring(xml_bytes)
    suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
    if not suites:
        raise ValueError("No JUnit suites")
    totals = {key: sum(int(s.get(key, "0")) for s in suites)
              for key in ("tests", "failures", "errors", "skipped")}
    if totals["tests"] <= 0 or any(totals[k] for k in ("failures", "errors", "skipped")):
        raise ValueError("Recorded test phase is empty, failed, or skipped")
    # Accept only a complete terminal summary; don't count names or progress dots.
    summaries = re.findall(r"(?m)^(\d+) passed(?:, (\d+) subtests passed)? in ([0-9.]+)s\s*$",
                           log_bytes.decode("utf-8"))
    if len(summaries) != 1:
        raise ValueError("Missing or ambiguous pytest terminal summary")
    tests, subtests, seconds = summaries[0]
    tests, subtests = int(tests), int(subtests or 0)
    if tests + subtests != totals["tests"]:
        raise ValueError("JUnit count disagrees with pytest tests/subtests")
    return {"tests_passed": tests, "subtests_passed": subtests,
            "counted_executions": totals["tests"], "failures": 0, "errors": 0,
            "skipped": 0, "pytest_reported_seconds": float(seconds)}


def compact_case(archive, prefix, hashes, case):
    trace = prefix + "trace/"
    manifest = read_json(archive, trace + "manifest.json")
    if manifest.get("complete") is not True:
        raise ValueError("Unfinished trace")
    for path, sha in manifest["files"].items():
        safe_name(path)
        if hashes.get(trace + path) != sha:
            raise ValueError(f"Trace manifest hash disagrees: {path}")
    counts = dict(Counter(stage["status"] for stage in manifest["stages"]))
    reported = {k: v for k, v in manifest["stage_status_counts"].items() if v}
    if counts != reported:
        raise ValueError("Stage counts disagree with manifest")
    for stage in manifest["stages"]:
        if hashes.get(trace + stage["record_file"]) != stage["record_sha256"]:
            raise ValueError("Stage-record checksum mismatch")
    summary = read_json(archive, trace + "summary.json")
    if (summary.get("neuron_id") != case or summary.get("real_accepted_ids") != [] or
            summary.get("scientific_inference_ready") is not False or
            summary.get("production_eligible") is not False or
            summary.get("accepted_metrics_csv_written") is not False):
        raise ValueError("Unexpected scientific release claim")
    track = read_json(archive, trace + "tracking_comparison.json")
    if track.get("all_proposals_unadopted") is not True:
        raise ValueError("Tracking proposal adoption differs from declared scope")
    tracking = {}
    keep = ("day", "search_radius_px", "displacement_from_stored_anchor_px",
            "diagnostic_match_score", "diagnostic_score_pass", "adopted")
    for radius, rows in track["results_by_radius"].items():
        tracking[radius] = [{k: row[k] for k in keep} for row in rows]
        if any(row["adopted"] is not False for row in tracking[radius]):
            raise ValueError("Tracking row is adopted")
    sensitivity = read_json(archive, trace + "parameter_sensitivity.json")
    if (sensitivity.get("all_settings_unadopted") is not True or
            sensitivity.get("no_best_setting_selected") is not True):
        raise ValueError("Parameter sweep adoption differs from declared scope")
    sweep_keys = ("segmentation_min_area_px", "valid_visit_count", "core_constructed",
                  "core_area_px", "core_rejection", "adopted", "phenotype_used_to_select_setting")
    sweep = [{k: setting[k] for k in sweep_keys} for setting in sensitivity["settings"]]
    if any(s["adopted"] or s["phenotype_used_to_select_setting"] for s in sweep):
        raise ValueError("Adopted or phenotype-selected parameter setting")
    secondary = read_json(archive, trace + "secondary_soma_screen.json")
    return {"neuron_id": case, "trace_manifest_sha256": hashes[trace + "manifest.json"],
            "trace_file_inventory_entries_verified": len(manifest["files"]),
            "stage_status_counts": counts, "summary": summary,
            "tracking_proposals_by_radius": tracking, "segmentation_sweep": sweep,
            "secondary_soma_screen": secondary,
            "input_array_sha256": manifest["metadata"]["source_array_sha256"],
            "source_code_sha256": manifest["metadata"]["source_file_sha256"],
            "measurement_release_authorized": False, "real_accepted_ids": [],
            "scientific_inference_ready": False}


def audit_results(path):
    data = Path(path).read_bytes()
    outer, prefix, hashes = validated_archive(data)
    try:
        run = read_json(outer, prefix + "RUN_SUMMARY.json")
        push = read_json(outer, prefix + "PUSH_RECEIPT.json")
        if (run.get("push_verified") is not True or push.get("status") != "pushed_verified" or
                run.get("commit") != push.get("commit") or
                run.get("payload_sha256") != push.get("payload_sha256")):
            raise ValueError("Recorded push receipts disagree")
        if run.get("real_accepted_ids") != [] or run.get("scientific_inference_ready") is not False:
            raise ValueError("Unexpected run-level release claim")
        cases = {}
        verification = None
        inventories = {}
        for task in ("verification",) + CASES:
            receipt = read_json(outer, prefix + task + "_finalize_receipt.json")
            blob = outer.read(prefix + task + "_results.zip")
            if (receipt["task"] != task or receipt["job_exit_code"] != 0 or
                    digest(blob) != receipt["archive_sha256"] or len(blob) != receipt["archive_bytes"]):
                raise ValueError(f"Finalization receipt mismatch: {task}")
            inner, inner_prefix, inner_hashes = validated_archive(blob)
            try:
                inventories[task] = {"sha256": digest(blob), "bytes": len(blob),
                                     "internal_entries_verified": len(inner_hashes)}
                if task == "verification":
                    vprefix = inner_prefix + "verification/"
                    recorded = read_json(inner, vprefix + "verification_status.json")
                    phases = {phase: phase_result(inner.read(vprefix + phase + ".xml"),
                                                  inner.read(vprefix + phase + ".log"))
                              for phase in ("unit", "integration")}
                    if (recorded.get("status") != "passed" or recorded.get("tests") !=
                            sum(p["counted_executions"] for p in phases.values())):
                        raise ValueError("Verification JSON disagrees with XML/logs")
                    verification = {"phases": phases,
                                    "tests_passed": sum(p["tests_passed"] for p in phases.values()),
                                    "subtests_passed": sum(p["subtests_passed"] for p in phases.values()),
                                    "known_truth_example": recorded["known_truth_example"],
                                    "scope": "Recorded software verification, not experimental validation"}
                else:
                    cases[task] = compact_case(inner, inner_prefix, inner_hashes, task)
            finally:
                inner.close()
        audit = {"schema_version": "tmem.portable_evidence.v1", "source_zip_sha256": digest(data),
                 "source_zip_bytes": len(data), "outer_entries_verified": len(hashes),
                 "task_archives": inventories, "base_commit": run["base_commit"],
                 "payload_sha256": run["payload_sha256"], "recorded_push_receipt": push,
                 "push_scope": "Returned command and receipt; not an independent live GitHub query",
                 "verification": verification, "diagnostic_cases": list(CASES),
                 "track_visits": sum(len(c["summary"]["valid_488_by_day"]) for c in cases.values()),
                 "executed_stage_records": sum(c["stage_status_counts"].get("executed", 0) for c in cases.values()),
                 "real_accepted_ids": [], "scientific_inference_ready": False,
                 "limitations": ["Repeated stage outputs do not increase biological sample size.",
                     "Registered inputs cannot validate historical raw IC, stitching or alignment.",
                     "Correlation and segmentation-validity flags do not establish identity or ROI ownership.",
                     "Archive checksums establish internal consistency, not independent authenticity.",
                     "Scheduler elapsed and queue times were not included."]}
        return audit, cases
    finally:
        outer.close()


def write_evidence(path, out):
    audit, cases = audit_results(path)
    out = Path(out)
    if out.exists():
        raise FileExistsError("Choose a new output directory; existing evidence is preserved")
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".stage_evidence_", dir=out.parent) as tmp:
        stage = Path(tmp) / "evidence"
        stage.mkdir()
        records = {"AUDIT.json": audit, "PUSH_RECEIPT.json": audit["recorded_push_receipt"],
                   "VERIFICATION.json": audit["verification"]}
        records.update({case + ".json": record for case, record in cases.items()})
        for name, record in records.items():
            (stage / name).write_text(json.dumps(record, indent=2, allow_nan=False) + "\n")
        v = audit["verification"]
        text = ("# Verified returned evidence\n\n"
                f"Source ZIP SHA256: `{audit['source_zip_sha256']}`.\n\n"
                f"Verified {audit['outer_entries_verified']} outer checksum entries and all four nested inventories. "
                f"Recorded software verification: **{v['tests_passed']} tests + {v['subtests_passed']} subtests passed**, "
                "with zero failures, errors or skips.\n\n"
                f"Recorded push: `{audit['recorded_push_receipt']['commit']}` on "
                f"`{audit['recorded_push_receipt']['branch']}`. This records the returned push evidence; "
                "it is not a live GitHub query.\n\n"
                f"Three diagnostic tracks, {audit['track_visits']} track-visits, "
                f"{audit['executed_stage_records']} executed intermediate stage records. "
                "All candidate tracking, LUT boxes and parameter settings remain unadopted.\n\n"
                "No biological cohort was accepted. The IC/alignment known-truth example is synthetic. "
                "Historical real-input IC, stitching and alignment remain unvalidated.\n\n"
                "Per-case JSON preserves the measured parameter sensitivity and tracking proposals. "
                "A passing automatic secondary-soma screen does not establish ROI ownership.\n")
        (stage / "AUDIT.md").write_text(text)
        stage.rename(out)
    return audit


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-zip", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    result = write_evidence(args.results_zip, args.out)
    print(f"EVIDENCE_VERIFIED={args.out.resolve()}")
    print(f"TESTS={result['verification']['tests_passed']}")
    print(f"SUBTESTS={result['verification']['subtests_passed']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
