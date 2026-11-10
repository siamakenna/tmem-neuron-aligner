#!/usr/bin/env python3
"""Run new unit/integration contracts first, then the checkout's actual tests.

No dependencies are installed, no sources are modified and no counts are guessed.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

from full_dataset import HERE, atomic_json, new_directory, source_binding


def run(repo, out, full=False):
    repo = Path(repo).resolve(strict=True)
    out = new_directory(out, repo)
    before = source_binding(repo)
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", MPLBACKEND="Agg", OMP_NUM_THREADS="1",
               OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1",
               PYTHONPATH=os.pathsep.join([str(repo / "src"), str(repo / "scripts"), str(HERE)]))
    commands = [("new_batch_contracts", [sys.executable, "-B", "-m", "unittest", "discover", "-s", str(HERE), "-p", "test_*.py", "-v"])]
    commands.append(("live_science_adapter", [sys.executable, "-B", str(HERE / "check_project_adapter.py"),
                                             "--repo", str(repo), "--out", str(out / "adapter")]))
    required = ["tests/test_preprocess.py", "tests/test_register.py", "tests/test_nd2_tools.py",
                "tests/test_registration_qc.py", "tests/test_preprocess_trace.py", "tests/test_registration_trace.py",
                "tests/audit_v1/test_visualization.py", "tests/audit_v1/test_pipeline_diagnostics.py", "tests/audit_v1/test_core.py"]
    missing = [p for p in required if not (repo / p).is_file()]
    if missing:
        raise ValueError("Current source test layout changed; inspect required checks: " + str(missing))
    targets = ["tests"] if full else required
    commands.append(("actual_project_tests", [sys.executable, "-B", "-m", "pytest", "-p", "no:napari", "-q", *targets,
                                              "--junitxml=" + str(out / "actual_project_tests.xml")]))
    steps = []
    for name, command in commands:
        print("TMEM_TEST_START=" + name, flush=True)
        with (out / (name + ".log")).open("w") as log:
            p = subprocess.run(command, cwd=repo, env=env, stdout=log, stderr=subprocess.STDOUT)
        step = {"name": name, "returncode": p.returncode, "log": name + ".log"}
        if name == "actual_project_tests" and (out / "actual_project_tests.xml").is_file():
            root = ET.parse(out / "actual_project_tests.xml").getroot()
            suites = [root] if root.tag == "testsuite" else root.findall("testsuite")
            step["junit"] = {key: sum(int(s.get(key, "0")) for s in suites)
                             for key in ["tests", "failures", "errors", "skipped"]}
        steps.append(step)
        atomic_json(out / "VERIFICATION_PRIVATE.json", {"status": "running", "source": before, "steps": steps})
        print("TMEM_TEST_END=" + name + ":" + str(p.returncode), flush=True)
        if p.returncode:
            print((out / (name + ".log")).read_text(errors="replace")[-12000:], flush=True)
            break
    unchanged = source_binding(repo) == before
    counts = steps[-1].get("junit", {})
    passed = len(steps) == 3 and all(s["returncode"] == 0 for s in steps) and unchanged and counts.get("tests", 0) > 0 and all(counts.get(k, 1) == 0 for k in ["failures", "errors", "skipped"])
    result = {"status": "passed" if passed else "requires_review", "source": before, "source_unchanged": unchanged,
              "steps": steps, "scope": "full existing suite" if full else "required affected science and diagnostic tests",
              "real_nd2_validation": False, "biological_validation": False}
    atomic_json(out / "VERIFICATION_PRIVATE.json", result)
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repo", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--full", action="store_true")
    args = p.parse_args()
    try:
        result = run(args.repo, args.out, args.full)
        print(json.dumps({k: v for k, v in result.items() if k != "source"}, indent=2))
        raise SystemExit(0 if result["status"] == "passed" else 2)
    except Exception as exc:
        print("STOP: " + str(exc), file=sys.stderr)
        raise SystemExit(2)
