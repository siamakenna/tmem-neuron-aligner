#!/usr/bin/env python3
"""Describe or verify six registered stacks for a portable local diagnostic run.

The remote mode only reads CSV/file metadata and streams file hashes.  It does
not decode images, submit jobs, approve neurons, or modify source data.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import stat
import sys


SCHEMA = "tmem.portable_dataset.v1"
WELLS = ("E05", "F05", "I05", "J05", "M05", "N05")
DAYS = [8, 12, 16, 20, 25, 29, 32, 36, 39]
CHANNELS = ["405", "561", "488"]
MASTER_SHA256 = "4d1a7c224cea385562492601859ac90fb29228070539ce13ca79598341d12390"
DEFAULT_MASTER = Path(
    "/data/rodriguezmak/tmem106b/processed/multi_neuron_atlas_v2/"
    "all_neurons_longitudinal_master.csv"
)
SOURCE_ROOTS = (
    Path("/data/rodriguezmak/tmem106b/processed"),
    Path("/vf/users/rodriguezmak/tmem106b/processed"),
)


def _snapshot(path: Path):
    item = path.lstat()
    if not stat.S_ISREG(item.st_mode):
        raise ValueError(f"Require a regular, non-symlink file: {path}")
    return (item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns)


def _digest(path: Path):
    before = _snapshot(path)
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    if before != _snapshot(path):
        raise ValueError(f"Source changed while hashing: {path}")
    return {"sha256": digest.hexdigest(), "bytes": before[2]}


def _source(path: Path, allowed_roots):
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError(f"Source must be an absolute path without traversal: {path}")
    roots = tuple(Path(root) for root in allowed_roots)
    lexical = any(path.is_relative_to(root) for root in roots)
    resolved = path.resolve(strict=True)
    contained = any(resolved.is_relative_to(root.resolve()) for root in roots)
    if not lexical or not contained:
        raise ValueError(f"Source is outside the allowed processed-data roots: {path}")
    _snapshot(path)
    return path


def _read_master(data: bytes):
    reader = csv.DictReader(io.StringIO(data.decode("utf-8-sig")))
    required = {"well", "neuron_id", "day", "time_index", "source_registered_stack",
                "anchor_y", "anchor_x", "tracking_valid"}
    if not required.issubset(reader.fieldnames or []):
        raise ValueError("Master is missing required longitudinal/source columns")
    if len(reader.fieldnames) != len(set(reader.fieldnames)):
        raise ValueError("Master contains duplicate column names")
    rows = list(reader)
    if not rows:
        raise ValueError("Master contains no rows")
    tracks = {}
    sources = {well: set() for well in WELLS}
    for row in rows:
        well = row["well"]
        if well not in sources:
            raise ValueError(f"Unexpected well in frozen master: {well}")
        neuron = row["neuron_id"]
        if not re.fullmatch(re.escape(well) + r"_N\d{3}", neuron):
            raise ValueError(f"Malformed neuron identity: {neuron}")
        try:
            day = int(row["day"])
            index = int(row["time_index"])
        except (TypeError, ValueError) as error:
            raise ValueError(f"Invalid day/index for {neuron}") from error
        tracks.setdefault(neuron, []).append((index, day))
        sources[well].add(row["source_registered_stack"])
    for neuron, visits in tracks.items():
        if sorted(visits) != list(enumerate(DAYS)):
            raise ValueError(f"Require exactly the nine declared visits: {neuron}")
    for well, paths in sources.items():
        if len(paths) != 1:
            raise ValueError(f"Require one registered source stack for {well}")
    return rows, sources


def build_remote_manifest(master=DEFAULT_MASTER, *, expected_master_sha256=MASTER_SHA256,
                          allowed_roots=SOURCE_ROOTS):
    """Hash the frozen sources; override roots/hash only in isolated tests."""
    master = _source(Path(master), allowed_roots)
    before = _snapshot(master)
    master_bytes = master.read_bytes()
    if before != _snapshot(master):
        raise ValueError("Master changed while reading")
    digest = hashlib.sha256(master_bytes).hexdigest()
    if digest != expected_master_sha256:
        raise ValueError("Frozen master checksum does not match; no data was selected")
    rows, sources = _read_master(master_bytes)
    manifest = {
        "schema_version": SCHEMA,
        "master": {"path": "master.csv", "source_path": str(master),
                   "sha256": digest, "bytes": len(master_bytes)},
        "stacks": {}, "days": DAYS[:], "channels": CHANNELS[:],
        "master_rows": len(rows),
        "scope": "Registered image inputs only; historical raw IC/stitching remain unvalidated",
        "real_accepted_ids": [], "scientific_inference_ready": False,
    }
    for well in WELLS:
        path = _source(Path(next(iter(sources[well]))), allowed_roots)
        if path.name != f"{well}_registered_common_overlap_tcyx.ome.tif":
            raise ValueError(f"Unexpected source stack basename for {well}: {path.name}")
        record = _digest(path)
        if record["bytes"] <= 0:
            raise ValueError(f"Source stack is empty: {path}")
        manifest["stacks"][well] = {
            "path": f"stacks/{well}.ome.tif", "source_path": str(path), **record,
        }
    # A changing master invalidates the manifest even if all image hashes finished.
    if before != _snapshot(master) or hashlib.sha256(master.read_bytes()).hexdigest() != digest:
        raise ValueError("Frozen master changed during collection")
    return manifest


def _local_file(root: Path, relative: str, expected: str):
    if relative != expected or PurePosixPath(relative).is_absolute() or ".." in PurePosixPath(relative).parts:
        raise ValueError(f"Unexpected portable relative path: {relative}")
    current = root
    for part in PurePosixPath(relative).parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"Portable data must not use symlinks: {current}")
    if not current.resolve(strict=True).is_relative_to(root.resolve()):
        raise ValueError("Portable path escaped the dataset root")
    _snapshot(current)
    return current


def verify_local_dataset(directory, *, expected_master_sha256=MASTER_SHA256):
    root = Path(directory)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Require an existing, non-symlink dataset directory")
    manifest_path = _local_file(root, "dataset_manifest.json", "dataset_manifest.json")
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("schema_version") != SCHEMA:
        raise ValueError("Unsupported portable dataset schema")
    if manifest.get("days") != DAYS or manifest.get("channels") != CHANNELS:
        raise ValueError("Dataset must declare the original nine days and channel order")
    if set(manifest.get("stacks", {})) != set(WELLS):
        raise ValueError("Portable dataset must include all six wells")
    records = [("master", manifest["master"], "master.csv")]
    records += [(well, manifest["stacks"][well], f"stacks/{well}.ome.tif") for well in WELLS]
    total = 0
    for label, record, relative in records:
        if not isinstance(record, dict) or not re.fullmatch(r"[0-9a-f]{64}", record.get("sha256", "")):
            raise ValueError(f"Invalid SHA256 for {label}")
        if type(record.get("bytes")) is not int or record["bytes"] <= 0:
            raise ValueError(f"Invalid byte count for {label}")
        path = _local_file(root, record.get("path", ""), relative)
        actual = _digest(path)
        if actual != {"sha256": record["sha256"], "bytes": record["bytes"]}:
            raise ValueError(f"Downloaded data checksum/size mismatch: {label}")
        total += actual["bytes"]
    if manifest["master"]["sha256"] != expected_master_sha256:
        raise ValueError("Downloaded master is not the declared frozen baseline")
    rows, sources = _read_master((root / "master.csv").read_bytes())
    for well in WELLS:
        if manifest["stacks"][well].get("source_path") != next(iter(sources[well])):
            raise ValueError(f"Source-stack provenance mismatch for {well}")
    return {"status": "verified", "schema_version": SCHEMA, "wells": list(WELLS),
            "files_verified": 7, "bytes_verified": total, "master_rows": len(rows),
            "registered_inputs_only": True, "real_accepted_ids": [],
            "scientific_inference_ready": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--remote-manifest", action="store_true")
    mode.add_argument("--verify-local", metavar="DATASET_DIR", type=Path)
    parser.add_argument("--master", type=Path, default=DEFAULT_MASTER)
    parser.add_argument("--out", type=Path, help="Write JSON to a NEW path instead of stdout")
    args = parser.parse_args(argv)
    try:
        result = (build_remote_manifest(args.master) if args.remote_manifest
                  else verify_local_dataset(args.verify_local))
        data = json.dumps(result, indent=2, sort_keys=True) + "\n"
        if args.out:
            with args.out.open("x", encoding="utf-8") as handle:
                handle.write(data)
        else:
            sys.stdout.write(data)
        return 0
    except (OSError, ValueError, TypeError, KeyError, csv.Error) as error:
        print(f"STOP: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
