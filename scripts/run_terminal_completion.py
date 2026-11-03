#!/usr/bin/env python3
"""Run affected checks and optional original-ND2 diagnostics in ordinary Terminal.

Workflow graphics and a prepared (unsent) stress packet are attempted before
verification. Original ND2 inputs are read only, selected explicitly and never
substituted with registered TIFFs. Scientific blockers remain separate from
software test results. No package installation, publication or review occurs.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
import traceback
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
UNIT_TESTS = [
    "tests/audit_v1/test_terminal_completion.py",
    "tests/audit_v1/test_pipeline_flowcharts.py",
    "tests/audit_v1/test_claire_stress_packet.py",
    "tests/audit_v1/test_original_nd2_well.py",
    "tests/audit_v1/test_legacy_nd2_guards.py",
]
SUPPLEMENTAL_TESTS = ["tests/test_nd2_tools.py", "tests/audit_v1/test_core.py"]


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024**2), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    temporary.replace(path)


def code_hashes():
    return {path.relative_to(ROOT).as_posix(): sha(path)
            for directory in ["src", "scripts", "tests", "configs"]
            for path in sorted((ROOT / directory).rglob("*"))
            if path.is_file() and path.suffix in {".py", ".json", ".js", ".sh"}}


def environment():
    record = {"python": sys.version, "executable": sys.executable, "packages": {}}
    for name in ["numpy", "pandas", "scipy", "scikit-image", "tifffile", "nd2",
                 "Pillow", "imageio", "matplotlib", "pytest", "pytest-subtests"]:
        try:
            record["packages"][name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            record["packages"][name] = None
    return record


def junit_counts(path):
    root = ET.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
    if not suites:
        raise ValueError("JUnit contains no direct test suites")
    counts = {key: sum(int(suite.get(key, "0")) for suite in suites)
              for key in ["tests", "failures", "errors", "skipped"]}
    if counts["tests"] < 1 or any(counts[k] for k in ["failures", "errors", "skipped"]):
        raise ValueError("Required software check had zero tests, failures, errors or skips: " + str(counts))
    return counts


def require_new_output(path, raw_root=None):
    out = Path(path).expanduser().resolve()
    if out.is_relative_to(ROOT) or ROOT.is_relative_to(out):
        raise ValueError("Private output must be outside the repository and its ancestors")
    if raw_root:
        raw = Path(raw_root).expanduser().resolve(strict=True)
        if not raw.is_dir():
            raise ValueError("--raw-root must be an existing directory")
        if out.is_relative_to(raw) or raw.is_relative_to(out):
            raise ValueError("Private output must not overlap the original ND2 root")
    if out.exists():
        raise ValueError("Require a new output directory; preserve previous run receipts")
    out.mkdir(parents=True)
    return out


class Runner:
    def __init__(self, out, timeout):
        self.out, self.timeout = Path(out), timeout
        self.steps = {}
        (self.out / "logs").mkdir()

    def step(self, name, command):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", name):
            raise ValueError("Invalid step name")
        record = {"status": "running", "command": list(map(str, command)),
                  "log": "logs/" + name + ".log"}
        self.steps[name] = record
        write_json(self.out / "STEP_STATUS.json", self.steps)
        started = time.monotonic()
        print("TMEM_STEP_START=" + name, flush=True)
        env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(ROOT / "src"), str(ROOT / "scripts"), str(ROOT)]),
                   PYTHONDONTWRITEBYTECODE="1", MPLBACKEND="Agg", OMP_NUM_THREADS="1",
                   OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1", NUMEXPR_NUM_THREADS="1")
        process = None
        try:
            with (self.out / record["log"]).open("w") as log:
                process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=log,
                    stderr=subprocess.STDOUT, start_new_session=os.name == "posix")
                while True:
                    remaining = self.timeout - (time.monotonic() - started)
                    if remaining <= 0:
                        raise subprocess.TimeoutExpired(command, self.timeout)
                    try:
                        code = process.wait(timeout=min(15, remaining))
                        break
                    except subprocess.TimeoutExpired:
                        print("TMEM_STEP_RUNNING=" + name + " elapsed_seconds="
                              + str(int(time.monotonic() - started)), flush=True)
            record.update(status="passed" if code == 0 else "failed", returncode=code)
        except BaseException as error:
            if process is not None and process.poll() is None:
                if os.name == "posix":
                    os.killpg(process.pid, signal.SIGKILL)
                else:
                    process.kill()
                process.wait()
            record.update(status="timed_out" if isinstance(error, subprocess.TimeoutExpired) else "failed",
                          error=type(error).__name__ + ": " + str(error))
            if isinstance(error, KeyboardInterrupt):
                raise
        finally:
            record["seconds"] = round(time.monotonic() - started, 3)
            self.steps[name] = record
            write_json(self.out / "STEP_STATUS.json", self.steps)
            print("TMEM_STEP_END=" + name + ":" + record["status"], flush=True)
        return record


def py(script, *args):
    return [sys.executable, "-B", str(ROOT / "scripts" / script), *map(str, args)]


def succeeded(record):
    return record.get("status") == "passed" and record.get("returncode") == 0


def graphics_verified(directory):
    for stem in ["original_ND2_to_well", "segmentation_tracking"]:
        ET.parse(Path(directory) / (stem + ".svg"))
        with (Path(directory) / (stem + ".png")).open("rb") as stream:
            if stream.read(8) != b"\x89PNG\r\n\x1a\n":
                raise ValueError("Missing actual rendered PNG: " + stem)


def packet_verified(path):
    with zipfile.ZipFile(path) as archive:
        if archive.testzip() is not None:
            raise ValueError("Corrupt prepared stress ZIP")
        provenance = json.loads(archive.read("PROVENANCE.json"))
        if provenance.get("delivery_status") != "prepared_not_sent":
            raise ValueError("Stress packet must remain prepared_not_sent")


def run_pytest(runner, name, paths):
    if any(not (ROOT / p.split("::", 1)[0]).is_file() for p in paths):
        raise FileNotFoundError("A required affected test file is missing")
    report = runner.out / (name + ".xml")
    command = [sys.executable, "-B", "-m", "pytest", "-p", "no:napari", "-q", *paths,
               "--junitxml=" + str(report)]
    record = runner.step(name, command)
    if not succeeded(record):
        raise RuntimeError(name + " failed; inspect " + record["log"])
    return dict(command=record["command"], log=record["log"], junit=report.name, **junit_counts(report))


def check_selection(header, supplied):
    sizes = header["sizes"]
    if set(sizes) - set("PTZCYX") or any(axis not in sizes for axis in "CYX"):
        raise ValueError("Require declared ND2 C/Y/X axes and only optional P/T/Z axes")
    if sizes["C"] != 3:
        raise ValueError("Require three explicitly named fluorescence planes")
    if set(supplied) - {"position", "time", "z"}:
        raise ValueError("Only explicit position/time/z selection is supported")
    indices = {}
    for axis, name in [("P", "position"), ("T", "time"), ("Z", "z")]:
        value = supplied.get(name)
        if value is not None and (type(value) is not int or value < 0):
            raise ValueError(name + " must be a nonnegative integer")
        if axis not in sizes:
            if value not in {None, 0}:
                raise ValueError("Selection references absent " + axis + " axis")
            indices[name] = None
        else:
            if value is None:
                if sizes[axis] != 1:
                    raise ValueError("Explicit " + name + " required; do not silently use index zero")
                value = 0
            if value >= sizes[axis]:
                raise ValueError("Selection outside ND2 " + axis + " axis")
            indices[name] = value
    names = list(header.get("channel_names", []))
    if len(names) != 3 or any(not re.search(r"(?<!\d)" + wavelength + r"(?!\d)", names[i])
                             for i, wavelength in enumerate(["405", "561", "488"])):
        raise ValueError("Current pair pipeline requires metadata-named channel order 405/561/488; resolve mapping explicitly")
    return indices


def extract_field(path, destination, selection, max_read_bytes):
    """Roundtrip one explicitly selected CYX field, including original-file hashes."""
    import numpy as np
    import tifffile
    from tmem_align.nd2_tools import _require_nd2, extract_nd2_selection, inspect_nd2
    source = Path(path).expanduser().resolve(strict=True)
    if source.suffix.lower() != ".nd2" or not source.is_file():
        raise ValueError("Require an original .nd2 file")
    before = sha(source)
    header = inspect_nd2(source)
    indices = check_selection(header, selection)
    extract_nd2_selection(source, destination, **indices,
                          max_read_bytes=max_read_bytes, max_output_bytes=max_read_bytes)
    with tifffile.TiffFile(destination) as image:
        if len(image.series) != 1 or image.series[0].axes != "CYX":
            raise ValueError("Extracted TIFF did not preserve explicit CYX")
        output = image.asarray()
    nd2 = _require_nd2()
    with nd2.ND2File(source) as image:
        if {str(k): int(v) for k, v in image.sizes.items()} != header["sizes"]:
            raise ValueError("ND2 axes changed between extraction and pixel comparison")
        requested = {"P": indices["position"], "T": indices["time"], "Z": indices["z"]}
        selector = tuple(requested[axis] if axis in requested else slice(None) for axis in image.sizes)
        selected = image.to_dask()[selector]
        if int(np.prod(selected.shape)) * np.dtype(selected.dtype).itemsize > max_read_bytes:
            raise ValueError("Comparison read exceeds the declared memory limit")
        expected = np.asarray(selected.compute())
    if output.dtype != expected.dtype or output.shape != expected.shape or not np.array_equal(output, expected):
        raise ValueError("Original ND2 pixel roundtrip differs in shape, dtype or values")
    if sha(source) != before:
        raise ValueError("Original ND2 changed while reading")
    return output, dict(path=str(source), sha256=before, header=header, indices=indices,
        extraction_path=str(destination), extraction_sha256=sha(destination),
        array_shape=list(output.shape), array_dtype=str(output.dtype), pixel_equality_verified=True,
        well_coverage_verified=False, optical_channel_identity_verified=False)


def run_pair(args):
    sys.path.insert(0, str(ROOT / "src"))
    sys.path.insert(0, str(ROOT / "scripts"))
    import numpy as np
    from tmem_align.audit_v1.pipeline_diagnostics import trace_raw_pair, file_record, load_config
    from tmem_align.audit_v1.stage_trace import verify_trace
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=False)
    selections = json.loads(args.selection_json.read_text()) if args.selection_json else {}
    if set(selections) - {"reference", "moving"} or any(not isinstance(v, dict) for v in selections.values()):
        raise ValueError("Selection JSON requires reference/moving objects")
    ref, ref_record = extract_field(args.reference_nd2, out / "reference.ome.tif",
                                   selections.get("reference", {}), args.max_read_bytes)
    mov, mov_record = extract_field(args.moving_nd2, out / "moving.ome.tif",
                                   selections.get("moving", {}), args.max_read_bytes)
    binding = dict(mode="original_ND2_field_pair", inputs=[ref_record, mov_record],
        physical_channel_identity_verified=False, well_coverage_verified=False,
        historical_correction_state_verified=False)
    controls = [file_record(p) for p in [args.selection_json, args.config] if p is not None]
    binding["configuration_inputs"] = controls
    corrections = []
    flatfield = None
    if args.flatfield:
        if args.flatfield.suffix.lower() != ".npy":
            raise ValueError("Flatfield must be a pickle-free matching detector-coordinate NPY")
        if not args.flatfield_provenance:
            raise ValueError("Supplying a flatfield requires --flatfield-provenance JSON")
        corrections = [file_record(args.flatfield), file_record(args.flatfield_provenance)]
        provenance = json.loads(args.flatfield_provenance.read_text())
        if (provenance.get("coordinate_system") != "detector" or not provenance.get("source")
                or provenance.get("flatfield_sha256") != corrections[0]["sha256"]):
            raise ValueError("Flatfield provenance requires detector coordinates, source and matching flatfield_sha256")
        flatfield = np.load(args.flatfield, allow_pickle=False, mmap_mode="r")
        binding["flatfield_provenance"] = provenance
    binding["correction_inputs"] = corrections
    write_json(out / "ORIGINAL_ND2_BINDINGS.json", binding)
    manifest = trace_raw_pair(ref, mov, out / "trace", flatfield=flatfield,
        flatfield_coordinate_system="detector" if flatfield is not None else None,
        darkfield=args.darkfield, background_radius=args.background_radius,
        config=load_config(args.config), metadata=binding)
    try:
        for record in [ref_record, mov_record, *corrections, *controls]:
            if sha(record["path"]) != record["sha256"]:
                raise ValueError("An original or correction input changed during processing")
    except Exception as error:
        write_json(out / "trace" / "SOURCE_CHANGED.json", {"error": str(error), "scientific_inference_ready": False})
        raise
    verify_trace(out / "trace")
    report = dict(status="original_ND2_field_pair_executed", source_bindings=binding,
        executed_summary=manifest["summary"], original_nd2_used=True,
        original_pixel_roundtrip_verified=True, whole_well_validation_granted=False,
        real_accepted_ids=[], scientific_inference_ready=False)
    write_json(out / "FIELD_PAIR_STATUS.json", report)
    return report


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", type=Path, required=True, help="New private output directory outside the repository")
    p.add_argument("--raw-root", type=Path, help="Original root for output-overlap protection; no automatic rescan")
    p.add_argument("--reference-nd2", type=Path)
    p.add_argument("--moving-nd2", type=Path)
    p.add_argument("--selection-json", type=Path, help="Explicit reference/moving position/time/z objects for non-singleton axes")
    p.add_argument("--well-manifest", type=Path, action="append", default=[])
    p.add_argument("--existing-trace", type=Path, action="append", default=[],
                   help="Reuse a prior verified StageTrace for image flowcharts; no benchmark rerun")
    p.add_argument("--flatfield", type=Path)
    p.add_argument("--flatfield-provenance", type=Path)
    p.add_argument("--darkfield", type=float, help="Declared scalar detector offset, not an inferred physical calibration")
    p.add_argument("--background-radius", type=int)
    p.add_argument("--config", type=Path)
    p.add_argument("--max-read-bytes", type=int, default=256 * 1024**2)
    p.add_argument("--step-timeout", type=int, default=1800)
    p.add_argument("--field-worker", action="store_true", help=argparse.SUPPRESS)
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    if args.step_timeout < 1 or args.max_read_bytes < 1:
        raise ValueError("Timeout and memory limit must be positive")
    if bool(args.reference_nd2) != bool(args.moving_nd2):
        raise ValueError("Supply both --reference-nd2 and --moving-nd2")
    if (args.reference_nd2 and args.reference_nd2.expanduser().resolve()
            == args.moving_nd2.expanduser().resolve()):
        raise ValueError("Reference and moving must be distinct original ND2 files")
    if args.field_worker:
        if not args.reference_nd2:
            raise ValueError("Field worker requires both original ND2 inputs")
        run_pair(args)
        return 0
    for source in [args.reference_nd2, args.moving_nd2]:
        if source and (not source.expanduser().is_file() or source.suffix.lower() != ".nd2"):
            raise ValueError("Original field inputs must be existing ND2 files")
    out = require_new_output(args.out, args.raw_root)
    if any(source and source.expanduser().resolve().is_relative_to(out) for source in [args.reference_nd2, args.moving_nd2]):
        raise ValueError("An input cannot be inside the new output directory")
    runner = Runner(out, args.step_timeout)
    status = dict(schema_version="tmem.terminal_completion.v1", status="running",
        software_checks_passed=False, source_unchanged=False, workflow_graphics_generated=False,
        claire_stress_packet_prepared=False, claire_delivery_status="not_sent",
        original_nd2_used=False, whole_well_validation_granted=False,
        scientific_inference_ready=False, real_accepted_ids=[],
        code_file_sha256=code_hashes(), environment=environment(), phases={}, blockers=[])
    write_json(out / "RUN_STATUS.json", status)
    try:
        for name, command in [
            ("workflow_graphics", py("render_pipeline_flowcharts.py", "--raster", "--out", out / "flowcharts")),
            ("claire_stress_packet", py("package_claire_stress_tests.py", "--out", out / "Claire_stress_tests.zip")),
        ]:
            record = runner.step(name, command)
            try:
                if not succeeded(record):
                    raise RuntimeError(name + " failed; inspect " + record["log"])
                if name == "workflow_graphics":
                    graphics_verified(out / "flowcharts")
                    status["workflow_graphics_generated"] = True
                else:
                    packet_verified(out / "Claire_stress_tests.zip")
                    status["claire_stress_packet_prepared"] = True
            except Exception as error:
                status["blockers"].append(str(error))
            write_json(out / "RUN_STATUS.json", status)
        status["phases"]["new_unit_controls"] = run_pytest(runner, "new_unit_controls", UNIT_TESTS)
        record = runner.step("production_unit_then_integration", py("verify_stage_pipeline.py", "--out", out / "production_verification"))
        if not succeeded(record):
            raise RuntimeError("Production unit/integration verification failed; inspect " + record["log"])
        production = json.loads((out / "production_verification/verification_status.json").read_text())
        if (production.get("status") != "passed" or production.get("unit_tests_passed") is not True
                or production.get("integration_tests_passed") is not True):
            raise ValueError("Production verification did not certify its actual required checks")
        status["phases"]["production_unit_then_integration"] = production
        status["phases"]["nd2_and_stitching_controls"] = run_pytest(runner, "nd2_and_stitching_controls", SUPPLEMENTAL_TESTS)
        status["software_checks_passed"] = True
        write_json(out / "RUN_STATUS.json", status)
        if args.reference_nd2:
            command = py("run_terminal_completion.py", "--field-worker", "--out", out / "original_field_pair",
                "--reference-nd2", args.reference_nd2.expanduser().resolve(),
                "--moving-nd2", args.moving_nd2.expanduser().resolve(), "--max-read-bytes", args.max_read_bytes)
            for name in ["selection_json", "flatfield", "flatfield_provenance", "darkfield", "background_radius", "config"]:
                value = getattr(args, name)
                if value is not None:
                    command += ["--" + name.replace("_", "-"), str(value.expanduser().resolve() if isinstance(value, Path) else value)]
            record = runner.step("original_ND2_field_pair", command)
            if succeeded(record):
                field = json.loads((out / "original_field_pair/FIELD_PAIR_STATUS.json").read_text())
                if field.get("original_nd2_used") is not True or field.get("original_pixel_roundtrip_verified") is not True:
                    raise ValueError("Field worker did not establish original ND2 extraction fidelity")
                status["original_nd2_used"] = True
                status["field_pair"] = field
                status["image_flowchart_status"] = runner.step("original_field_flowcharts",
                    py("render_pipeline_flowcharts.py", "--trace", out / "original_field_pair/trace", "--raster", "--out", out / "original_field_flowcharts"))
                if not succeeded(status["image_flowchart_status"]):
                    status["blockers"].append("Original-field image flowcharts failed; inspect logs")
            else:
                status["blockers"].append("Original ND2 field pair failed; inspect " + record["log"])
        else:
            status["blockers"].append("No explicit original ND2 field pair supplied")
        status["existing_trace_graphics"] = []
        for index, trace in enumerate(args.existing_trace):
            record = runner.step("existing_trace_graphics_" + str(index),
                py("render_pipeline_flowcharts.py", "--trace", trace.expanduser().resolve(), "--raster",
                   "--out", out / ("existing_trace_graphics_" + str(index))))
            status["existing_trace_graphics"].append(record)
            if not succeeded(record):
                status["blockers"].append("Supplied existing trace could not be verified/rendered; inspect " + record["log"])
        status["well_manifest_runs"] = []
        for index, manifest in enumerate(args.well_manifest):
            record = runner.step("original_well_" + str(index), py("trace_original_nd2_well.py", "--manifest", manifest.expanduser().resolve(),
                "--out", out / ("original_well_" + str(index))))
            status["well_manifest_runs"].append(record)
            if succeeded(record):
                well_result = json.loads((out / ("original_well_" + str(index)) / "RUN_STATUS.json").read_text())
                if (well_result.get("original_nd2_used") is not True or well_result.get("whole_well_visits") != 9
                        or well_result.get("status") != "original_nd2_ic_assembly_registration_executed"):
                    raise ValueError("Well worker did not establish its required original ND2 execution")
                record["well_execution_receipt"] = well_result
                status["original_nd2_used"] = True
            else:
                status["blockers"].append("Original ND2 well manifest did not execute; inspect " + record["log"])
        status["blockers"].append("Whole-well coverage, channel optics, matching IC provenance and independent identity/ROI evidence remain separate validation requirements")
        if code_hashes() != status["code_file_sha256"]:
            status["software_checks_passed"] = False
            raise ValueError("Source files changed during this run; results cannot certify the final source")
        status["source_unchanged"] = True
        status["status"] = "software_passed_scientific_validation_pending"
        return 2
    except KeyboardInterrupt:
        status.update(status="interrupted", software_checks_passed=False)
        return 130
    except Exception as error:
        status.update(status="software_failed", error=str(error), traceback=traceback.format_exc())
        return 1
    finally:
        write_json(out / "RUN_STATUS.json", status)
        text = ["# TMEM Terminal run", "", "Status: " + status["status"],
                "Software checks passed: " + str(status["software_checks_passed"]),
                "Original ND2 used: " + str(status["original_nd2_used"]),
                "Whole-well / biological validation granted: false", "", "## Remaining evidence", ""]
        text += ["- " + b for b in status["blockers"]]
        if status.get("error"):
            text += ["", "Software failure: " + status["error"]]
        (out / "RUN_SUMMARY.md").write_text("\n".join(text) + "\n")
        print("TMEM_TERMINAL_STATUS=" + status["status"], flush=True)
        print("TMEM_TERMINAL_RESULTS=" + str(out), flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
