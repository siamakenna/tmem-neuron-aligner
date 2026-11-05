#!/usr/bin/env python3
"""Private, manifest-bound ND2 batch execution. No pixel reads during inventory.

All new results are diagnostics. Receipts never approve neurons or phenotype.
The image adapter imports the user's actual checkout, not an embedded snapshot.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import resource
import shlex
import subprocess
import sys
import tempfile
import time
import traceback

SCHEMA = "tmem.full_dataset.v2"
DAYS = [8, 12, 16, 20, 25, 29, 32, 36, 39]
HERE = Path(__file__).resolve().parent
WELL = re.compile(r"Well\s*([A-P])\s*(\d{2})(?!\d)", re.I)
DAY = re.compile(r"Day\s*0?(\d{1,2})(?!\d)", re.I)
BRIGHTFIELD = re.compile(r"bright\s*field|(?:^|[_-])BF(?:[_-]|\.)|transmitted", re.I)


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024**2), b""):
            h.update(block)
    return h.hexdigest()


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def object_sha(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def load(path):
    return json.loads(Path(path).read_text())


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".receipt-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(encoded(value) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def disjoint(a, b):
    a, b = Path(a).resolve(), Path(b).resolve()
    if a.is_relative_to(b) or b.is_relative_to(a):
        raise ValueError("Input and output directories must be disjoint")


def new_directory(path, *inputs):
    path = Path(path).expanduser().absolute()
    if path.is_symlink():
        raise ValueError("Linked output directory is forbidden")
    path = path.resolve()
    for source in inputs:
        disjoint(path, source)
    path.mkdir(parents=True, exist_ok=False, mode=0o700)
    return path


def stat_record(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError("Source must be a regular, unlinked file: " + str(path))
    s = path.stat()
    return {"bytes": s.st_size, "mtime_ns": s.st_mtime_ns, "device": s.st_dev, "inode": s.st_ino}


def parse_name(name):
    wells, days = list(WELL.finditer(name)), list(DAY.finditer(name))
    w = wells[0] if len(wells) == 1 else None
    d = days[0] if len(days) == 1 else None
    well = w.group(1).upper() + w.group(2) if w else None
    if well and not 1 <= int(well[1:]) <= 24:
        well = None
    return well, int(d.group(1)) if d else None, "brightfield" if BRIGHTFIELD.search(name) else "fluorescence"


def find_nd2(root, maximum=10000):
    root = Path(root).expanduser().resolve(strict=True)
    if maximum < 1 or not root.is_dir():
        raise ValueError("Positive maximum and existing raw directory required")
    paths, links = [], []
    for directory, dirs, files in os.walk(root, followlinks=False):
        kept = []
        for name in sorted(dirs):
            child = Path(directory) / name
            if child.is_symlink():
                links.append(str(child))
            else:
                kept.append(name)
        dirs[:] = kept
        for name in sorted(files):
            child = Path(directory) / name
            if child.suffix.lower() != ".nd2":
                continue
            if child.is_symlink():
                links.append(str(child))
                continue
            paths.append(child)
            if len(paths) > maximum:
                raise ValueError("ND2 count exceeds --max-files; no partial inventory accepted")
    if not paths:
        raise ValueError("No original ND2 files found; empty inventory cannot pass")
    return sorted(paths), links


def header(path, nd2_module):
    """Axis and channel metadata only; no to_dask/asarray call."""
    well, day, modality = parse_name(path.name)
    row = {"path": str(path.resolve()), "well": well, "day": day, "modality": modality,
           "stat": stat_record(path), "error": None}
    try:
        with nd2_module.ND2File(str(path)) as f:
            sizes = {str(k): int(v) for k, v in f.sizes.items()}
            if not {"Y", "X"}.issubset(sizes) or any(v < 1 for v in sizes.values()):
                raise ValueError("Missing/invalid spatial axes")
            channels = [str(getattr(getattr(c, "channel", c), "name", "UNKNOWN"))
                        for c in getattr(getattr(f, "metadata", None), "channels", []) or []]
            if len(channels) != sizes.get("C", 1) or len(set(channels)) != len(channels):
                raise ValueError("Channel metadata absent, ambiguous or inconsistent with C axis")
            if any(c in {"", "None", "UNKNOWN"} for c in channels):
                raise ValueError("Explicit source channel labels required")
            rgb = getattr(f, "is_rgb", None)
            if rgb is None or bool(rgb):
                raise ValueError("RGB/unknown color encoding requires a separate validated adapter")
            row.update(sizes=sizes, axis_order=list(sizes), channels=channels,
                       dtype=str(f.dtype), is_rgb=False, position_axis_present="P" in sizes,
                       declared_positions=sizes.get("P", 1), site_correspondence="unverified")
            try:
                voxel = f.voxel_size()
                row["voxel_size_um"] = {axis: float(getattr(voxel, axis)) for axis in "xyz"}
            except (AttributeError, TypeError, ValueError):
                row["voxel_size_um"] = None
            # Capture source-provided loop metadata verbatim when serializable.
            # These values are evidence to authenticate, never a fabricated grid.
            experiments = []
            for experiment in getattr(f, "experiment", []) or []:
                if hasattr(experiment, "model_dump"):
                    experiments.append(experiment.model_dump(mode="json"))
                elif hasattr(experiment, "_asdict"):
                    experiments.append(experiment._asdict())
                else:
                    experiments.append(repr(experiment))
            try:
                encoded(experiments)
                row["acquisition_experiment_metadata"] = experiments
            except (ValueError, TypeError):
                row["acquisition_experiment_metadata"] = repr(experiments)
    except Exception as error:
        row["error"] = type(error).__name__ + ": " + str(error)
    return row


def inventory(root, out, *, nd2_module=None, max_files=10000, expected_wells=None, expected_days=None):
    root = Path(root).expanduser().resolve(strict=True)
    paths, links = find_nd2(root, max_files)
    out = new_directory(out, root)
    if nd2_module is None:
        import nd2 as nd2_module
    rows = []
    for index, path in enumerate(paths, 1):
        row = header(path, nd2_module)
        rows.append(row)
        # Atomic file-level checkpoints survive preemption or a later bad header.
        atomic_json(out / "headers" / f"{index:06}.json", row)
        if index % 100 == 0:
            print(f"TMEM_HEADERS={index}/{len(paths)}", flush=True)
    actual_wells = sorted({r["well"] for r in rows if r["well"] and r["modality"] == "fluorescence"})
    expected = sorted(set(expected_wells or actual_wells))
    keys = {}
    inodes = {}
    for r in rows:
        keys.setdefault((r["well"], r["day"], r["modality"]), []).append(r["path"])
        inodes.setdefault((r["stat"]["device"], r["stat"]["inode"]), []).append(r["path"])
    expected_days = expected_days or DAYS
    summary = {"files": len(rows), "observed_wells": actual_wells, "expected_days": expected_days,
               "expected_well_roster_supplied": expected_wells is not None,
               "expected_wells": expected,
               "missing_fluorescence": [[w, d] for w in expected for d in expected_days
                                        if (w, d, "fluorescence") not in keys],
               "multiple_sources_need_site_mapping": [{"key": list(k), "paths": v}
                                                        for k, v in keys.items() if len(v) > 1],
               "header_errors": [r for r in rows if r["error"]], "excluded_links": links,
               "duplicate_source_inodes": [v for v in inodes.values() if len(v) > 1],
               "unparsed_names": [r["path"] for r in rows if not r["well"] or r["day"] is None],
               "file_counts_192x9_plus_192_BF": len(rows) == 1920 and len(actual_wells) == 192
                   and all(sum(r["day"] == d and r["modality"] == "fluorescence" for r in rows) == 192 for d in DAYS)
                   and sum(r["day"] == 8 and r["modality"] == "brightfield" for r in rows) == 192,
               "whole_well_coverage_verified": False, "pixel_data_read": False,
               "source_identity": "stat/device/inode only; worker hashes all selected original bytes"}
    result = {"schema": SCHEMA, "raw_root": str(root), "headers": rows, "summary": summary}
    atomic_json(out / "INVENTORY_PRIVATE.json", result)
    candidates = []
    for r in rows:
        if r["error"] or r["modality"] != "fluorescence":
            continue
        for position in range(r["declared_positions"]):
            candidates.append({"path": r["path"], "position": position, "time": 0, "z": 0,
                               "well": r["well"], "day": r["day"], "site": None,
                               "channel_map": {}, "evidence": None})
    atomic_json(out / "SITE_MAP_UNVERIFIED_PRIVATE.json", {"schema": SCHEMA, "observations": candidates})
    return result


def source_binding(repo):
    repo = Path(repo).expanduser().resolve(strict=True)
    files = {}
    for directory in ["src", "scripts", "configs", "tools/full_dataset_v2"]:
        base = repo / directory
        if not base.exists():
            continue
        for path in sorted(base.rglob("*")):
            if "__pycache__" in path.parts or path.suffix not in {".py", ".json", ".yaml", ".yml", ".sh"}:
                continue
            if path.is_symlink():
                raise ValueError("Source code symlink cannot be bound: " + str(path))
            if path.is_file():
                files[str(path.relative_to(repo))] = digest(path)
    if not files:
        raise ValueError("No project source found in --repo")
    for path in [repo / "pyproject.toml", repo / "environment.yml", *sorted(repo.glob("requirements*.txt"))]:
        if path.is_file():
            files[str(path.relative_to(repo))] = digest(path)
    def git(*args):
        p = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
        return p.stdout.strip() if p.returncode == 0 else None
    engine = {p.name: digest(p) for p in [HERE / "full_dataset.py", HERE / "project_adapter.py"]}
    versions = {}
    for name in ["numpy", "scipy", "scikit-image", "nd2", "tifffile", "dask", "pandas", "Pillow", "matplotlib", "imageio", "PyYAML"]:
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    return {"project_files": files, "engine_files": engine, "head": git("rev-parse", "HEAD"),
            "origin_main_at_capture": git("rev-parse", "refs/remotes/origin/main"),
            "dirty_status": git("status", "--porcelain", "--untracked-files=normal"),
            "python": sys.version, "executable": sys.executable, "package_versions": versions}


def verify_source(manifest):
    current = source_binding(manifest["repo"])
    if current != manifest["source"]:
        raise ValueError("Source/environment changed; preserve run and create a new manifest")


def evidence_record(value, raw_root):
    if not isinstance(value, dict) or not value.get("path") or not value.get("reason"):
        raise ValueError("Site/geometry requires an acquisition evidence file and explicit reason")
    path = Path(value["path"]).expanduser().resolve(strict=True)
    # Evidence can be an instrument log alongside originals; never written.
    return {"path": str(path), "sha256": digest(path), "reason": str(value["reason"])}


def make_plan(inv, site_map, profile, repo, out, *, allow_subset=False):
    """Require explicit per-file indices, labels and authenticated site mapping."""
    raw = Path(inv["raw_root"])
    if not allow_subset and any(inv["summary"].get(k) for k in ["header_errors", "excluded_links", "unparsed_names", "duplicate_source_inodes"]):
        raise ValueError("Inventory has unresolved sources; a full-dataset manifest cannot silently omit them")
    out = Path(out).expanduser().resolve()
    disjoint(out, raw)
    disjoint(out, repo)
    required = {"name", "days", "channels", "identity_channel", "luts", "processing"}
    if not required.issubset(profile):
        raise ValueError("Incomplete dataset profile")
    days, channels = profile["days"], profile["channels"]
    if not days or days != sorted(set(days)) or len(channels) != len(set(channels)):
        raise ValueError("Unique ordered days/channels required")
    if profile["identity_channel"] not in channels:
        raise ValueError("Identity role must be a declared metadata-mapped channel")
    if profile["name"] == "february_neuron" and (channels != ["405", "561", "488"] or profile["identity_channel"] != "488"):
        raise ValueError("Neuronal diagnostics require canonical 405/561/488, with 488 identity")
    if profile["name"] == "february_neuron" and not allow_subset:
        if days != DAYS or not inv["summary"].get("file_counts_192x9_plus_192_BF"):
            raise ValueError("Full February planning requires all nine visits and the complete declared file collection; label a pilot subset explicitly")
    for c in channels:
        low, high = profile["luts"][c]
        if not (isinstance(low, (int, float)) and isinstance(high, (int, float)) and low < high):
            raise ValueError("Every channel needs a fixed finite increasing LUT range")
    # Current adapter intentionally does not retune the frozen registration QC.
    if set(profile["processing"]) - {"background_radius", "max_read_bytes", "trace_arrays", "candidate_tracking", "tracking"}:
        raise ValueError("Unknown processing parameter; no silently ignored settings")
    settings = profile["processing"]
    if type(settings.get("max_read_bytes", 512 * 1024**2)) is not int or settings.get("max_read_bytes", 1) < 1:
        raise ValueError("Positive integer memory guard required")
    radius = settings.get("background_radius")
    if radius is not None and (type(radius) is not int or radius < 1):
        raise ValueError("Background radius must be null or a positive integer")
    for boolean in ["trace_arrays", "candidate_tracking"]:
        if boolean in settings and type(settings[boolean]) is not bool:
            raise ValueError("Explicit boolean required: " + boolean)
    tuning = settings.get("tracking", {})
    bounds = {"bbox_size": (128, 256), "template_size": (15, 65), "search_radius": (10, 100),
              "min_area": (20, 1000), "initial_search_radius": (1, 100)}
    if set(tuning) - set(bounds):
        raise ValueError("Unknown candidate tracking parameter")
    for name, value in tuning.items():
        low, high = bounds[name]
        if type(value) is not int or not low <= value <= high:
            raise ValueError("Candidate parameter outside declared diagnostic bounds: " + name)
    rows_by_path = {r["path"]: r for r in inv["headers"]}
    grouped, seen, covered = {}, set(), set()
    for supplied in site_map["observations"]:
        path = str(Path(supplied["path"]).expanduser().resolve(strict=True))
        if path not in rows_by_path:
            raise ValueError("Observation not present in this inventory")
        row = rows_by_path[path]
        if row["error"] or row["modality"] != "fluorescence":
            raise ValueError("Only readable fluorescence inputs can enter a fluorescence task")
        if supplied.get("well") != row["well"] or supplied.get("day") != row["day"]:
            raise ValueError("Well/day metadata mismatch")
        if row["day"] not in days:
            raise ValueError("Mapped visit absent from the selected profile")
        site = supplied.get("site")
        if not isinstance(site, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,50}", site):
            raise ValueError("Authenticated site ID required; P index alone is not a site ID")
        for axis, key in [("P", "position"), ("T", "time"), ("Z", "z")]:
            index = supplied.get(key)
            if type(index) is not int or not 0 <= index < row["sizes"].get(axis, 1):
                raise ValueError(f"Explicit in-range {key} required")
            if axis != "P" and row["sizes"].get(axis, 1) > 1:
                raise ValueError("T/Z>1 requires a separately validated acquisition policy; no implicit frame/projection selection")
        mapping = supplied.get("channel_map", {})
        if len(channels) != row["sizes"].get("C", 1):
            raise ValueError("Profile must declare every source channel; undeclared channels cannot be silently dropped")
        if set(mapping) != set(channels) or len(set(mapping.values())) != len(channels):
            raise ValueError("One unique metadata label per profile channel required, on every visit")
        if any(row["channels"].count(mapping[c]) != 1 for c in channels):
            raise ValueError("Channel map does not uniquely match this file's own metadata")
        key = (row["well"], site, row["day"])
        physical = (path, supplied["position"], supplied["time"], supplied["z"])
        if key in seen or physical in covered:
            raise ValueError("Duplicate well/site/day or duplicate source position")
        seen.add(key)
        covered.add(physical)
        observation = dict(supplied, path=path, header=row,
                           evidence=evidence_record(supplied.get("evidence"), raw))
        grouped.setdefault((row["well"], site), []).append(observation)
    expected = {(r["path"], p, 0, 0) for r in inv["headers"]
                if not r["error"] and r["modality"] == "fluorescence" and r["day"] in days
                for p in range(r["declared_positions"])}
    missing = expected - covered
    if not allow_subset and missing:
        raise ValueError(f"{len(missing)} declared source positions are unmapped; refuse an all-dataset claim")
    tasks = []
    for (well, site), observations in sorted(grouped.items()):
        observations.sort(key=lambda x: x["day"])
        if [x["day"] for x in observations] != days:
            raise ValueError("Every well/site must contain all selected visits exactly once")
        tasks.append({"id": well + "__" + site, "well": well, "site": site,
                      "scope": "field_series", "observations": observations})
    if not tasks:
        raise ValueError("No tasks planned")
    manifest = {"schema": SCHEMA, "repo": str(Path(repo).resolve()), "raw_root": str(raw),
                "out_root": str(out), "profile": profile, "source": source_binding(repo),
                "tasks": tasks, "declared_positions": len(expected), "mapped_positions": len(covered),
                "all_declared_positions_mapped": not missing, "subset_requested": allow_subset,
                "unmapped_positions": [list(k) for k in sorted(missing)],
                "whole_well_coverage_verified": False, "accepted_identities": 0}
    manifest["manifest_sha256"] = object_sha(manifest)
    return manifest


def check_manifest(manifest):
    other = dict(manifest)
    checksum = other.pop("manifest_sha256", None)
    if checksum != object_sha(other):
        raise ValueError("Manifest bytes changed")
    tasks = manifest["tasks"]
    ids = [t["id"] for t in tasks]
    if len(ids) != len(set(ids)) or any(not re.fullmatch(r"[A-Za-z0-9_-]+", t) for t in ids):
        raise ValueError("Duplicate/unsafe task IDs")
    for source in [manifest["repo"], manifest["raw_root"]]:
        disjoint(manifest["out_root"], source)
    return manifest


def input_records(task):
    records = {}
    for obs in task["observations"]:
        p = obs["path"]
        if stat_record(p) != obs["header"]["stat"]:
            raise ValueError("Original ND2 size/mtime changed after inventory: " + p)
        if p not in records:
            records[p] = {**stat_record(p), "sha256": digest(p)}
        ev = obs["evidence"]
        if digest(ev["path"]) != ev["sha256"]:
            raise ValueError("Acquisition site evidence changed")
        records[ev["path"]] = {**stat_record(ev["path"]), "sha256": ev["sha256"]}
        for spec in obs.get("calibration", {}).values():
            if not isinstance(spec, dict) or not spec.get("path") or not spec.get("sha256"):
                raise ValueError("Calibration path and checksum required")
            path = str(Path(spec["path"]).expanduser().resolve(strict=True))
            if digest(path) != spec["sha256"]:
                raise ValueError("Calibration source bytes changed")
            records[path] = {**stat_record(path), "sha256": spec["sha256"]}
    if task.get("geometry_evidence"):
        ev = task["geometry_evidence"]
        if digest(ev["path"]) != ev["sha256"]:
            raise ValueError("Whole-well geometry evidence changed")
        records[ev["path"]] = {**stat_record(ev["path"]), "sha256": ev["sha256"]}
    return records


def make_well_plan(manifest, geometry, out_root):
    """Assemble each visit's authentic fields before well-level registration."""
    check_manifest(manifest)
    verify_source(manifest)
    if len(manifest["profile"]["channels"]) != 3:
        raise ValueError("Existing verified well assembler requires three canonical channels; other assays need a tested adapter")
    tasks = []
    for well, spec in sorted(geometry["wells"].items()):
        if spec.get("coordinate_model") != "verified_integer_translation":
            raise ValueError("Existing assembler supports verified integer placements only; no guessed grids/rotation")
        canvas = spec["canvas_yx"]
        if len(canvas) != 2 or any(type(v) is not int or v < 1 for v in canvas) or canvas[0] * canvas[1] > 40_000_000:
            raise ValueError("Invalid/memory-unsafe whole-well canvas")
        source_tasks = [t for t in manifest["tasks"] if t["well"] == well and t["scope"] == "field_series"]
        if not source_tasks:
            raise ValueError("Geometry well absent from mapped field tasks")
        observations = []
        for day in manifest["profile"]["days"]:
            placements = spec["visits"][str(day)]
            by_site = {p["site"]: p for p in placements}
            if len(by_site) != len(placements) or set(by_site) != {t["site"] for t in source_tasks}:
                raise ValueError("Every visit must place every authentic mapped site exactly once")
            for t in source_tasks:
                obs = next(o for o in t["observations"] if o["day"] == day)
                offset = by_site[t["site"]]["offset_yx"]
                if len(offset) != 2 or any(type(v) is not int or v < 0 for v in offset):
                    raise ValueError("Require nonnegative integer detector offsets")
                observations.append(dict(obs, placement_yx=offset))
        tasks.append({"id": well + "__WELL_MOSAIC", "well": well, "site": "WELL_MOSAIC",
                      "scope": "well_mosaic_series", "canvas_yx": canvas,
                      "geometry_evidence": evidence_record(spec["evidence"], manifest["raw_root"]),
                      "observations": observations})
    if not tasks:
        raise ValueError("No well geometries supplied")
    result = dict(manifest, tasks=tasks, out_root=str(Path(out_root).resolve()),
                  all_declared_positions_mapped=manifest["all_declared_positions_mapped"] and
                  {t["well"] for t in tasks} == {t["well"] for t in manifest["tasks"]},
                  parent_field_manifest_sha256=manifest["manifest_sha256"])
    result.pop("manifest_sha256", None)
    result["manifest_sha256"] = object_sha(result)
    return check_manifest(result)


def output_records(root):
    records = {}
    for p in sorted(Path(root).rglob("*")):
        if p.is_symlink():
            raise ValueError("Linked result cannot be committed")
        if p.is_file():
            with p.open("rb") as stream:
                os.fsync(stream.fileno())
            records[str(p.relative_to(root))] = {"bytes": p.stat().st_size, "sha256": digest(p)}
    return records


def safe_result(root, relative):
    root = Path(root).resolve()
    path = root / relative
    if Path(relative).is_absolute() or ".." in Path(relative).parts or path.is_symlink():
        raise ValueError("Unsafe result path")
    if not path.resolve().is_relative_to(root):
        raise ValueError("Result path escapes task output")
    return path


def verify_completed(root, receipt):
    if receipt.get("status") != "completed" or not receipt.get("outputs"):
        raise ValueError("Empty/noncompleted task receipt")
    artifact_root = root / "artifacts"
    if artifact_root.is_symlink():
        raise ValueError("Linked artifact root")
    paths = list(artifact_root.rglob("*"))
    if any(p.is_symlink() for p in paths):
        raise ValueError("Linked artifact")
    observed = {str(p.relative_to(artifact_root)) for p in paths if p.is_file()}
    if observed != set(receipt["outputs"]):
        raise ValueError("Artifact inventory differs from the completed receipt")
    for name, r in receipt["outputs"].items():
        p = safe_result(root / "artifacts", name)
        if not p.is_file() or p.stat().st_size != r["bytes"] or digest(p) != r["sha256"]:
            raise ValueError("Missing or modified result: " + name)


def run_task(manifest, task_id, *, processor=None):
    check_manifest(manifest)
    verify_source(manifest)
    task = next((t for t in manifest["tasks"] if t["id"] == task_id), None)
    if task is None:
        raise ValueError("Explicit task ID absent from manifest")
    root = Path(manifest["out_root"]) / task_id
    if root.is_symlink():
        raise ValueError("Linked task directory")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    # mkdir is an atomic per-task claim. A killed process leaves a visible lock;
    # no automatic stale-lock deletion or second job is allowed.
    lock = root / "ACTIVE.lock"
    lock.mkdir(exist_ok=False)
    started = time.monotonic()
    stage = None
    try:
        inputs = input_records(task)
        binding = object_sha({"manifest": manifest["manifest_sha256"], "task": task, "inputs": inputs})
        existing = root / "COMPLETED.json"
        if existing.exists():
            receipt = load(existing)
            if receipt["binding"] != binding:
                raise ValueError("Completed task conflicts with changed inputs/config/source")
            verify_completed(root, receipt)
            return dict(receipt, resumed=True)
        # Attempts remain durable and separate. A failed prior attempt is never erased.
        attempts = root / "attempts"
        attempts.mkdir(exist_ok=True)
        stage = Path(tempfile.mkdtemp(prefix="attempt-", dir=attempts))
        atomic_json(stage / "STARTED.json", {"binding": binding, "inputs": inputs, "pid": os.getpid()})
        artifacts = stage / "artifacts"
        artifacts.mkdir()
        if processor is None:
            sys.path.insert(0, str(HERE))
            from project_adapter import process
            processor = process
        result = processor(manifest, task, artifacts)
        if input_records(task) != inputs:
            raise ValueError("Original source changed during execution")
        verify_source(manifest)
        outputs = output_records(artifacts)
        if not outputs:
            raise ValueError("Processor produced no durable artifacts")
        if (root / "artifacts").exists():
            raise ValueError("Unreceipted artifacts exist; preserve and reconcile before retry")
        os.rename(artifacts, root / "artifacts")
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        peak_bytes = int(peak if sys.platform == "darwin" else peak * 1024)
        receipt = {"schema": SCHEMA, "status": "completed", "id": task_id, "binding": binding,
                   "manifest_sha256": manifest["manifest_sha256"], "inputs": inputs, "outputs": outputs,
                   "result": result, "seconds": round(time.monotonic() - started, 6),
                   "peak_rss_bytes": peak_bytes, "peak_rss_scope": "process lifetime high-water mark",
                   "finished_utc": datetime.now(timezone.utc).isoformat(), "accepted_identities": 0,
                   "phenotype_approval": False, "whole_well_coverage_verified": False}
        atomic_json(existing, receipt)
        return receipt
    except BaseException as exc:
        if stage is None:
            attempts = root / "attempts"
            attempts.mkdir(exist_ok=True)
            stage = Path(tempfile.mkdtemp(prefix="preflight-", dir=attempts))
        atomic_json(stage / "FAILED.json", {"status": "failed", "id": task_id,
            "error": type(exc).__name__ + ": " + str(exc), "traceback": traceback.format_exc(),
            "seconds": round(time.monotonic() - started, 6)})
        raise
    finally:
        lock.rmdir()


def aggregate(manifest, *, hash_inputs=False):
    check_manifest(manifest)
    verify_source(manifest)
    rows = []
    for task in manifest["tasks"]:
        root = Path(manifest["out_root"]) / task["id"]
        row = {"id": task["id"], "well": task["well"], "site": task["site"],
               "expected_days": manifest["profile"]["days"], "status": "missing", "qc_failed_days": []}
        if (root / "COMPLETED.json").is_file():
            try:
                receipt = load(root / "COMPLETED.json")
                if receipt["manifest_sha256"] != manifest["manifest_sha256"]:
                    raise ValueError("Receipt belongs to another manifest")
                if hash_inputs and receipt["inputs"] != input_records(task):
                    raise ValueError("Source pixels changed after completion")
                verify_completed(root, receipt)
                result = receipt["result"]
                if result["days"] != manifest["profile"]["days"]:
                    raise ValueError("Completed task omitted visits")
                row.update(status="completed", qc_failed_days=result.get("qc_failed_days", []),
                           well_registration_qc_pass=result.get("well_registration_qc_pass"),
                           segmentation_failed_days=result.get("soma_tracking", {}).get("segmentation_failed_days", []),
                           tracking_failed_days=result.get("soma_tracking", {}).get("tracking_failed_days", []),
                           seconds=receipt["seconds"], peak_rss_bytes=receipt["peak_rss_bytes"])
            except Exception as exc:
                row.update(status="invalid", error=str(exc))
        elif (root / "ACTIVE.lock").is_dir():
            row["status"] = "active_or_interrupted_lock"
        elif list((root / "attempts").glob("*/FAILED.json")):
            row["status"] = "failed"
        rows.append(row)
    expected_ids = {t["id"] for t in manifest["tasks"]}
    out = Path(manifest["out_root"])
    unexpected = sorted(p.parent.name for p in out.glob("*/COMPLETED.json") if p.parent.name not in expected_ids)
    summary = {"manifest_sha256": manifest["manifest_sha256"], "tasks": rows,
               "expected": len(rows), "completed": sum(r["status"] == "completed" for r in rows),
               "unexpected_task_receipts": unexpected, "source_pixels_rehashed": hash_inputs,
               "all_declared_positions_mapped": manifest["all_declared_positions_mapped"],
               "scientific_review_complete": False, "whole_well_coverage_verified": False,
               "accepted_identities": 0}
    summary["execution_complete"] = summary["completed"] == len(rows) and not unexpected
    return summary


def _child_run(args):
    path, task_id = args
    # One fresh subprocess per task makes RSS comparable across serial/parallel pilots.
    cmd = [sys.executable, "-B", str(HERE / "full_dataset.py"), "run", "--manifest", str(path), "--task", task_id]
    p = subprocess.run(cmd, capture_output=True, text=True)
    return {"task": task_id, "returncode": p.returncode, "stdout": p.stdout[-2000:], "stderr": p.stderr[-4000:]}


def pilot(manifest_path, out, wells):
    original = check_manifest(load(manifest_path))
    verify_source(original)
    if len(set(wells)) != 2:
        raise ValueError("Pilot requires exactly two distinct actual wells")
    tasks = [t for t in original["tasks"] if t["well"] in wells]
    if set(t["well"] for t in tasks) != set(wells):
        raise ValueError("Both pilot wells must be mapped in manifest")
    if len(original["profile"]["days"]) < 2:
        raise ValueError("Pilot needs at least two real visits")
    out = new_directory(out, original["raw_root"], original["repo"], original["out_root"])
    paths, logs = {}, {}
    for mode in ["serial", "parallel"]:
        m = dict(original, tasks=tasks, out_root=str(out / mode))
        m.pop("manifest_sha256", None)
        m["manifest_sha256"] = object_sha(m)
        path = out / (mode + "_manifest.json")
        atomic_json(path, m)
        paths[mode] = path
        jobs = [(path, t["id"]) for t in tasks]
        if mode == "serial":
            logs[mode] = [_child_run(job) for job in jobs]
        else:
            with ProcessPoolExecutor(max_workers=2) as pool:
                logs[mode] = list(pool.map(_child_run, jobs))
        atomic_json(out / (mode + "_logs.json"), logs[mode])
    comparisons = []
    for t in tasks:
        receipts = []
        for mode in ["serial", "parallel"]:
            p = out / mode / t["id"] / "COMPLETED.json"
            receipts.append(load(p) if p.is_file() else None)
        equal = all(receipts) and receipts[0]["outputs"] == receipts[1]["outputs"] and receipts[0]["result"] == receipts[1]["result"]
        resumed = False
        if equal:
            resumed = run_task(load(paths["serial"]), t["id"]).get("resumed", False)
        comparisons.append({"task": t["id"], "byte_equal_all_outputs_and_diagnostics": bool(equal), "resume_noop": resumed})
    success = all(x["byte_equal_all_outputs_and_diagnostics"] and x["resume_noop"] for x in comparisons)
    report = {"schema": SCHEMA, "passed": success, "original_manifest_sha256": original["manifest_sha256"],
              "pilot_manifests": {mode: {"path": str(path), "sha256": digest(path)} for mode, path in paths.items()},
              "source": original["source"], "actual_wells": wells, "days": original["profile"]["days"],
              "all_mapped_sites_for_these_wells": True, "comparisons": comparisons,
              "serial_summary": aggregate(load(paths["serial"]), hash_inputs=True),
              "parallel_summary": aggregate(load(paths["parallel"]), hash_inputs=True),
              "method": "original ND2; separate serial and two-worker subprocesses; exact hashes; exact-source resume",
              "biological_validation": False, "whole_well_coverage_verified": False}
    atomic_json(out / "REAL_PILOT_REPORT_PRIVATE.json", report)
    return report


def swarm_commands(manifest_path, pilot_path, output):
    manifest = check_manifest(load(manifest_path))
    verify_source(manifest)
    report = load(pilot_path)
    if not report.get("passed") or report.get("original_manifest_sha256") != manifest["manifest_sha256"]:
        raise ValueError("Real source-bound serial/two-worker pilot has not passed for this manifest")
    if set(report.get("pilot_manifests", {})) != {"serial", "parallel"}:
        raise ValueError("Pilot lacks its verifiable original execution manifests")
    live_pilots = {}
    for mode, record in report["pilot_manifests"].items():
        if digest(record["path"]) != record["sha256"]:
            raise ValueError("Pilot manifest changed")
        pm = check_manifest(load(record["path"]))
        verify_source(pm)
        if pm["source"] != manifest["source"] or pm["profile"] != manifest["profile"]:
            raise ValueError("Pilot source/profile no longer matches intended full run")
        expected_tasks = [t for t in manifest["tasks"] if t["well"] in report["actual_wells"]]
        if pm["tasks"] != expected_tasks:
            raise ValueError("Pilot did not include every declared mapped site for its wells")
        live_pilots[mode] = pm
        if not aggregate(pm, hash_inputs=True)["execution_complete"]:
            raise ValueError("Pilot artifacts/inputs no longer verify")
    for task in live_pilots["serial"]["tasks"]:
        receipts = [load(Path(live_pilots[mode]["out_root"]) / task["id"] / "COMPLETED.json") for mode in ["serial", "parallel"]]
        if receipts[0]["outputs"] != receipts[1]["outputs"] or receipts[0]["result"] != receipts[1]["result"]:
            raise ValueError("Serial/parallel pilot outputs no longer agree")
    if not manifest["all_declared_positions_mapped"] or manifest["subset_requested"]:
        raise ValueError("Full-dataset Swarm requires complete original-position mapping")
    # Swarm recognizes # as a comment even within shell quotes; reject unsafe names.
    paths = [sys.executable, str(HERE / "full_dataset.py"), str(Path(manifest_path).resolve()), manifest["out_root"]]
    if any(any(c in p for c in "#\r\n") for p in paths):
        raise ValueError("Swarm paths may not contain comment/newline characters")
    commands = []
    for task in manifest["tasks"]:
        args = [sys.executable, "-B", str(HERE / "full_dataset.py"), "run", "--manifest",
                str(Path(manifest_path).resolve()), "--task", task["id"]]
        commands.append("env OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 " + shlex.join(args))
    output = Path(output)
    disjoint(output, manifest["raw_root"])
    disjoint(output, manifest["repo"])
    with output.open("x") as stream:
        stream.write("\n".join(commands) + "\n")
    peak = max((r.get("peak_rss_bytes", 0) for r in report["parallel_summary"]["tasks"]), default=0)
    return {"commands": len(commands), "swarm_sha256": digest(output), "pilot_peak_rss_bytes": peak,
            "suggested_gb_with_50_percent_headroom": max(4, int(peak * 1.5 / 1024**3) + 1),
            "submitted": False, "scope": "one ordered well/site series per task; no whole-well claim"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("inventory")
    p.add_argument("--root", required=True, type=Path)
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--max-files", type=int, default=10000)
    p.add_argument("--expected-wells", type=Path, help="JSON list from acquisition plate map")
    p.add_argument("--profile", type=Path, help="Use this assay's declared visits for coverage checks")
    p.add_argument("--expect-february-counts", action="store_true")
    p = sub.add_parser("plan")
    for flag in ["inventory", "site-map", "profile", "repo", "out-root", "out"]:
        p.add_argument("--" + flag, required=True, type=Path)
    p.add_argument("--allow-subset", action="store_true")
    p = sub.add_parser("run")
    p.add_argument("--manifest", required=True, type=Path)
    p.add_argument("--task", required=True)
    p = sub.add_parser("well-plan")
    for flag in ["manifest", "geometry", "out-root", "out"]:
        p.add_argument("--" + flag, required=True, type=Path)
    p = sub.add_parser("aggregate")
    p.add_argument("--manifest", required=True, type=Path)
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--hash-inputs", action="store_true")
    p = sub.add_parser("pilot")
    p.add_argument("--manifest", required=True, type=Path)
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--wells", nargs=2, required=True)
    p = sub.add_parser("swarm")
    p.add_argument("--manifest", required=True, type=Path)
    p.add_argument("--pilot-report", required=True, type=Path)
    p.add_argument("--out", required=True, type=Path)
    p = sub.add_parser("source")
    p.add_argument("--repo", required=True, type=Path)
    p.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    if args.command == "inventory":
        inv = inventory(args.root, args.out, max_files=args.max_files,
                        expected_wells=load(args.expected_wells) if args.expected_wells else None,
                        expected_days=load(args.profile)["days"] if args.profile else None)
        print(json.dumps(inv["summary"], indent=2))
        bad = any(inv["summary"][k] for k in ["header_errors", "excluded_links", "unparsed_names", "missing_fluorescence", "duplicate_source_inodes"])
        bad |= bool(args.expect_february_counts and not inv["summary"]["file_counts_192x9_plus_192_BF"])
        return 2 if bad else 0
    if args.command == "plan":
        result = make_plan(load(args.inventory), load(args.site_map), load(args.profile), args.repo,
                           args.out_root, allow_subset=args.allow_subset)
        if args.out.exists():
            raise ValueError("Manifest output already exists; preserve it")
        disjoint(args.out, result["repo"])
        disjoint(args.out, result["raw_root"])
        atomic_json(args.out, result)
    elif args.command == "run":
        result = run_task(load(args.manifest), args.task)
    elif args.command == "well-plan":
        result = make_well_plan(load(args.manifest), load(args.geometry), args.out_root)
        if args.out.exists():
            raise ValueError("Output manifest exists")
        disjoint(args.out, result["repo"])
        disjoint(args.out, result["raw_root"])
        atomic_json(args.out, result)
    elif args.command == "aggregate":
        manifest = load(args.manifest)
        disjoint(args.out, manifest["repo"])
        disjoint(args.out, manifest["raw_root"])
        result = aggregate(manifest, hash_inputs=args.hash_inputs)
        atomic_json(args.out, result)
    elif args.command == "pilot":
        result = pilot(args.manifest, args.out, args.wells)
    elif args.command == "swarm":
        result = swarm_commands(args.manifest, args.pilot_report, args.out)
        atomic_json(args.out.with_suffix(".receipt.json"), result)
    else:
        result = source_binding(args.repo)
        if args.out.exists():
            raise ValueError("Source receipt exists")
        atomic_json(args.out, result)
    print(json.dumps({k: v for k, v in result.items() if k not in {"inputs", "outputs", "source", "project_files", "engine_files", "tasks"}}, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print("STOP: " + type(error).__name__ + ": " + str(error), file=sys.stderr)
        raise SystemExit(2)
