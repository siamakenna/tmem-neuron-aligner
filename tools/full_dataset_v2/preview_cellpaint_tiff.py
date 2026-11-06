#!/usr/bin/env python3
"""Bounded five-role, single-acquisition Cell Paint TIFF diagnostics.

All input locations and role mappings come from a private hashed manifest.
This is image ingestion/preprocessing/display validation, not assay validation.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
import csv
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import traceback

import numpy as np
import tifffile

import full_dataset as f
from project_adapter import Observer

SCHEMA = "tmem.cellpaint.tiff.single_acquisition.v1"
ROLES = ["DNA", "ER", "RNA", "AGP", "Mito"]


def verified_file(spec):
    supplied = Path(spec["path"]).expanduser().absolute()
    if supplied.is_symlink():
        raise ValueError("Linked input is unsupported")
    path = supplied.resolve(strict=True)
    record = {"path": str(path), **f.stat_record(path), "sha256": f.digest(path)}
    if record["sha256"] != spec.get("sha256"):
        raise ValueError("Source hash mismatch: " + path.name)
    return record


def metadata_rows(spec):
    record = verified_file(spec)
    delimiter = spec.get("delimiter", ",")
    if not isinstance(delimiter, str) or len(delimiter) != 1:
        raise ValueError("Metadata delimiter must be one character")
    opener = gzip.open if record["path"].endswith(".gz") else open
    with opener(record["path"], "rt", newline="") as stream:
        reader = csv.DictReader(stream, delimiter=delimiter)
        if not reader.fieldnames or len(reader.fieldnames) != len(set(reader.fieldnames)):
            raise ValueError("Metadata requires unique column labels")
        rows = list(reader)
    return rows, record


def selected_row(rows, selector):
    if not isinstance(selector, dict) or not selector or any(not isinstance(v, str) for v in selector.values()):
        raise ValueError("Explicit string-valued metadata selector required")
    matches = [r for r in rows if all(r.get(k) == v for k, v in selector.items())]
    if len(matches) != 1:
        raise ValueError("Metadata selector must match exactly one acquisition row")
    return matches[0]


def validate_manifest(manifest):
    allowed = {"schema", "acquisition_count", "role_metadata", "acquisition_metadata", "provenance", "fields", "luts", "processing"}
    if set(manifest) - allowed or manifest.get("schema") != SCHEMA or type(manifest.get("acquisition_count")) is not int or manifest["acquisition_count"] != 1:
        raise ValueError("Only the declared single-acquisition schema is supported; no temporal visits")
    if set(manifest["luts"]) != set(ROLES):
        raise ValueError("Declare one fixed LUT for every Cell Paint role")
    from tmem_align.audit_v1.display import LUT
    for role in ROLES:
        limits = manifest["luts"][role]
        if not isinstance(limits, list) or len(limits) != 2:
            raise ValueError("LUT must be [lower, upper]")
        LUT(*limits)
    settings = manifest.get("processing", {})
    if set(settings) - {"background_radius", "trace_arrays", "max_field_bytes"}:
        raise ValueError("Unsupported processing option; calibration is unavailable for this adapter")
    radius = settings.get("background_radius")
    if radius is not None and (type(radius) is not int or not 1 <= radius <= 500):
        raise ValueError("background_radius must be null or integer 1..500")
    if type(settings.get("trace_arrays", False)) is not bool:
        raise ValueError("trace_arrays must be an explicit boolean")
    if type(settings.get("max_field_bytes", 256 * 1024**2)) is not int or settings.get("max_field_bytes", 1) < 1:
        raise ValueError("Positive max_field_bytes required")
    rows, role_record = metadata_rows(manifest["role_metadata"])
    acquisition_rows, acquisition_record = metadata_rows(manifest["acquisition_metadata"])
    acquisition = selected_row(acquisition_rows, manifest["acquisition_metadata"]["selector"])
    count_column = manifest["acquisition_metadata"].get("count_column", "Times_imaged")
    if acquisition.get(count_column) != "1":
        raise ValueError("Acquisition metadata must authenticate exactly one imaging pass")
    records = [role_record, acquisition_record] + [verified_file(s) for s in manifest.get("provenance", [])]
    fields = manifest["fields"]
    if not isinstance(fields, list) or not fields:
        raise ValueError("At least one explicit field required")
    seen_ids, seen_sources, seen_sites = set(), set(), set()
    for field in fields:
        if set(field) != {"id", "metadata_selector", "acquisition_time", "shape_yx", "images"}:
            raise ValueError("Unexpected or missing field declaration")
        if not isinstance(field["id"], str) or not re.fullmatch(r"[A-Za-z0-9_-]+", field["id"]) or field["id"] in seen_ids:
            raise ValueError("Unique filename-safe field ID required")
        seen_ids.add(field["id"])
        shape = field["shape_yx"]
        if not isinstance(shape, list) or len(shape) != 2 or any(type(n) is not int or n < 1 for n in shape):
            raise ValueError("Explicit positive YX shape required")
        if 5 * np.prod(shape, dtype=np.int64) * 2 > settings.get("max_field_bytes", 256 * 1024**2):
            raise ValueError("Field exceeds declared memory guard")
        row = selected_row(rows, field["metadata_selector"])
        acquisition_plate = acquisition.get("Assay_Plate_Barcode", acquisition.get("Plate"))
        if not acquisition_plate or row.get("Metadata_Plate") != acquisition_plate:
            raise ValueError("Field plate disagrees with authenticated acquisition metadata")
        metadata_shape = [row.get("Metadata_ImageSizeY"), row.get("Metadata_ImageSizeX")]
        if any(v is not None for v in metadata_shape) and metadata_shape != [str(n) for n in shape]:
            raise ValueError("Declared YX shape disagrees with acquisition metadata")
        physical_site = tuple(row.get(k) for k in ["Metadata_Plate", "Metadata_Well", "Metadata_Site"])
        if any(not x for x in physical_site) or physical_site in seen_sites:
            raise ValueError("Each physical field appears once; no temporal visits may be invented")
        seen_sites.add(physical_site)
        if not field["acquisition_time"] or row.get("Metadata_AbsTime") != field["acquisition_time"]:
            raise ValueError("Actual metadata acquisition timestamp required")
        roles = [s.get("role") for s in field["images"]]
        if len(roles) != 5 or set(roles) != set(ROLES):
            raise ValueError("Exactly one image for each of the five roles required")
        for spec in field["images"]:
            if set(spec) != {"role", "path", "sha256", "source_filename", "mapping_column"}:
                raise ValueError("Unexpected or missing image declaration")
            if spec["mapping_column"] != "FileName_Orig" + spec["role"] or row.get(spec["mapping_column"]) != spec["source_filename"]:
                raise ValueError("Role/filename mapping disagrees with acquisition metadata")
            record = verified_file(spec)
            physical = (record["device"], record["inode"])
            if physical in seen_sources:
                raise ValueError("Duplicate source image/inode across roles or fields")
            seen_sources.add(physical)
            records.append(record)
    return records


def read_field(field, *, with_backends=False):
    """Read all five independently mapped YX planes into canonical CYX order."""
    planes, backends, declarations = [], [], {s["role"]: s for s in field["images"]}
    for role in ROLES:
        spec = declarations[role]
        verified_file(spec)
        with tifffile.TiffFile(spec["path"]) as image:
            if len(image.series) != 1 or len(image.pages) != 1 or image.series[0].axes != "YX" or image.series[0].shape != tuple(field["shape_yx"]):
                raise ValueError("Unsupported axes/shape: expected one declared YX TIFF plane")
            if image.pages[0].samplesperpixel != 1 or np.dtype(image.series[0].dtype) != np.dtype("uint16"):
                raise ValueError("Expected scalar uint16 detector pixels")
            backend = "tifffile"
            try:
                plane = image.series[0].asarray()
            except ValueError as exc:
                if image.pages[0].compression != 5 or "imagecodecs" not in str(exc) or "requires" not in str(exc):
                    raise
                # The independent JUMP originals use LZW. The existing Pillow
                # libtiff decoder can read it without installing a dependency.
                # Keep every TIFF metadata gate above; never rescale pixels.
                from PIL import Image
                with Image.open(spec["path"]) as fallback:
                    if fallback.format != "TIFF" or getattr(fallback, "n_frames", 1) != 1 or fallback.mode not in {"I;16", "I;16L", "I;16B"}:
                        raise ValueError("Pillow LZW fallback requires one scalar uint16 TIFF frame") from exc
                    plane = np.asarray(fallback)
                    if plane.dtype.kind != "u" or plane.dtype.itemsize != 2:
                        raise ValueError("Pillow LZW fallback changed source pixel dtype") from exc
                    plane = plane.astype(np.uint16, copy=False)
                backend = "Pillow/libtiff LZW; tifffile metadata gates; uint16 exact-value decode"
        if plane.ndim != 2 or plane.shape != tuple(field["shape_yx"]) or plane.dtype != np.uint16:
            raise ValueError("Decoded TIFF disagrees with declared axes/shape/dtype")
        planes.append(plane)
        backends.append({"role": role, "backend": backend, "source_sha256": spec["sha256"]})
    result = np.stack(planes)
    return (result, backends) if with_backends else result


def code_binding(repo):
    return {"project": f.source_binding(repo), "helper_sha256": f.digest(Path(__file__))}


def process_field(manifest, field, repo, out):
    out = Path(out)
    out.mkdir(mode=0o700)
    observer = Observer(out / "stages", ROLES, manifest["luts"], "DNA", arrays=manifest.get("processing", {}).get("trace_arrays", False))
    from tmem_align.preprocess import preprocess_image
    from tmem_align.audit_v1.display import LUT
    from tmem_align.audit_v1.visualization import render_preview
    from PIL import Image
    try:
        raw, backends = read_field(field, with_backends=True)
        np.save(out / "RAW_CYX.npy", raw, allow_pickle=False)
        raw_hash = hashlib.sha256(raw.tobytes()).hexdigest()
        processed = preprocess_image(raw, ic_field=None, darkfield=None,
            background_radius=manifest.get("processing", {}).get("background_radius"), trace=observer, trace_prefix="cellpaint_preprocess")
        np.save(out / "PREPROCESSED_CYX.npy", processed, allow_pickle=False)
        processed_hash = hashlib.sha256(processed.tobytes()).hexdigest()
        previews = []
        for index, role in enumerate(ROLES):
            limits = manifest["luts"][role]
            lut = LUT(*limits, scope="fixed-per-role-across-selected-fields", source="explicit-private-manifest")
            for stage, array in [("raw", raw[index]), ("preprocessed", processed[index])]:
                preview = Image.fromarray(render_preview(array, lut))
                observer.capture_display(role + "_" + stage + "_render_preview", preview, array,
                    "Production render_preview; full YX viewport, fixed declared per-role LUT; display only")
                observer.records[-1].update(preview_lut=limits, channel=role, render_function="tmem_align.audit_v1.visualization.render_preview",
                    source_selection={"field_id": field["id"], "acquisition_time": field["acquisition_time"], "canonical_channel_index": index, "axes": "YX"})
                previews.append({"role": role, "stage": stage, "path": observer.records[-1]["preview"], "lut": limits})
        if hashlib.sha256(raw.tobytes()).hexdigest() != raw_hash or hashlib.sha256(processed.tobytes()).hexdigest() != processed_hash:
            raise ValueError("Display rendering mutated quantitative arrays")
        result = {"field_id": field["id"], "acquisition_count": 1, "acquisition_time": field["acquisition_time"],
            "axes": "CYX", "roles": ROLES, "shape": list(raw.shape), "dtype": str(raw.dtype),
            "decode_backends": backends,
            "raw_sha256": raw_hash, "preprocessed_sha256": processed_hash, "quantitative_arrays_unchanged_by_rendering": True,
            "preprocessing": {"function": "tmem_align.preprocess.preprocess_image", "background_radius": manifest.get("processing", {}).get("background_radius"),
                "darkfield": "skipped: unavailable calibration", "flatfield_ic": "skipped: unavailable calibration"},
            "unexecuted": {"registration": "single acquisition; independent fields lack authenticated correspondence",
                "segmentation": "Cell Paint assay model unvalidated", "tracking": "single acquisition; no temporal tracking",
                "whole_well_stitching": "selected independent fields; whole-well geometry unavailable"},
            "previews": previews, "accepted_identities": 0, "biological_validation": False}
        f.atomic_json(out / "FIELD_RESULT_PRIVATE.json", result)
        return result
    finally:
        for record in observer.records:
            record["source_provenance"] = {"field_id": field["id"], "acquisition_time": field["acquisition_time"],
                "source_images": field["images"], "configuration_object_sha256": f.object_sha(manifest),
                "execution_binding": "../../../CELLPAINT_VERIFICATION_PRIVATE.json"}
        observer.finish()


def _child(args):
    manifest, field, repo, out = args
    try:
        result = process_field(manifest, field, repo, out)
        return {"id": field["id"], "status": "passed", "result": result, "outputs": f.output_records(out)}
    except BaseException as exc:
        Path(out).mkdir(parents=True, exist_ok=True, mode=0o700)
        failure = {"id": field["id"], "status": "failed", "error": type(exc).__name__ + ": " + str(exc), "traceback": traceback.format_exc()}
        f.atomic_json(Path(out) / "FAILED_PRIVATE.json", failure)
        return failure


def run(manifest_path, repo, out, *, compare_workers=False):
    manifest_path, repo = Path(manifest_path).resolve(strict=True), Path(repo).resolve(strict=True)
    # Require outputs outside every input parent and checkout before any writes.
    manifest = f.load(manifest_path)
    specs = [manifest["role_metadata"], manifest["acquisition_metadata"], *manifest.get("provenance", []),
             *[s for field in manifest["fields"] for s in field["images"]]]
    input_parents = [manifest_path.parent, *[Path(s["path"]).expanduser().resolve().parent for s in specs]]
    out = f.new_directory(out, repo, *input_parents)
    os.chmod(out, 0o700)
    try:
        from tmem_align import preprocess
        from tmem_align.audit_v1 import visualization
        for module in [preprocess, visualization]:
            if not Path(module.__file__).resolve().is_relative_to(repo):
                raise ValueError("Production module was imported outside bound checkout")
        before = code_binding(repo)
        inputs = validate_manifest(manifest)
        config_hash = f.digest(manifest_path)
        f.atomic_json(out / "MANIFEST_PRIVATE.json", manifest)
        f.atomic_json(out / "STARTED_PRIVATE.json", {"source": before, "inputs": inputs, "manifest_sha256": config_hash})
        modes, reports = (["serial", "two_workers"] if compare_workers else ["serial"]), {}
        for mode in modes:
            mode_root = out / mode
            mode_root.mkdir(mode=0o700)
            jobs = [(manifest, field, str(repo), str(mode_root / field["id"])) for field in manifest["fields"]]
            if mode == "serial":
                results = [_child(job) for job in jobs]
            else:
                with ProcessPoolExecutor(max_workers=2) as pool:
                    results = list(pool.map(_child, jobs))
            reports[mode] = results
            f.atomic_json(out / (mode + "_PRIVATE.json"), results)
        success = all(r["status"] == "passed" for results in reports.values() for r in results)
        comparisons = []
        if compare_workers:
            for serial, parallel in zip(reports["serial"], reports["two_workers"]):
                equal = serial == parallel and serial["status"] == "passed"
                comparisons.append({"field_id": serial["id"], "byte_equal_all_artifacts_and_results": equal})
            success &= all(c["byte_equal_all_artifacts_and_results"] for c in comparisons)
        source_unchanged = code_binding(repo) == before
        inputs_unchanged = validate_manifest(manifest) == inputs and f.digest(manifest_path) == config_hash
        result = {"schema": SCHEMA, "status": "passed" if success and source_unchanged and inputs_unchanged else "requires_review",
            "source": before, "manifest_sha256": config_hash, "inputs": inputs, "source_unchanged": source_unchanged, "inputs_unchanged": inputs_unchanged,
            "field_count": len(manifest["fields"]), "role_count_per_field": 5, "acquisition_count": 1,
            "serial_two_worker_comparisons": comparisons, "comparison_scope": "ingestion/preprocessing/LUT diagnostics; no registration or temporal tracking",
            "scientific_validation": False, "whole_well_coverage_verified": False}
        f.atomic_json(out / "CELLPAINT_VERIFICATION_PRIVATE.json", result)
        return result
    except BaseException as exc:
        f.atomic_json(out / "FAILED_PRIVATE.json", {"status": "failed", "error": type(exc).__name__ + ": " + str(exc), "traceback": traceback.format_exc()})
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ["manifest", "repo", "out"]:
        parser.add_argument("--" + flag, type=Path, required=True)
    parser.add_argument("--compare-workers", action="store_true")
    args = parser.parse_args()
    result = run(args.manifest, args.repo, args.out, compare_workers=args.compare_workers)
    print(json.dumps({k: v for k, v in result.items() if k not in {"source", "inputs"}}, indent=2))
    return 0 if result["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
