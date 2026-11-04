#!/usr/bin/env python3
"""Trace original ND2 tiles through detector IC and explicit whole-well assembly.

No P=0 default, inferred grid, adopted old anchors, or accepted phenotype export.
Geometry and detector correction inputs must be supplied with source evidence.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import traceback

ROOT = Path(__file__).resolve().parents[1]
DAYS = [8, 12, 16, 20, 25, 29, 32, 36, 39]
CHANNELS = ["405", "561", "488"]
sys.path.insert(0, str(ROOT / "src"))


def write_json(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    temporary.replace(path)


def digest(path):
    path = Path(path)
    before = path.stat()
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(4 * 1024**2), b""):
            value.update(block)
    after = path.stat()
    if (before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns):
        raise ValueError("Input changed while hashing: " + str(path))
    return value.hexdigest()


def _integer(value, name, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError(name + " must be an explicit integer >= " + str(minimum))


def _text(value, name):
    if not isinstance(value, str) or not value.strip() or "REPLACE" in value.upper():
        raise ValueError("Supply actual " + name)


def _input(base, value, expected, suffix):
    _text(value, "input path")
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = base / path
    if path.suffix.lower() != suffix or path.is_symlink() or not path.is_file():
        raise ValueError(f"Require original regular {suffix} input: {path}")
    if not re.fullmatch(r"[0-9a-f]{64}", str(expected)) or digest(path) != expected:
        raise ValueError("Declared input SHA256 mismatch: " + str(path))
    return path.resolve()


def validate_manifest(value, base):
    """Pure-stdlib contract and source hashes; ND2 decoding is a separate gate."""
    if value.get("schema_version") != "tmem.original_nd2_well.v1":
        raise ValueError("Unsupported original-ND2 manifest schema")
    well = value.get("well")
    if not re.fullmatch(r"[A-P](?:0[1-9]|1[0-9]|2[0-4])", str(well)):
        raise ValueError("Supply a valid well identifier")
    geometry = value.get("geometry", {})
    if geometry.get("well") != well or geometry.get("orientation_validated") is not True:
        raise ValueError("Require reviewed orientation/complete-well geometry for this well")
    for field in ["geometry_id", "coordinate_evidence", "coordinate_convention"]:
        _text(geometry.get(field), field)
    if geometry.get("channel_order") != CHANNELS:
        raise ValueError("Require explicit 405/561/488 channel order")
    _text(value.get("channel_mapping_evidence"), "channel-mapping evidence")
    pixel = geometry.get("pixel_size_um")
    if isinstance(pixel, bool) or not isinstance(pixel, (int, float)) or not math.isfinite(pixel) or pixel <= 0:
        raise ValueError("Require finite positive detector pixel size")
    canvas = geometry.get("canvas_yx")
    if not isinstance(canvas, list) or len(canvas) != 2:
        raise ValueError("Require explicit shared canvas_yx")
    for number in canvas:
        _integer(number, "canvas dimension", 1)
    expected = geometry.get("expected_tile_ids")
    if (not isinstance(expected, list) or not expected or len(set(expected)) != len(expected)
            or any(not isinstance(t, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", t) for t in expected)):
        raise ValueError("Require complete unique filename-safe expected tile IDs")
    visits = value.get("visits", [])
    if [visit.get("day") for visit in visits] != DAYS:
        raise ValueError("Require exactly all nine chronological visits")
    radius = value.get("background_radius_px")
    if radius is not None:
        _integer(radius, "background radius", 1)
    max_pixels = value.get("max_canvas_pixels", 40_000_000)
    _integer(max_pixels, "max_canvas_pixels", 1)
    _integer(value.get("max_selected_read_bytes", 512 * 1024**2), "max_selected_read_bytes", 1)
    registration_gib = value.get("max_registration_input_gib", 2)
    if isinstance(registration_gib, bool) or not isinstance(registration_gib, (int, float)) or not math.isfinite(registration_gib) or registration_gib <= 0:
        raise ValueError("Require finite positive max_registration_input_gib")
    if canvas[0] * canvas[1] > max_pixels:
        raise ValueError("Shared canvas exceeds declared memory guard")
    inputs, resolved, used_observations = {}, [], set()
    for visit in visits:
        day = visit["day"]
        ic = visit.get("ic", {})
        if ic.get("coordinate_system") != "detector":
            raise ValueError("IC fields must be in detector coordinates, before any stitching")
        if ic.get("channel_order") != CHANNELS:
            raise ValueError("Declare IC channel_order as 405/561/488 after the source-index mapping")
        for name in ["calibration_id", "provenance"]:
            _text(ic.get(name), "IC " + name)
        fields = {}
        for name in ["flatfield", "darkfield"]:
            path = _input(base, ic.get(name + "_path"), ic.get(name + "_sha256"), ".npy")
            fields[name] = str(path)
            inputs[str(path)] = ic[name + "_sha256"]
        files = visit.get("files", [])
        if not files:
            raise ValueError(f"Day{day}: no original ND2 files declared")
        seen_tiles, seen_paths, prepared = [], set(), []
        for item in files:
            path = _input(base, item.get("path"), item.get("sha256"), ".nd2")
            if str(path) in seen_paths:
                raise ValueError("Declare each ND2 file once per visit, with its full position roster")
            seen_paths.add(str(path))
            _integer(item.get("time_index"), "ND2 time index")
            if type(item.get("max_project_z")) is not bool:
                raise ValueError("Declare max_project_z true or false explicitly")
            if item["max_project_z"]:
                if item.get("z_index") is not None:
                    raise ValueError("Max-Z projection requires z_index=null")
            else:
                _integer(item.get("z_index"), "ND2 Z index")
            names = item.get("source_channel_names")
            if not isinstance(names, list) or len(names) != 3:
                raise ValueError("Declare the exact three ordered source channel names")
            for name in names:
                _text(name, "source channel name")
            indices = item.get("channel_indices")
            if (not isinstance(indices, list) or len(indices) != 3
                    or any(type(index) is not int for index in indices)
                    or sorted(indices) != [0, 1, 2]):
                raise ValueError("Declare channel_indices as the source-index permutation for 405/561/488")
            tiles = item.get("tiles", [])
            if not tiles:
                raise ValueError("Every ND2 needs an explicit complete position roster")
            positions = []
            for tile in tiles:
                _integer(tile.get("position"), "ND2 position")
                positions.append(tile["position"])
                observation = (str(path), item["time_index"], item.get("z_index"),
                               item["max_project_z"], tile["position"])
                if observation in used_observations:
                    raise ValueError("The same ND2 observation cannot represent multiple visits")
                used_observations.add(observation)
                seen_tiles.append(tile.get("tile_id"))
                _integer(tile.get("y_px"), "tile y offset")
                _integer(tile.get("x_px"), "tile x offset")
            if len(set(positions)) != len(positions):
                raise ValueError("Duplicate ND2 position")
            inputs[str(path)] = item["sha256"]
            prepared.append({**item, "path": str(path)})
        if sorted(seen_tiles) != sorted(expected):
            raise ValueError(f"Day{day}: missing/duplicate/unexpected tile; cannot claim complete well")
        resolved.append({**visit, "files": prepared, "resolved_fields": fields})
    return {**value, "visits": resolved, "input_sha256": inputs}


def validate_nd2_metadata(item, report, geometry):
    sizes = report["sizes"]
    if any(type(size) is not int or size < 1 for size in sizes.values()):
        raise ValueError("ND2 axis sizes must be positive integers")
    if report.get("is_rgb") or set(sizes) - set("PTCZYX") or sizes.get("C") != 3 or not {"Y", "X"}.issubset(sizes):
        raise ValueError("Require explicit non-RGB ND2 axes P/T/C/Z/Y/X and three independent channels")
    if report.get("channel_names") != item["source_channel_names"]:
        raise ValueError("ND2 source channel labels differ from the reviewed mapping")
    positions = sorted(tile["position"] for tile in item["tiles"])
    if positions != list(range(sizes.get("P", 1))):
        raise ValueError("Every acquired ND2 position must be included exactly once; no implicit P=0")
    if item["time_index"] >= sizes.get("T", 1):
        raise ValueError("Requested ND2 time index is outside metadata")
    if item["max_project_z"] and "Z" not in sizes:
        raise ValueError("Max-Z requested but ND2 has no Z axis")
    if not item["max_project_z"] and item["z_index"] >= sizes.get("Z", 1):
        raise ValueError("Requested ND2 Z index is outside metadata")
    voxel = report.get("voxel_size") or {}
    if any(not isinstance(voxel.get(k), (int, float)) or not math.isclose(voxel[k], geometry["pixel_size_um"], rel_tol=1e-4, abs_tol=1e-9)
           for k in ["x_um", "y_um"]):
        raise ValueError("ND2 detector pixel calibration differs from declared reviewed geometry")
    for tile in item["tiles"]:
        if tile["y_px"] + sizes["Y"] > geometry["canvas_yx"][0] or tile["x_px"] + sizes["X"] > geometry["canvas_yx"][1]:
            raise ValueError("An acquired tile extends outside the reviewed shared canvas")


def run_command(name, arguments, out):
    env = dict(os.environ, PYTHONPATH=str(ROOT / "src") + os.pathsep + str(ROOT / "scripts"),
               PYTHONDONTWRITEBYTECODE="1", MPLBACKEND="Agg")
    with (out / (name + ".log")).open("w") as handle:
        result = subprocess.run(arguments, cwd=ROOT, env=env, stdout=handle, stderr=subprocess.STDOUT, check=False)
    if result.returncode:
        raise RuntimeError(f"{name} failed; inspect {out / (name + '.log')}")


def execute(plan, out):
    import numpy as np
    import tifffile
    from tmem_align.nd2_tools import extract_nd2_selection, inspect_nd2
    from tmem_align.preprocess import preprocess_image
    from tmem_align.audit_v1.stage_trace import StageTrace, verify_trace
    geometry = plan["geometry"]
    write_json(out / "geometry.json", geometry)
    all_tiles, visits = [], []
    metadata_records = []
    for visit in plan["visits"]:
        day = visit["day"]
        folder = out / f"day_{day:02d}"
        folder.mkdir()
        fields = visit["resolved_fields"]
        flat = np.load(fields["flatfield"], allow_pickle=False)
        dark = np.load(fields["darkfield"], allow_pickle=False)
        for file_index, item in enumerate(visit["files"]):
            report = inspect_nd2(item["path"])
            validate_nd2_metadata(item, report, geometry)
            metadata_records.append({"day": day, "file": item["path"], "metadata": report,
                                     "selection": {k: item[k] for k in ["time_index", "z_index", "max_project_z", "tiles"]}})
            for tile in item["tiles"]:
                tile_root = folder / "tiles" / tile["tile_id"]
                tile_root.mkdir(parents=True)
                raw_path = tile_root / "raw_cyx.ome.tif"
                extract_nd2_selection(item["path"], raw_path, position=tile["position"],
                    time=item["time_index"], z=item["z_index"], max_project_z=item["max_project_z"],
                    max_read_bytes=plan.get("max_selected_read_bytes", 512 * 1024**2))
                with tifffile.TiffFile(raw_path) as image:
                    if image.series[0].axes != "CYX" or image.series[0].shape[0] != 3:
                        raise ValueError("ND2 extraction did not produce exact three-channel CYX")
                    source_raw = image.asarray()
                # Preserve raw_cyx.ome.tif in source order; only the explicitly
                # declared mapping enters the project-order processing path.
                raw = source_raw[item["channel_indices"]]
                trace = StageTrace(tile_root / "preprocessing", metadata={"original_nd2": item["path"],
                    "original_nd2_sha256": item["sha256"], "day": day, "well": plan["well"],
                    "tile": tile, "ic": visit["ic"], "invoked_mode": "nd2-well",
                    "channels": CHANNELS,
                    "source_channel_names": item["source_channel_names"],
                    "channel_indices": item["channel_indices"],
                    "inputs": [{"path": item["path"], "sha256": item["sha256"]}],
                    "scientific_inference_ready": False})
                trace.capture("nd2_read_tile", raw[2], axes="YX", channel="488",
                    why="Preserve the exact selected 488 detector plane read from the original ND2 before correction; all three channels are retained in raw_cyx.ome.tif.",
                    details={"original_nd2_sha256": item["sha256"], "position": tile["position"],
                             "time_index": item["time_index"], "z_index": item["z_index"],
                             "max_project_z": item["max_project_z"], "raw_cyx_path": str(raw_path),
                             "source_channel_indices": item["channel_indices"],
                             "raw_cyx_channel_order": item["source_channel_names"]})
                corrected = preprocess_image(raw, ic_field=flat, darkfield=dark,
                    background_radius=plan.get("background_radius_px"), trace=trace, trace_prefix="detector")
                trace.finish({"status": "executed", "original_nd2_used": True,
                              "ic_field_supplied_not_physically_validated_by_software": True,
                              "real_accepted_ids": [], "scientific_inference_ready": False})
                verify_trace(tile_root / "preprocessing")
                corrected_path = tile_root / "corrected_cyx.ome.tif"
                tifffile.imwrite(corrected_path, corrected, photometric="minisblack", metadata={"axes": "CYX"})
                all_tiles.append(dict(well=plan["well"], day=day, tile_id=tile["tile_id"], path=str(corrected_path),
                    y_px=tile["y_px"], x_px=tile["x_px"], ic_status="applied_with_provenance",
                    ic_provenance=str(tile_root / "preprocessing/provenance.json")))
        tile_manifest = folder / "tiles.csv"
        with tile_manifest.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(all_tiles[-1]))
            writer.writeheader()
            writer.writerows(row for row in all_tiles if row["day"] == day)
        run_command(f"assemble_day_{day:02d}", [sys.executable, str(ROOT / "scripts/assemble_tmem_well.py"),
            "--tiles", str(tile_manifest), "--geometry", str(out / "geometry.json"), "--well", plan["well"],
            "--day", str(day), "--out", str(folder / "assembly"),
            "--max-pixels", str(plan.get("max_canvas_pixels", 40_000_000))], out)
        visits.append(dict(well=plan["well"], day=day, assembly_directory=str(folder / "assembly")))
        write_json(out / "nd2_metadata_and_selections.json", metadata_records)
    visits_path = out / "whole_well_visits.csv"
    with visits_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["well", "day", "assembly_directory"])
        writer.writeheader(); writer.writerows(visits)
    run_command("whole_well_registration", [sys.executable, str(ROOT / "scripts/register_tmem_well.py"),
        "--visits", str(visits_path), "--well", plan["well"], "--out", str(out / "registration"),
        "--max-input-gib", str(plan.get("max_registration_input_gib", 2))], out)
    return dict(status="original_nd2_ic_assembly_registration_executed", original_nd2_used=True,
        original_positions_included="all metadata positions in every declared file",
        independent_whole_well_validation=False,
        placement_model="reviewed integer detector-aligned offsets; no affine/rotation resampling",
        whole_well_visits=9, fresh_tracking_status="pending_new_coordinate_system",
        old_atlas_anchors_reusable=False, scientific_inference_ready=False, real_accepted_ids=[])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args(argv)
    out = args.out.expanduser().resolve()
    out.mkdir(parents=True, exist_ok=False)
    status = dict(status="validating", original_nd2_used=False, real_accepted_ids=[],
                  independent_whole_well_validation=False, scientific_inference_ready=False)
    try:
        manifest_path = args.manifest.expanduser().resolve()
        manifest_bytes = manifest_path.read_bytes()
        manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
        plan = validate_manifest(json.loads(manifest_bytes), manifest_path.parent)
        write_json(out / "resolved_manifest.json", plan)
        before = dict(plan["input_sha256"])
        code_paths = sorted((ROOT / "src").rglob("*.py")) + [Path(__file__).resolve(),
            ROOT / "scripts/assemble_tmem_well.py", ROOT / "scripts/register_tmem_well.py",
            ROOT / "scripts/run_260213_longitudinal_pilot.py"]
        code = {str(p.relative_to(ROOT)): digest(p) for p in code_paths}
        write_json(out / "input_and_code_provenance.json", dict(manifest_sha256=manifest_sha,
            inputs=before, code_sha256=code, source_kind="original ND2, not registered TIFF"))
        if args.validate_only:
            status.update(status="contract_and_input_hashes_validated", nd2_metadata_reader_status="not_executed",
                          preprocessing_status="not_executed", registration_status="not_executed")
        else:
            status.update(execute(plan, out))
            if before != {p: digest(p) for p in before} or code != {str(p.relative_to(ROOT)): digest(p) for p in code_paths}:
                raise RuntimeError("Input or code changed during execution; all outputs require rejection")
        if digest(manifest_path) != manifest_sha:
            raise RuntimeError("Manifest changed during execution; outputs require rejection")
        (out / "NEXT_STEPS.md").write_text("# Original ND2 well run\n\n"
            "Read RUN_STATUS.json and the actual traces before claiming completion.\n"
            "Fresh tracking/segmentation must use the newly assembled/registered coordinate system.\n"
            "Old atlas anchors are invalid in this coordinate frame. No biological review or export was approved.\n"
            "Generate image flowcharts from the recorded ND2 preprocessing and whole-well stages; label unavailable downstream stages explicitly.\n")
        write_json(out / "RUN_STATUS.json", status)
        print("TMEM_ORIGINAL_ND2_STATUS=" + status["status"])
        return 0
    except Exception as error:
        status.update(status="blocked_or_failed", error=str(error), traceback=traceback.format_exc())
        write_json(out / "RUN_STATUS.json", status)
        print("STOP: " + str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
