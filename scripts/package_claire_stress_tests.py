#!/usr/bin/env python3
"""Create a compact independent stress-test request; never approve or send it."""
from __future__ import annotations

import argparse
import ast
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE_FILES = (
    "src/tmem_align/audit_v1/actual_fov_figures.py",
    "scripts/render_actual_fov_figures.py",
    "tests/audit_v1/test_actual_fov_figures.py",
    "configs/tmem_stage_diagnostics.json",
    "scripts/make_stress_examples.py",
    "scripts/exercise_stress_pipeline.py",
    "scripts/verify_stage_pipeline.py",
    "scripts/inventory_acquisition_sources.py",
    "scripts/assemble_tmem_well.py",
    "scripts/trace_original_nd2_well.py",
    "scripts/run_260213_longitudinal_pilot.py",
    "scripts/run_260213_all_wells_batch.py",
    "src/tmem_align/audit_v1/nd2_contracts.py",
    "scripts/render_pipeline_flowcharts.py",
    "scripts/package_claire_stress_tests.py",
    "src/tmem_align/audit_v1/stress_fixtures.py",
    "src/tmem_align/audit_v1/parameters.py",
    "src/tmem_align/audit_v1/stage_trace.py",
    "src/tmem_align/audit_v1/visualization.py",
    "src/tmem_align/audit_v1/acquisition_inventory.py",
    "src/tmem_align/audit_v1/stitching.py",
    "src/tmem_align/nd2_tools.py",
    "tests/audit_v1/test_stress_variants.py",
    "tests/audit_v1/test_production_stress.py",
    "tests/audit_v1/test_stress_stage_guards.py",
    "tests/audit_v1/test_reference.py",
    "tests/audit_v1/test_core.py",
    "tests/audit_v1/test_parameters.py",
    "tests/audit_v1/test_stage_trace.py",
    "tests/audit_v1/test_visualization.py",
    "tests/audit_v1/test_segmentation_trace.py",
    "tests/test_preprocess_trace.py",
    "tests/test_registration_trace.py",
    "tests/audit_v1/test_acquisition_inventory.py",
    "tests/test_nd2_tools.py",
    "tests/audit_v1/test_legacy_nd2_guards.py",
    "tests/audit_v1/test_original_nd2_well.py",
)
REAL_CASES = (
    ("original_nd2_ic", "Read original ND2 detector planes; verify channel/optics mapping, correction state, matching detector flat/dark provenance, exact pre/post arrays and source hashes. A missing field remains blocked."),
    ("well_stitch_overlap", "Establish the complete acquisition site roster and stage-to-pixel transform, including any off-axis camera component; assemble all FOVs per well/visit and independently inspect seams, boundaries and a neuron crossing an overlap. P=1 does not prove whole-well coverage."),
    ("well_longitudinal_identity", "Review all nine visits of original-source-bound 488 identity and ROI ownership before 561 outcomes."),
)


def git_context(root):
    """Report Git identity only when this directory is the actual checkout root."""
    try:
        actual = subprocess.run(["git", "-C", str(root), "rev-parse", "--show-toplevel"],
            check=True, capture_output=True, text=True).stdout.strip()
        if Path(actual).resolve() != Path(root).resolve():
            return dict(commit=None, worktree_modified=None, git_identity_available=False)
        commit = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
            check=True, capture_output=True, text=True).stdout.strip()
        status = subprocess.run(["git", "-C", str(root), "status", "--porcelain"],
            check=True, capture_output=True, text=True).stdout
        return dict(commit=commit, worktree_modified=bool(status), git_identity_available=True)
    except (OSError, subprocess.CalledProcessError):
        return dict(commit=None, worktree_modified=None, git_identity_available=False)


def encoded(value):
    return (json.dumps(value, indent=2, allow_nan=False) + "\n").encode()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def source_path(root, name):
    relative = PurePosixPath(name)
    if (relative.is_absolute() or ".." in relative.parts or "\\" in name
            or relative.as_posix() != name):
        raise ValueError("Unsafe source reference")
    path = Path(root) / name
    current = path
    while current != Path(root):
        if current.is_symlink():
            raise ValueError("Linked source reference")
        current = current.parent
    if not path.is_file() or path.stat().st_size > 512 * 1024:
        raise ValueError("Missing or oversized compact source: " + name)
    return path


def fixture_constants(path):
    result = {}
    for node in ast.parse(Path(path).read_text()).body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in {"CASE_IDS", "DEFAULT_SEED"}:
                    result[target.id] = ast.literal_eval(node.value)
    cases, seed = result.get("CASE_IDS"), result.get("DEFAULT_SEED")
    if (not isinstance(cases, tuple) or not cases or len(cases) != len(set(cases))
            or any(not isinstance(case, str) for case in cases) or type(seed) is not int):
        raise ValueError("Synthetic fixture declarations are unavailable or ambiguous")
    return cases, seed


def verified_run_summary(path, root):
    """Include fresh, source-matched software proof, not unrestricted result files."""
    path = Path(path)
    if path.is_dir():
        path = path / "verification_status.json"
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 256 * 1024:
        raise ValueError("Require a small, regular verification_status.json")
    original = path.read_bytes()
    result = json.loads(original)
    counts = ("tests", "failures", "errors", "skipped")
    if (result.get("status") != "passed" or result.get("unit_tests_passed") is not True
            or result.get("integration_tests_passed") is not True
            or any(type(result.get(key)) is not int for key in counts)
            or result["tests"] < 1 or any(result[key] for key in counts[1:])):
        raise ValueError("Supplied verification did not pass all nonempty phases without skips")
    phases = result.get("phases", {})
    if set(phases) != {"unit", "integration"}:
        raise ValueError("Both verification phases are required")
    for phase in phases.values():
        if (phase.get("returncode") != 0 or type(phase.get("tests")) is not int
                or phase["tests"] < 1 or any(phase.get(key) != 0 for key in counts[1:])):
            raise ValueError("Verification phase failed or is empty")
    bindings = result.get("source_file_sha256")
    if not isinstance(bindings, dict) or not bindings:
        raise ValueError("Verification lacks source bindings")
    for name, expected in bindings.items():
        if sha(source_path(root, name).read_bytes()) != expected:
            raise ValueError("Verification source no longer matches: " + name)
    return dict(status="verified_software_checks_passed", verification_status_sha256=sha(original),
                **{key: result[key] for key in counts},
                phases={name: {key: phase[key] for key in counts} for name, phase in phases.items()},
                source_bindings_verified=len(bindings),
                biological_acceptance=False, original_nd2_execution_established=False)


def package(out, *, run_results=None, root=ROOT):
    root, out = Path(root).resolve(), Path(out)
    if out.exists() or out.is_symlink():
        raise FileExistsError("Choose a new packet path; existing packets are preserved")
    out.parent.mkdir(parents=True, exist_ok=True)
    content = {"source_context/" + name: source_path(root, name).read_bytes() for name in SOURCE_FILES}
    cases, seed = fixture_constants(root / "src/tmem_align/audit_v1/stress_fixtures.py")
    configuration = json.loads((root / "configs/tmem_stage_diagnostics.json").read_text())
    content["DECLARED_PARAMETERS.json"] = encoded({"configuration": configuration,
        "source": "source_context/configs/tmem_stage_diagnostics.json", "fixture_seed": seed,
        "scope": "Declared diagnostic settings. Run outputs must record actual source-derived parameters; no new setting is adopted."})
    case_plan = [dict(case_id=case, evidence_type="SYNTHETIC_KNOWN_TRUTH_CHALLENGE",
        status="not_executed_by_packet_creation", original_nd2=False,
        review="Compare measured production response with fixture truth; retain misses as findings.") for case in cases]
    case_plan += [dict(case_id=case, evidence_type="ORIGINAL_ND2_REQUIRED", status="blocked_pending_original_source_run",
        original_nd2=True, review=review) for case, review in REAL_CASES]
    content["STRESS_CASE_PLAN.json"] = encoded(case_plan)
    content["RESULTS.template.json"] = encoded(dict(schema_version="tmem.independent_stress_review.v1",
        reviewer=None, reviewed_commit=None, status="not_run", unit_tests=None, integration_tests=None,
        original_nd2_inputs_verified=False, real_nd2_checks={case: "not_run" for case, _ in REAL_CASES},
        cases=[dict(case_id=case, execution="not_run", findings=[], evidence_paths=[]) for case in cases],
        limitations=[], real_accepted_ids=[], scientific_inference_ready=False))
    content["RUN_STRESS.sh"] = ('''#!/usr/bin/env bash
set -euo pipefail
tmem_repo="${TMEM_REPO:-$PWD}"
tmem_python="${TMEM_PYTHON:-python3}"
test -f "$tmem_repo/scripts/verify_stage_pipeline.py"
test -f "$tmem_repo/scripts/exercise_stress_pipeline.py"
tmem_repo="$(cd "$tmem_repo" && pwd)"
tmem_packet="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
"$tmem_python" - "$tmem_repo" "$tmem_packet/PROVENANCE.json" <<'SOURCE_CHECK'
import hashlib,json,re,sys
from pathlib import Path,PurePosixPath
root=Path(sys.argv[1]).resolve()
bindings=json.loads(Path(sys.argv[2]).read_text())["source_sha256"]
if not isinstance(bindings,dict) or not bindings:
    raise SystemExit("STOP: stress packet has no source bindings")
for name,expected in bindings.items():
    relative=PurePosixPath(name)
    if relative.is_absolute() or ".." in relative.parts or "\\\\" in name or relative.as_posix()!=name:
        raise SystemExit("STOP: unsafe stress source binding")
    path=root/name
    if not re.fullmatch(r"[0-9a-f]{64}",str(expected)) or not path.is_file():
        raise SystemExit("STOP: missing stress source: "+name)
    if any(part.is_symlink() for part in [path,*path.parents] if part!=root and root in part.parents):
        raise SystemExit("STOP: linked stress source: "+name)
    if hashlib.sha256(path.read_bytes()).hexdigest()!=expected:
        raise SystemExit("STOP: stress source differs from packet: "+name)
print("Stress packet source bindings verified:",len(bindings))
SOURCE_CHECK
tmem_run="$(mktemp -d "${TMPDIR:-/tmp}/tmem_claire_stress_XXXXXXXX")"
export PYTHONPATH="$tmem_repo/src:$tmem_repo/scripts${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONDONTWRITEBYTECODE=1
cd "$tmem_repo"
printf 'Results directory: %s\\n' "$tmem_run"
# This command runs required unit checks before production integrations.
"$tmem_python" scripts/verify_stage_pipeline.py --out "$tmem_run/verification"
"$tmem_python" -m pytest -p no:napari -q tests/audit_v1/test_stress_variants.py tests/audit_v1/test_production_stress.py tests/audit_v1/test_stress_stage_guards.py tests/audit_v1/test_legacy_nd2_guards.py tests/audit_v1/test_original_nd2_well.py tests/audit_v1/test_actual_fov_figures.py --junitxml="$tmem_run/stress_tests.xml"
"$tmem_python" scripts/make_stress_examples.py --out "$tmem_run/synthetic_truth"
"$tmem_python" scripts/exercise_stress_pipeline.py --out "$tmem_run/production_responses"
printf 'Synthetic software stress execution finished. Original-ND2 and independent image review remain required.\\nResults: %s\\n' "$tmem_run"
''').encode()
    content["README.md"] = ("# TMEM106B independent stress-test request for Claire\n\n"
        "This compact packet is prepared for independent testing; it has not been sent and does not identify an authenticated recipient. "
        "Packet creation executes no microscopy algorithms and grants no review approval.\n\n"
        "## Run in the current repository\n\n"
        "Use a Python 3.11+ environment with the repository's declared dependencies. The included source_context files are review copies, not a complete standalone repository. "
        "From the full checkout run `TMEM_REPO=\"$PWD\" TMEM_PYTHON=python3 bash /path/to/extracted/packet/RUN_STRESS.sh`. "
        "The launcher checks the current checkout against every included source binding before executing tests; a mismatch stops the run. Retain the printed result directory. The verification runner performs unit checks before integrations.\n\n"
        "## Independent review\n\n"
        "Inspect the saved synthetic input/truth previews and actual production responses. Record detector misses, wrong matches, unstable masks, contamination and exposure sensitivity as findings; do not tune them away or equate successful execution with correctness. "
        "Vary one predeclared 488 parameter at a time; keep 561 outcomes independent. A higher matching score or smaller ROI does not prove identity or ownership. "
        "Compare fixed-LUT before/during/after images and numeric arrays. LUT-box proposals are display-only until explicitly reviewed.\n\n"
        "## Required original-source checks\n\n"
        "The real-source checks require original ND2 files, the complete well/FOV/visit roster, reviewed stage-to-pixel coordinates including any off-axis camera component, authoritative channel/optics mapping, and matching detector-coordinate IC fields when applying correction. "
        "A single CYX scene with P=1 is a field observation until acquisition coverage is established independently; do not count it as a complete well. "
        "Check IC before/after on actual decoded detector planes, all-FOV well stitching including overlap seams and a boundary-crossing neuron, and nine-visit identity/ROI continuity. "
        "The packet contains no original ND2 images, and synthetic challenges cannot complete these checks. "
        "Mark missing inputs or unavailable image review as blocked. Preserve original all-nine-visit gates; never shrink away a failure or force an acceptance.\n\n"
        "Complete RESULTS.template.json with the actual commit, execution results, evidence paths and independent observations. "
        "No track is accepted and no biological discovery follows from this packet or its software checks.\n").encode()
    if run_results is not None:
        content["VERIFIED_SOFTWARE_RESULT.json"] = encoded(verified_run_summary(run_results, root))
    provenance = dict(schema_version="tmem.claire_stress_packet.v1",
        created_utc=datetime.now(timezone.utc).isoformat(), delivery_status="prepared_not_sent",
        recipient_identity="unresolved", packet_creation_runs_microscopy=False,
        synthetic_case_count=len(cases), original_nd2_files_included=False,
        provided_verification="source_matched_software_result" if run_results else "none_not_run",
        source_sha256={name: sha(content["source_context/" + name]) for name in SOURCE_FILES},
        source_git=git_context(root),
        real_accepted_ids=[], scientific_inference_ready=False)
    content["PROVENANCE.json"] = encoded(provenance)
    content["MANIFEST.json"] = encoded({name: sha(data) for name, data in sorted(content.items())})
    temporary = out.with_name(out.name + ".part")
    try:
        with zipfile.ZipFile(temporary, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for name, data in sorted(content.items()):
                archive.writestr(name, data)
        with zipfile.ZipFile(temporary) as archive:
            for name, expected in json.loads(archive.read("MANIFEST.json")).items():
                if sha(archive.read(name)) != expected:
                    raise ValueError("Packet readback checksum mismatch")
        temporary.replace(out)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return dict(status="prepared_not_sent", path=str(out.resolve()), sha256=sha(out.read_bytes()),
                bytes=out.stat().st_size, synthetic_cases=len(cases), real_accepted_ids=[])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--run-results", type=Path, help="Source-matched passed verification_status.json or its directory")
    args = parser.parse_args(argv)
    print(json.dumps(package(args.out, run_results=args.run_results), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
