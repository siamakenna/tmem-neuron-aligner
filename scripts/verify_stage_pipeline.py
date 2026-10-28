#!/usr/bin/env python3
"""Run unit then production integration checks; write an auditable result.

No dependency is installed, no missing test is silently skipped, and no
experimental track is approved by this verification. A compact known-truth IC
and registration example is saved only after the affected tests pass.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import inspect
import json
import os
from pathlib import Path
import subprocess
import sys
import traceback
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

UNIT = [
    "tests/audit_v1/test_stage_trace.py",
    "tests/audit_v1/test_visualization.py",
    "tests/audit_v1/test_parameters.py",
    "tests/audit_v1/test_pipeline_diagnostics.py::PipelineDiagnosticConfig",
    "tests/audit_v1/test_verification_runner.py",
]
INTEGRATION = [
    "tests/test_preprocess.py",
    "tests/test_preprocess_integration.py",
    "tests/test_preprocess_trace.py",
    "tests/test_register.py",
    "tests/test_registration_trace.py",
    "tests/audit_v1/test_segmentation_trace.py",
    "tests/audit_v1/test_pipeline_diagnostics.py::PipelineDiagnosticIntegration",
    "tests/audit_v1/test_reference.py",
    "tests/audit_v1/test_review_gate.py",
    "tests/audit_v1/test_review_export.py",
    "tests/audit_v1/test_render_binding.py",
]


def write_json(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    temporary.replace(path)


def code_hashes():
    paths = [p for directory in ["src", "scripts", "tests"]
             for p in (ROOT / directory).rglob("*.py")]
    paths.append(ROOT / "configs/tmem_stage_diagnostics.json")
    return {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(paths)}


def junit_counts(path):
    root = ET.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
    if not suites:
        raise ValueError("JUnit contains no test suite")
    return {key: sum(int(suite.get(key, "0")) for suite in suites)
            for key in ["tests", "failures", "errors", "skipped"]}


def run_phase(name, paths, out):
    for relative in paths:
        if not (ROOT / relative.split("::", 1)[0]).is_file():
            raise FileNotFoundError("Required verification test is missing: " + relative)
    report = out / (name + ".xml")
    command = [sys.executable, "-B", "-m", "pytest", "-p", "no:napari", "-q",
               *paths, "--junitxml=" + str(report)]
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1",
               PYTHONPATH=str(ROOT / "src") + os.pathsep + str(ROOT) + os.pathsep
               + os.environ.get("PYTHONPATH", ""))
    print("TMEM_VERIFICATION_PHASE=" + name, flush=True)
    with (out / (name + ".log")).open("w") as log:
        result = subprocess.run(command, cwd=ROOT, env=env, stdout=log,
                                stderr=subprocess.STDOUT, check=False)
    record = dict(name=name, command=command, returncode=result.returncode,
                  test_paths=paths, junit_file=report.name, log_file=name + ".log")
    record.update(junit_counts(report) if report.is_file() else
                  dict(tests=0, failures=0, errors=1, skipped=0))
    write_json(out / (name + "_result.json"), record)
    if (result.returncode != 0 or record["tests"] < 1
            or any(record[key] for key in ["failures", "errors", "skipped"])):
        raise RuntimeError(name + " did not pass every required test; inspect " + record["log_file"])
    return record


def known_truth_example(out):
    import numpy as np
    from scipy.ndimage import shift
    from tmem_align.audit_v1.fixtures import neuron_fixture
    from tmem_align.audit_v1.pipeline_diagnostics import trace_raw_pair
    from tmem_align.audit_v1.stage_trace import verify_trace

    truth, _, _ = neuron_fixture()
    displaced = np.stack([shift(plane, (4, -6), order=1, mode="constant", cval=0)
                          for plane in truth])
    field = np.broadcast_to(np.linspace(.6, 1.4, truth.shape[-1]), truth.shape[-2:]).copy()
    dark = 7.0
    raw_reference = np.rint(truth * field + dark).astype(np.uint16)
    raw_moving = np.rint(displaced * field + dark).astype(np.uint16)
    metadata = dict(evidence_type="SYNTHETIC_KNOWN_TRUTH_SOFTWARE_VERIFICATION",
                    experimental_data=False, physical_camera_calibration=False,
                    prescribed_displacement_yx_px=[4, -6], expected_shift_yx_px=[-4, 6])
    manifest = trace_raw_pair(raw_reference, raw_moving, out / "synthetic_IC_alignment",
        flatfield=field, flatfield_coordinate_system="detector", darkfield=dark,
        metadata=metadata)
    verify_trace(out / "synthetic_IC_alignment")
    actual_shift = manifest["summary"]["shift_dy_dx_px"]
    np.testing.assert_allclose(actual_shift, [-4, 6], atol=1)
    corrected_reference = next(r for r in manifest["stages"]
                               if r["stage"] == "preprocessed_reference_cyx")
    corrected = np.load(out / "synthetic_IC_alignment"
                        / corrected_reference["artifacts"]["numeric"]["path"], allow_pickle=False)
    np.testing.assert_allclose(corrected, truth, atol=2)
    return dict(evidence_type=metadata["evidence_type"], experimental_data=False,
                expected_shift_yx_px=[-4, 6], observed_shift_yx_px=list(actual_shift),
                max_IC_rounding_error_adu=float(np.max(np.abs(corrected - truth))),
                gallery="synthetic_IC_alignment/index.html", trace_verified=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    status = dict(status="running", unit_tests_passed=False, integration_tests_passed=False,
        tests=0, failures=0, errors=0, skipped=0, real_accepted_ids=[],
        scientific_inference_ready=False, microscopy_jobs_run_here=False,
        phases={}, source_file_sha256=code_hashes())
    write_json(out / "verification_status.json", status)
    try:
        packages = ["numpy", "scipy", "scikit-image", "tifffile", "pandas", "Pillow", "imageio", "matplotlib", "pytest"]
        status["environment"] = {name: importlib.metadata.version(name) for name in packages}
        from skimage.morphology import remove_small_objects
        if "max_size" not in inspect.signature(remove_small_objects).parameters:
            raise RuntimeError("The existing renderer requires scikit-image remove_small_objects(max_size=...).")
        status["phases"]["unit"] = run_phase("unit", UNIT, out)
        status["unit_tests_passed"] = True
        write_json(out / "verification_status.json", status)
        status["phases"]["integration"] = run_phase("integration", INTEGRATION, out)
        status["integration_tests_passed"] = True
        status["known_truth_example"] = known_truth_example(out)
        if code_hashes() != status["source_file_sha256"]:
            raise RuntimeError("Source files changed during verification")
        for key in ["tests", "failures", "errors", "skipped"]:
            status[key] = sum(phase[key] for phase in status["phases"].values())
        status["status"] = "passed"
        write_json(out / "verification_status.json", status)
        print("TMEM_UNIT_AND_INTEGRATION=passed", flush=True)
        print("TMEM_TESTS=" + str(status["tests"]), flush=True)
        return 0
    except Exception as error:
        status.update(status="failed", error=str(error), traceback=traceback.format_exc())
        status["errors"] = max(1, status["errors"])
        write_json(out / "verification_status.json", status)
        print("STOP: " + str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
