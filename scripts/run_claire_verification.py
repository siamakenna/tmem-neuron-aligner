#!/usr/bin/env python3
"""Verify an immutable portable TMEM handoff and run all automated checks.

No Git checkout is required. Source identity comes from verified file hashes.
Human scientific review and original-acquisition stitching are separate gates.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

IGNORED_PARTS = {"__pycache__", ".pytest_cache", ".git"}


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def generated_file(path: Path) -> bool:
    return (any(part in IGNORED_PARTS or part.endswith(".egg-info") for part in path.parts)
            or path.suffix in {".pyc", ".pyo"} or path.name == ".DS_Store")


def verify_manifest(root: Path) -> dict:
    """Check every payload byte and reject ambiguous/unlisted input files."""
    root = root.resolve(strict=True)
    manifest = root / "SHA256SUMS"
    if manifest.is_symlink() or not manifest.is_file():
        raise ValueError("Handoff requires a regular SHA256SUMS file")
    expected = {}
    for number, line in enumerate(manifest.read_text().splitlines(), 1):
        match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
        if not match:
            raise ValueError(f"Invalid SHA256SUMS line {number}")
        sha, name = match.groups()
        relative = PurePosixPath(name)
        if (relative.is_absolute() or ".." in relative.parts or "\\" in name
                or relative.as_posix() != name or name == "SHA256SUMS"):
            raise ValueError(f"Unsafe or ambiguous manifest path: {name}")
        if name in expected:
            raise ValueError(f"Duplicate manifest entry: {name}")
        path = root.joinpath(*relative.parts)
        if (not path.is_file() or any(p.is_symlink() for p in [path, *path.parents]
                                     if p == root or p.is_relative_to(root))
                or not path.resolve().is_relative_to(root)):
            raise ValueError(f"Missing or nonlocal regular manifest file: {name}")
        if digest(path) != sha:
            raise ValueError(f"Checksum mismatch: {name}")
        expected[name] = sha
    if not expected:
        raise ValueError("Empty manifest is not a portable handoff")
    ignored = []
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        if generated_file(relative):
            if path.is_file():
                ignored.append(relative.as_posix())
            continue
        if path.is_symlink():
            raise ValueError(f"Unexpected symbolic link in handoff: {relative}")
        if path.is_file() and relative.as_posix() not in expected and relative.as_posix() != "SHA256SUMS":
            raise ValueError(f"Unmanifested handoff input: {relative}")
    required = {"source/pyproject.toml", "source/scripts/run_claire_verification.py",
                "source/scripts/run_tmem_audit.py", "source/scripts/export_reviewed_metrics.py",
                "source/configs/tmem_review_v6.json", "source/docs/audit_v1/claire_stress_cases.csv",
                "stress_results.csv"}
    missing = required - expected.keys()
    if missing:
        raise ValueError("Incomplete handoff: " + ", ".join(sorted(missing)))
    if digest(Path(__file__).resolve()) != expected["source/scripts/run_claire_verification.py"]:
        raise ValueError("Loaded verification runner differs from the handoff's verified runner")
    return {"manifest_sha256": digest(manifest), "verified_files": len(expected),
            "files": expected, "ignored_generated_files": sorted(ignored)}


def reserve_output(root: Path, out: Path) -> Path:
    root = root.expanduser().resolve()
    out = out.expanduser().resolve()
    if out == root or out.is_relative_to(root):
        raise ValueError("Use a NEW output directory outside the immutable handoff")
    out.mkdir(parents=True, exist_ok=False)
    return out


def review_root(root: Path) -> Path:
    candidates = [p for p in [root / "review", root / "workspace" / "review"]
                  if (p / "manual_review_template.json").is_file()]
    if len(candidates) != 1:
        raise ValueError("Require exactly one portable review directory")
    return candidates[0]


def run_stage(name: str, command: list[str], source: Path, out: Path,
              env: dict[str, str], stages: list, expected_exit: int = 0) -> int:
    print(f"Running {name}; log: {out / (name + '.log')}", flush=True)
    started = time.monotonic()
    with (out / f"{name}.log").open("w") as handle:
        result = subprocess.run(command, cwd=source, env=env, stdout=handle,
                                stderr=subprocess.STDOUT, check=False)
    code = result.returncode
    stages.append({"stage": name, "command": command, "returncode": code,
                   "expected_returncode": expected_exit, "passed": code == expected_exit,
                   "seconds": round(time.monotonic() - started, 3), "log": f"{name}.log"})
    return code


def environment_record(out: Path, source: Path, env: dict[str, str]) -> bool:
    versions = sorted({dist.metadata.get("Name", "unknown"): dist.version
                       for dist in importlib.metadata.distributions()}.items())
    record = {"python_version": sys.version, "executable": sys.executable,
              "platform": platform.platform(), "machine": platform.machine(),
              "implementation": platform.python_implementation(), "distributions": dict(versions)}
    result = subprocess.run([sys.executable, "-m", "pip", "freeze", "--all"],
                            cwd=source, env=env, capture_output=True, text=True, check=False)
    (out / "environment.txt").write_text(result.stdout)
    if result.stderr:
        (out / "environment_stderr.txt").write_text(result.stderr)
    record["pip_freeze_exit_status"] = result.returncode
    write_json(out / "environment.json", record)
    return result.returncode == 0


def test_summary(xml_path: Path, log_path: Path) -> dict:
    """Preserve pytest's ordinary/subtest distinction instead of double counting."""
    result = {"ordinary_tests_passed": None, "subtests_passed": None}
    if log_path.exists():
        log = log_path.read_text()
        ordinary = re.findall(r"(?:^|[,\s])(\d+) passed(?:[,\s]|$)", log)
        subtests = re.findall(r"(\d+) subtests passed", log)
        if ordinary:
            result["ordinary_tests_passed"] = int(ordinary[-1])
        result["subtests_passed"] = int(subtests[-1]) if subtests else 0
    if xml_path.exists():
        try:
            doc = ET.parse(xml_path).getroot()
        except ET.ParseError as error:
            result["junit_parse_error"] = str(error)
            return result
        suites = [doc] if doc.tag == "testsuite" else doc.findall("testsuite")
        result["junit_counts_including_subtests"] = {
            key: sum(int(suite.get(key, "0")) for suite in suites)
            for key in ["tests", "failures", "errors", "skipped"]}
    return result


def mapped_case_results(root: Path, xml_path: Path) -> list[dict]:
    """Prove each declared automatic case names an actually executed assertion."""
    cases = list(ET.parse(xml_path).getroot().iter("testcase"))
    with (root / "stress_results.csv").open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    with (root / "source/docs/audit_v1/claire_stress_cases.csv").open(newline="") as handle:
        expected_rows = list(csv.DictReader(handle))
    mutable = {"execution_status", "observed_result", "reviewer", "failure_classification",
               "actual_classification", "execution_role", "notes", "reviewed_at"}
    def recipes(records):
        result = {}
        for row in records:
            case = row.get("case", "").strip()
            if not case or case in result:
                raise ValueError("Stress case IDs must be nonempty and unique")
            result[case] = {key: value for key, value in row.items() if key not in mutable}
        if not result:
            raise ValueError("Stress matrix cannot be empty")
        return result
    if recipes(rows) != recipes(expected_rows):
        raise ValueError("Portable stress recipes differ from the tested source matrix")
    results = []
    for row in rows:
        node = row.get("test_node", "").strip()
        automated = row.get("mode", "") in {"automated", "automated_and_manual"}
        if not node:
            if automated and row.get("availability_status") != "blocked_missing_real_input":
                raise ValueError(f"Automated case lacks test_node: {row.get('case')}")
            continue
        parts = node.split("::")
        if len(parts) < 2:
            raise ValueError("Stress test_node must identify a test function: " + node)
        classname = ".".join([Path(parts[0]).stem, *parts[1:-1]])
        name = parts[-1].split("[", 1)[0]
        matches = [case for case in cases
                   if (case.get("classname", "") == classname
                       or case.get("classname", "").endswith("." + classname))
                   and case.get("name", "").split("[", 1)[0] == name]
        if not matches:
            raise ValueError("Stress case's mapped assertion was not executed: " + node)
        if any(any(case.find(tag) is not None for tag in ["failure", "error", "skipped"])
               for case in matches):
            raise ValueError("Stress case's mapped assertion did not pass: " + node)
        results.append({"case": row.get("case"), "test_node": node,
                        "mapped_assertions_passed": True, "junit_rows": len(matches)})
    return results


def skip_policy(xml_path: Path) -> dict:
    """Only the separately exercised optional Node DOM check may be unavailable."""
    allowed, unexpected = [], []
    for case in ET.parse(xml_path).getroot().iter("testcase"):
        skipped = case.find("skipped")
        if skipped is None:
            continue
        record = {"classname": case.get("classname", ""), "name": case.get("name", ""),
                  "reason": skipped.get("message", "")}
        known = (record["classname"].endswith("test_review_workspace.WorkspaceTests")
                 and record["name"] == "test_offline_controls_save_resume_and_stale_rejection"
                 and record["reason"] == "Node is optional for the offline UI workflow check"
                 and shutil.which("node") is None)
        (allowed if known else unexpected).append(record)
    return {"allowed_optional_browser_skips": allowed, "unexpected_skips": unexpected,
            "scope": "This allowance never permits a skipped mapped scientific stress assertion."}


def stress_ledger(root: Path, out: Path, stages: list, role: str) -> None:
    """Record automated observations without filling any human review field."""
    with (root / "stress_results.csv").open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    suite_passed = any(s["stage"] == "all_tests" and s["passed"] for s in stages)
    mapped = set()
    if (out / "case_mapping.json").is_file():
        mapped = {item["case"] for item in json.loads((out / "case_mapping.json").read_text())
                  if item["mapped_assertions_passed"]}
    for row in rows:
        status = row.get("availability_status", "runnable")
        mode = row.get("mode", "manual")
        automated_passed = suite_passed and row.get("case") in mapped
        if status == "blocked_missing_real_input":
            executed = "blocked_missing_real_input"
            observation = "Original acquisition input is not supplied; no real-data PASS is asserted."
        elif mode == "automated":
            executed = "automated_checks_passed" if automated_passed else "not_completed"
            observation = ("Mapped automated assertions passed in the full current suite."
                           if automated_passed else "See all_tests.log and status.json.")
        elif mode == "automated_and_manual":
            executed = "automated_part_passed_manual_pending" if automated_passed else "manual_pending"
            observation = ("Synthetic assertions passed; separate human/real-acquisition judgment remains pending."
                           if automated_passed else "Human/real-acquisition judgment remains pending.")
        else:
            executed = "manual_pending"
            observation = "No human judgment has been entered by this automated runner."
        production_id = row.get("production_case_id", "")
        if production_id:
            path = out / "production_stress" / production_id / "observations.json"
            production = json.loads(path.read_text()) if path.is_file() else {}
            row["production_execution_status"] = production.get("execution_status", "not_completed")
            row["production_observations_path"] = str(path.relative_to(out))
            row["production_findings_count"] = str(len(production.get("findings", [])))
            observation += (f" Production execution: {row['production_execution_status']}; "
                            f"{row['production_findings_count']} recorded detector/QC observations. "
                            "Execution completion is not scientific acceptance.")
        row.update(execution_status=executed, observed_result=observation,
                   reviewer="", failure_classification="", execution_role=role)
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with (out / "stress_execution.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def verify(root: Path, out: Path, verify_only: bool = False,
           execution_role: str = "independent_verification") -> int:
    root = root.expanduser().resolve(strict=True)
    source = root / "source"
    out = reserve_output(root, out)
    state = {"schema_version": "tmem.portable_verification.v1", "status": "running",
             "started_at": datetime.now(timezone.utc).isoformat(), "execution_role": execution_role,
             "stages": [], "manual_review": "PENDING", "claire_independent_stress_complete": False,
             "full_pipeline_complete": False, "scientific_inference_ready": False}
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(source / "src"), str(source)])
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["MPLCONFIGDIR"] = str(out / "matplotlib")
    stages = state["stages"]
    write_json(out / "status.json", state)
    try:
        verified = verify_manifest(root)
        write_json(out / "source_snapshot.json", {
            "identity": "verified_portable_source_snapshot", "git_required": False,
            "manifest_sha256": verified["manifest_sha256"], "verified_files": verified["verified_files"],
            "ignored_generated_files": verified["ignored_generated_files"],
            "source_sha256": {name: sha for name, sha in verified["files"].items()
                              if name.startswith("source/")},
            "review_evidence_sha256": {name: sha for name, sha in verified["files"].items()
                                       if name.startswith(("review/", "fixtures/", "evidence/"))}})
        state["manifest_sha256"] = verified["manifest_sha256"]
        state["verified_files"] = verified["verified_files"]
        if verify_only:
            state["status"] = "hashes_verified_only"
            state["tests_executed"] = False
            print(f"PASS: {verified['verified_files']} immutable files match the manifest. Tests were not run.")
            return 0
        if not environment_record(out, source, env):
            raise RuntimeError("Cannot record complete pip environment; see environment_stderr.txt")
        template = review_root(root)
        commands = [
            ("all_tests", [sys.executable, "-m", "pytest", "tests", "-p", "no:cacheprovider", "-q",
                           "--junitxml=" + str(out / "all_tests.xml")], 0),
            ("synthetic", [sys.executable, "scripts/run_tmem_audit.py", "synthetic",
                           "--out", str(out / "synthetic")], 0),
            ("stress_examples", [sys.executable, "scripts/make_stress_examples.py",
                                 "--out", str(out / "stress_examples")], 0),
            ("production_stress", [sys.executable, "scripts/exercise_stress_pipeline.py",
                                   "--out", str(out / "production_stress")], 0),
            ("historical_ic", [sys.executable, "scripts/verify_historical_ic_fixtures.py",
                               "--evidence-root", str(root / "evidence"),
                               "--out", str(out / "historical_ic_fixture_checks.json")], 0),
            ("pending_export", [sys.executable, "scripts/export_reviewed_metrics.py",
                                "--curated", str(root / "fixtures"),
                                "--reviews", str(template / "manual_review_template.json"),
                                "--workspace", str(template),
                                "--config", str(source / "configs/tmem_review_v6.json"),
                                "--out", str(out / "pending_export_check")], 2),
        ]
        for name, command, expected in commands:
            code = run_stage(name, command, source, out, env, stages, expected)
            write_json(out / "status.json", state)
            if code != expected:
                raise RuntimeError(f"{name} returned {code}; expected {expected}. See {name}.log")
            if name == "all_tests":
                summary = test_summary(out / "all_tests.xml", out / "all_tests.log")
                counts = summary.get("junit_counts_including_subtests", {})
                if not counts.get("tests") or any(counts.get(key) for key in ["failures", "errors"]):
                    raise RuntimeError("Full suite must produce JUnit results with no failures or errors")
                optional = skip_policy(out / "all_tests.xml")
                write_json(out / "test_execution_policy.json", optional)
                state["optional_browser_skips"] = optional["allowed_optional_browser_skips"]
                if optional["unexpected_skips"]:
                    raise RuntimeError("Only the documented Node-unavailable UI check may be skipped")
                write_json(out / "case_mapping.json", mapped_case_results(root, out / "all_tests.xml"))
            if name == "synthetic":
                status_path = out / "synthetic/status.json"
                report = json.loads(status_path.read_text())
                if report.get("core_fixture") != "PASS" or report.get("reference_integrations") != "PASS":
                    raise RuntimeError("Synthetic stages did not report their numeric checks as PASS")
                for folder in ["01_preprocessing", "02_alignment", "03_phenotype", "05_stitching"]:
                    for filename in ["slides.html", "diagnostics.json", "stages.json"]:
                        if not (out / "synthetic" / folder / filename).is_file():
                            raise RuntimeError("Missing inspectable synthetic artifact: " + folder + "/" + filename)
            if name == "stress_examples":
                manifest = json.loads((out / "stress_examples/manifest.json").read_text())
                if not (out / "stress_examples/index.html").is_file() or not manifest.get("cases"):
                    raise RuntimeError("Synthetic stress examples were not emitted")
            if name == "historical_ic":
                report = json.loads((out / "historical_ic_fixture_checks.json").read_text())
                if (report.get("supplied_patch_arithmetic") != "PASS" or report.get("patches_checked") != 5
                        or report.get("physical_calibration_validated") is not False
                        or report.get("empirical_ic_adopted") is not False):
                    raise RuntimeError("Historical IC arithmetic evidence is incomplete or overstates its scope")
            if name == "production_stress":
                report = json.loads((out / "production_stress/status.json").read_text())
                if (report.get("cases_executed") != 9 or report.get("unexpected_software_errors") != 0
                        or report.get("execution_complete") is not True):
                    raise RuntimeError("Production stress responses did not complete for all nine declared cases")
                for case in report["cases"]:
                    record = json.loads((out / "production_stress" / case["observations"]).read_text())
                    if record.get("production_detector_result") != "COMPUTED":
                        raise RuntimeError("Production stress case lacks measured detector response")
            if name == "pending_export":
                blocked = out / "pending_export_check"
                if (blocked / "accepted_neuron_metrics.csv").exists() or not (blocked / "review_verdicts.json").is_file():
                    raise RuntimeError("Pending review did not produce the required blocked/no-CSV result")
                if json.loads((blocked / "review_verdicts.json").read_text()).get("accepted_ids"):
                    raise RuntimeError("Pending review incorrectly accepted a track")
        verify_manifest(root)
        state["status"] = "passed"
        state["tests_executed"] = True
        print("PASS: immutable snapshot, full test suite, synthetic stages and pending-review rejection verified.")
        print("Human identity/ROI/phenotype review and original-acquisition stitching remain pending.")
        return 0
    except Exception as error:
        state["status"] = "failed"
        state["error"] = f"{type(error).__name__}: {error}"
        print("FAIL: " + state["error"], file=sys.stderr)
        return 1
    finally:
        state["finished_at"] = datetime.now(timezone.utc).isoformat()
        state["test_summary"] = test_summary(out / "all_tests.xml", out / "all_tests.log")
        if not verify_only and "manifest_sha256" in state and (root / "stress_results.csv").is_file():
            stress_ledger(root, out, stages, execution_role)
        write_json(out / "status.json", state)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--handoff-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--verify-only", action="store_true",
                        help="Verify immutable input hashes only. Does not run scientific checks.")
    parser.add_argument("--execution-role", choices=["pre_handoff_verification", "independent_verification"],
                        default="independent_verification")
    args = parser.parse_args()
    try:
        return verify(args.handoff_root, args.out, args.verify_only, args.execution_role)
    except (ValueError, OSError) as error:
        parser.exit(1, "STOP: " + str(error) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
