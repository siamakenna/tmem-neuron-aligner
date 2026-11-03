"""Private, metadata-only source inventory; never an acquisition/geometry approval."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import re
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

SCHEMA = "tmem.acquisition_inventory.v1"
DECLARATIONS = "tmem.acquisition_declarations.v1"
WELLS = ("E05", "F05", "I05", "J05", "M05", "N05")
DAYS = (8, 12, 16, 20, 25, 29, 32, 36, 39)
STAGES = {"RAW_DETECTOR", "CORRECTED", "STITCHED", "REGISTERED", "UNKNOWN"}
SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", ".ruff_cache", "node_modules"}
REPO = Path(__file__).resolve().parents[3]


def absolute(path):
    return Path(os.path.abspath(Path(path).expanduser()))


def safe_id(path):
    """A stable path identifier, explicitly NOT an image-content digest."""
    return "src_" + hashlib.sha256(str(absolute(path)).encode()).hexdigest()[:24]


def _symlink_component(path):
    return any(p.is_symlink() for p in (path, *path.parents))


def scan_roots(roots, *, max_files=10000):
    """Deterministic bounded walk without following source symlinks."""
    if type(max_files) is not int or max_files <= 0:
        raise ValueError("max_files must be a positive integer")
    paths, root_records, skipped, seen = [], [], [], set()
    complete = True
    for value in roots:
        root = absolute(value)
        record = {"path": str(root), "root_id": safe_id(root), "errors": []}
        root_records.append(record)
        if _symlink_component(root):
            record["errors"].append("SYMLINK_ROOT_OR_ANCESTOR_NOT_FOLLOWED")
            complete = False
            continue
        if not root.exists():
            record["errors"].append("MISSING_ROOT")
            complete = False
            continue
        if not root.is_dir():
            record["errors"].append("ROOT_MUST_BE_DIRECTORY")
            complete = False
            continue

        def onerror(error, record=record):
            record["errors"].append(str(error))

        for folder, dirs, files in os.walk(root, followlinks=False, onerror=onerror):
            folder = Path(folder)
            kept = []
            for name in sorted(dirs):
                p = folder / name
                if p.is_symlink() or name in SKIP_DIRS or name.startswith((".venv", ".cache")):
                    skipped.append({"path": str(p), "reason": "SYMLINK_OR_ENVIRONMENT_CACHE"})
                else:
                    kept.append(name)
            dirs[:] = kept
            for name in sorted(files):
                p = folder / name
                if p.suffix.lower() not in {".nd2", ".tif", ".tiff"}:
                    continue
                if p.is_symlink():
                    skipped.append({"path": str(p), "reason": "SYMLINK_FILE_NOT_FOLLOWED"})
                    continue
                key = str(p)
                if key in seen:
                    next(r for r in paths if r["path"] == key)["root_ids"].append(record["root_id"])
                    continue
                if len(paths) >= max_files:
                    record["errors"].append("FILE_LIMIT_REACHED_INVENTORY_TRUNCATED")
                    complete = False
                    dirs[:] = []
                    break
                seen.add(key)
                paths.append({"path": key, "root_ids": [record["root_id"]]})
            if record["errors"] and "FILE_LIMIT_REACHED_INVENTORY_TRUNCATED" in record["errors"]:
                break
        if record["errors"]:
            complete = False
    return paths, root_records, skipped, complete


def _finite(value):
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (ValueError, TypeError):
        return None


def inspect_nd2_header(path):
    """Read only container metadata; frame zero is not a full scene/stage map."""
    import nd2

    from tmem_align.stage_qc import stage_coordinates_from_frame_metadata

    with nd2.ND2File(path) as image:
        sizes = {str(k): int(v) for k, v in image.sizes.items()}
        channels = []
        metadata = image.metadata
        for item in getattr(metadata, "channels", []) or []:
            channel = getattr(item, "channel", item)
            volume = getattr(item, "volume", None)
            channels.append(
                {
                    "name": getattr(channel, "name", None),
                    "index": getattr(channel, "index", None),
                    "excitation_nm": _finite(getattr(channel, "excitationLambdaNm", None)),
                    "emission_nm": _finite(getattr(channel, "emissionLambdaNm", None)),
                    "camera_transform_reported": getattr(
                        volume, "cameraTransformationMatrix", None
                    ),
                    "pixel_to_stage_reported": getattr(
                        volume, "pixelToStageTransformationMatrix", None
                    ),
                }
            )
        try:
            voxel = image.voxel_size()
            voxel_size = {k + "_um": _finite(getattr(voxel, k, None)) for k in "xyz"}
        except Exception:  # noqa: BLE001 - malformed optional vendor metadata stays unavailable.
            voxel_size = None
        try:
            stage = stage_coordinates_from_frame_metadata(image.frame_metadata(0))
        except Exception:  # noqa: BLE001 - frame-zero metadata absence is recorded, not fabricated.
            stage = {"stage_coordinate_source": "UNAVAILABLE"}
        return {
            "metadata_source": "ND2_CONTAINER_METADATA",
            "axes": "".join(sizes),
            "sizes": sizes,
            "shape": list(image.shape),
            "dtype": str(image.dtype),
            "is_rgb": bool(image.is_rgb),
            "channels": channels,
            "channel_identity_status": "REPORTED_NOT_INDEPENDENTLY_VALIDATED"
            if channels
            else "UNAVAILABLE",
            "position_count": sizes.get("P", 1),
            "time_count": sizes.get("T", 1),
            "z_count": sizes.get("Z", 1),
            "reported_voxel_size": voxel_size,
            "calibration_status": "REPORTED_NOT_INDEPENDENTLY_VALIDATED"
            if voxel_size
            else "UNAVAILABLE",
            "frame_0_stage": {"frame_index": 0, "units": "um", **stage},
            "stage_map_status": "FRAME_ZERO_ONLY_NOT_ALL_SITE_GEOMETRY",
            "orientation_status": "NOT_INDEPENDENTLY_VALIDATED",
        }


def inspect_tiff_header(path):
    import tifffile

    with tifffile.TiffFile(path) as image:
        series = [
            {
                "series_index": i,
                "axes": s.axes,
                "shape": list(s.shape),
                "dtype": str(s.dtype),
                "axes_source": "TIFF_SERIES_HEADER_NOT_ACQUISITION_AXIS_PROOF",
            }
            for i, s in enumerate(image.series)
        ]
        ome = []
        if image.ome_metadata:
            tree = ET.fromstring(image.ome_metadata)
            for pixels in tree.iter():
                if pixels.tag.rsplit("}", 1)[-1] != "Pixels":
                    continue
                record = {"pixels_attributes": dict(pixels.attrib), "channels": [], "planes": []}
                for child in pixels:
                    kind = child.tag.rsplit("}", 1)[-1]
                    if kind == "Channel":
                        record["channels"].append(dict(child.attrib))
                    elif kind == "Plane":
                        record["planes"].append(dict(child.attrib))
                ome.append(record)
        return {
            "metadata_source": "TIFF_HEADER",
            "series": series,
            "ome_pixels": ome,
            "acquisition_axes_status": "OME_DECLARED_NOT_INDEPENDENTLY_VALIDATED"
            if ome
            else "UNAVAILABLE",
            "calibration_status": "REPORTED_VALUES_ONLY_NOT_INDEPENDENTLY_VALIDATED",
            "orientation_status": "UNAVAILABLE_UNLESS_INDEPENDENTLY_SUPPLIED",
        }


def inspect_source(item):
    path = Path(item["path"])
    record = {
        **item,
        "source_id": safe_id(path),
        "source_id_basis": "PATH_NOT_CONTENT_HASH",
        "file_type": "ND2" if path.suffix.lower() == ".nd2" else "TIFF",
        "identity": None,
        "processing_stage": "UNKNOWN",
        "derived_from": [],
        "intensity_range": "NOT_MEASURED_METADATA_ONLY",
    }
    hints = {}
    for label, pattern in (("well", r"Well([A-P]\d{2})"), ("day", r"day\s*(\d+)")):
        match = re.search(pattern, path.name, re.IGNORECASE)
        if match:
            hints[label] = match.group(1)
    record["filename_hints"] = {"status": "UNVERIFIED_NOT_USED_FOR_COVERAGE", **hints}
    try:
        before = path.stat()
        record.update(size_bytes=before.st_size, mtime_ns=before.st_mtime_ns)
        record["metadata"] = (
            inspect_nd2_header(path) if record["file_type"] == "ND2" else inspect_tiff_header(path)
        )
        after = path.stat()
        if (before.st_size, before.st_mtime_ns, before.st_ino) != (
            after.st_size,
            after.st_mtime_ns,
            after.st_ino,
        ):
            raise ValueError("Source changed during metadata inspection")
        record["inspection_status"] = "HEADER_READ"
    except Exception as error:  # noqa: BLE001 - preserve per-source vendor errors in the inventory.
        record.update(
            inspection_status="HEADER_ERROR", error=type(error).__name__ + ": " + str(error)
        )
    return record


def read_declarations(path, sources):
    from .diagnostic_review import read_json

    if path is None:
        return
    path = absolute(path)
    document = read_json(path)
    if (
        not isinstance(document, dict)
        or set(document) != {"schema_version", "sources"}
        or document["schema_version"] != DECLARATIONS
        or not isinstance(document["sources"], list)
    ):
        raise ValueError("Invalid acquisition declarations schema")
    known = {r["path"]: r for r in sources}
    seen = set()
    required = {"path", "well", "day", "processing_stage", "evidence_reference", "identity_source"}
    for entry in document["sources"]:
        if (
            not isinstance(entry, dict)
            or not required.issubset(entry)
            or set(entry) - required - {"site_id", "derived_from"}
        ):
            raise ValueError("Malformed source declaration fields")
        if not all(
            isinstance(entry[k], str) and entry[k].strip()
            for k in ("path", "evidence_reference", "identity_source", "processing_stage")
        ):
            raise ValueError("Source identity requires nonempty provenance references")
        if (
            entry["well"] not in WELLS
            or type(entry["day"]) is not int
            or entry["day"] not in DAYS
            or entry["processing_stage"] not in STAGES
        ):
            raise ValueError("Invalid declaration well/day/processing stage")
        p = absolute(path.parent / entry["path"])
        if str(p) not in known or str(p) in seen:
            raise ValueError("Declaration is duplicate or absent from scanned sources")
        if "site_id" in entry and (
            not isinstance(entry["site_id"], str) or not entry["site_id"].strip()
        ):
            raise ValueError("Invalid site identity")
        if "derived_from" in entry and (
            not isinstance(entry["derived_from"], list)
            or not all(isinstance(x, str) and x.strip() for x in entry["derived_from"])
        ):
            raise ValueError("Invalid source relationship claims")
        parents = [str(absolute(path.parent / x)) for x in entry.get("derived_from", [])]
        if any(x not in known or x == str(p) for x in parents):
            raise ValueError("Source relationship references absent/self source")
        seen.add(str(p))
        known[str(p)].update(
            identity={**entry, "path": str(p), "status": "DECLARED_NOT_INDEPENDENTLY_VALIDATED"},
            processing_stage=entry["processing_stage"],
            derived_from=parents,
        )


def coverage_rows(sources, scan_complete):
    uncertain = not scan_complete or any(
        not r["identity"] or r["inspection_status"] != "HEADER_READ" for r in sources
    )
    rows = []
    for well in WELLS:
        for day in DAYS:
            raw = [
                r
                for r in sources
                if r["identity"]
                and r["identity"]["well"] == well
                and r["identity"]["day"] == day
                and r["processing_stage"] == "RAW_DETECTOR"
            ]
            readable = [r for r in raw if r["inspection_status"] == "HEADER_READ"]
            status = (
                "MISSING_GEOMETRY"
                if readable
                else ("DEFERRED" if uncertain or raw else "MISSING_SOURCE")
            )
            rows.append(
                {
                    "well": well,
                    "day": day,
                    "declared_raw_source_count": len(raw),
                    "header_read_raw_source_count": len(readable),
                    "source_ids": json.dumps([r["source_id"] for r in raw]),
                    "identity_scope": "DECLARED_NOT_INDEPENDENTLY_VALIDATED",
                    "assembly_status": status,
                    "blocker": "Independent tile completeness, placement/orientation and calibration evidence required"
                    if readable
                    else "No readable declared original source established within inventoried scope; incomplete scans/unassigned identities/errors remain explicit",
                    "assemblies_verified_here": 0,
                }
            )
    return rows


def build_inventory(roots, *, declarations=None, max_files=10000):
    items, root_records, skipped, complete = scan_roots(roots, max_files=max_files)
    sources = [inspect_source(item) for item in items]
    read_declarations(declarations, sources)
    coverage = coverage_rows(sources, complete)
    report = {
        "schema_version": SCHEMA,
        "roots": root_records,
        "sources": sources,
        "skipped": skipped,
        "scan_complete": complete,
        "configuration": {
            "max_files": max_files,
            "metadata_only": True,
            "declarations": str(absolute(declarations)) if declarations else None,
        },
        "limitations": [
            "No pixels read or content hashes calculated",
            "No independently validated channel/identity/calibration/orientation",
            "No assembly, registration or scientific approval",
            "Frame-zero stage coordinates are not an all-site map",
        ],
        "source_coverage": coverage,
    }
    return report


def aggregate(report):
    sources = report["sources"]
    return {
        "schema_version": "tmem.source_coverage_summary.v1",
        "metadata_only": True,
        "scan_complete": report["scan_complete"],
        "file_type_counts": dict(Counter(r["file_type"] for r in sources)),
        "inspection_status_counts": dict(Counter(r["inspection_status"] for r in sources)),
        "original_nd2_container_count": sum(r["file_type"] == "ND2" for r in sources),
        "nd2_count_is_not_raw_processing_or_well_completeness_proof": True,
        "unknown_identity_count": sum(not r["identity"] for r in sources),
        "unknown_processing_stage_count": sum(r["processing_stage"] == "UNKNOWN" for r in sources),
        "declared_raw_coverage_count": sum(
            r["header_read_raw_source_count"] > 0 for r in report["source_coverage"]
        ),
        "assembly_status_counts": dict(
            Counter(r["assembly_status"] for r in report["source_coverage"])
        ),
        "assemblies_verified_here": 0,
    }


def _write(path, callback):
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w", newline="") as stream:
        callback(stream)


def run(roots, out, *, declarations=None, max_files=10000):
    roots = [absolute(p) for p in roots]
    out = absolute(out)
    if (
        out.exists()
        or _symlink_component(out)
        or out.is_relative_to(REPO)
        or any(out.is_relative_to(p) or p.is_relative_to(out) for p in roots)
    ):
        raise ValueError("Require a new private output outside repository and scanned roots")
    if declarations and absolute(declarations).is_relative_to(out):
        raise ValueError("Output overlaps declarations")
    report = build_inventory(roots, declarations=declarations, max_files=max_files)
    out.mkdir(parents=True, mode=0o700, exist_ok=False)
    for name, value in (
        ("acquisition_inventory.json", report),
        ("source_coverage_summary.json", aggregate(report)),
    ):
        _write(
            out / name,
            lambda stream, value=value: json.dump(value, stream, indent=2, allow_nan=False),
        )

    def write_csv(stream):
        rows = report["source_coverage"]
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    _write(out / "source_coverage.csv", write_csv)
    return report
