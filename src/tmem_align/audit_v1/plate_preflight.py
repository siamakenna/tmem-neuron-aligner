"""Metadata-only, fail-closed boundary for future stored-field plate runs."""

import hashlib
import importlib.metadata
import json
import os
import platform
import re
import stat
import subprocess

from .full_plate import contract_digest, plain, sha, validate_contract
from .nd2_contracts import require_legacy_single_observation

STAGE = "ORIGINAL_STORED_ND2_CORRECTION_UNKNOWN"
PARAMETERS = {
    "ref_mode": "anchored",
    "max_sites": 1,
    "max_read_bytes": 2 * 1024**3,
    "anchor_corr_thresh": 0.10,
    "min_post_correlation": 0.07,
    "plate_offsets": None,
}


def canonical_digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def day_value(value):
    if type(value) is int and value >= 0:
        return value
    if isinstance(value, str) and re.fullmatch(r"0|[1-9][0-9]*", value):
        return int(value)
    raise ValueError("Visit day must be an explicit nonnegative integer")


def source_stat(path):
    p = plain(path)
    s = p.stat()
    if not stat.S_ISREG(s.st_mode) or not os.access(p, os.R_OK) or not s.st_mode & 0o444:
        raise ValueError("Require readable regular source")
    return {
        "size_bytes": s.st_size,
        "mtime_ns": s.st_mtime_ns,
        "device": s.st_dev,
        "inode": s.st_ino,
    }


def channel_index(names, target):
    indices = [
        i
        for i, name in enumerate(names)
        if isinstance(name, str)
        and re.search(r"(?<![0-9])" + re.escape(target) + r"(?![0-9])", name)
    ]
    if len(indices) != 1:
        raise ValueError("Absent/ambiguous named channel: " + target)
    return indices[0]


def validate_legacy_contract(contract):
    c = validate_contract(contract)
    if (
        c["sites"] != ["stored_observation_coverage_unresolved"]
        or c["expected_axes"] != "CYX"
        or c["expected_dtype"] != "uint16"
        or not c.get("expected_shape")
        or c["channels"] != {"alignment": "488", "phenotype": "561"}
        or set(c["reporter_wells"]) != {w for w in c["wells"] if w[0] in "EFIJMN"}
    ):
        raise ValueError("Unsupported legacy channel/site/axis/dtype/reporter configuration")
    if (
        c.get("processing_stage") != STAGE
        or c.get("source_identity_policy") != "TMEM_FILENAME_WELL_DAY_SEQ_V1"
        or c.get("source_lineage")
        != {"experiment_id": c["experiment_id"], "plate_id": c["plate_id"]}
    ):
        raise ValueError("Explicit stored-field stage and declared source lineage required")
    return c


def validate_header(header, contract):
    sizes = header.get("sizes", {})
    require_legacy_single_observation(sizes, 1)
    if (
        header.get("is_rgb") is not False
        or header.get("axes") != "CYX"
        or set(sizes) != set("CYX")
        or any(type(v) is not int or v <= 0 for v in sizes.values())
        or header.get("shape") != [sizes.get(x) for x in "CYX"]
        or header["shape"] != contract["expected_shape"]
        or header.get("dtype") != contract["expected_dtype"]
    ):
        raise ValueError("Unsupported fluorescence axes/shape/dtype (not brightfield/RGB)")
    channels = header.get("channels", [])
    names = [v.get("name") if isinstance(v, dict) else v for v in channels]
    if len(names) != sizes["C"] or any(not isinstance(n, str) or not n for n in names):
        raise ValueError("Channel count/names disagree with C axis")
    indices = {k: channel_index(names, target) for k, target in contract["channels"].items()}
    if len(set(indices.values())) != len(indices):
        raise ValueError("Structural and phenotype channels resolve to the same slot")
    # Do not erase instrument conflicts: reported labels are not optical authentication.
    return {
        "ordered_channel_names": names,
        "channel_indices": indices,
        "header": header,
        "optical_identity": "UNRESOLVED",
        "physical_coverage": "COVERAGE_UNRESOLVED",
    }


def preflight_selection(rows, contract, *, inspect_header=None, complete=True):
    """Inspect headers, never pixels. Identity is filename-declared, not physical proof."""
    c = validate_legacy_contract(contract)
    if inspect_header is None:
        from .acquisition_inventory import inspect_nd2_header

        inspect_header = inspect_nd2_header
    expected = {(w, d) for w in c["wells"] for d in c["visits"]}
    seen, paths, inodes, observations = set(), set(), set(), []
    orders = {}
    for row in rows:
        well, day = row.get("well"), day_value(row.get("day"))
        key = (well, day)
        if key in seen or key not in expected:
            raise ValueError("Duplicate/extra observation identity")
        seen.add(key)
        p = plain(row["path"])
        before = source_stat(p)
        inode = (before["device"], before["inode"])
        if p.suffix.lower() != ".nd2" or p in paths or inode in inodes:
            raise ValueError("Duplicate/unsupported source file")
        paths.add(p)
        inodes.add(inode)
        names = re.findall(r"Well([A-Z][0-9]{2})(?![0-9])", p.name, re.IGNORECASE)
        days = re.findall(r"Day[_ -]?([0-9]+)(?![0-9])", p.name, re.IGNORECASE)
        seq = re.findall(r"Seq([0-9]+)(?![0-9])", p.name, re.IGNORECASE)
        if (
            len(names) != 1
            or len(days) != 1
            or len(seq) != 1
            or names[0].upper() != well
            or int(days[0]) != day
            or row.get("site_fov") != "Seq" + seq[0]
            or "brightfield" in p.name.lower()
            or row.get("file_name", p.name) != p.name
        ):
            raise ValueError("Filename well/day/modality/sequence identity mismatch")
        valid = row.get("mcherry_analysis_valid")
        if not (type(valid) is bool or isinstance(valid, str) and valid in ("True", "False")) or (
            valid in (True, "True")
        ) != (well in c["reporter_wells"]):
            raise ValueError("Reporter policy mismatch")
        info = validate_header(inspect_header(p), c)
        if well in orders and orders[well] != info["ordered_channel_names"]:
            raise ValueError("Channel ordering changed across visits")
        orders[well] = info["ordered_channel_names"]
        if source_stat(p) != before:
            raise ValueError("Source changed during header inspection")
        observations.append(
            {
                "well": well,
                "day": day,
                "path": str(p),
                "site_fov": row["site_fov"],
                "source_stat": before,
                **info,
            }
        )
    if complete and seen != expected:
        raise ValueError("Missing observations: " + str(sorted(expected - seen)))
    return {
        "schema_version": "tmem.plate_preflight.v1",
        "contract_sha256": contract_digest(c),
        "processing_stage": c["processing_stage"],
        "declared_lineage": c["source_lineage"],
        "identity_assurance": "FILENAME_CONTAINER_AGREEMENT_NOT_PHYSICAL_AUTHENTICATION",
        "source_integrity_assurance": "HEADER_AND_STAT_ONLY_CONTENT_HASH_BOUND_BY_EXECUTOR",
        "observations": sorted(
            observations, key=lambda r: (r["well"], c["visits"].index(r["day"]))
        ),
    }


def source_tree_fingerprint(root):
    root = plain(root)
    files = sorted(
        p for prefix in ("src/tmem_align", "scripts") for p in (root / prefix).rglob("*.py")
    )
    if not files:
        raise ValueError("Empty scientific source tree")
    return {str(p.relative_to(root)): sha(plain(p)) for p in files}


def runtime_fingerprint(version=importlib.metadata.version):
    return {
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "packages": {
            name: version(name)
            for name in ("nd2", "numpy", "scipy", "pandas", "scikit-image", "tifffile", "dask")
        },
    }


def build_run_binding(root, config_path, selection_path, contract, *, runtime=None):
    from dataclasses import asdict

    from tmem_align import registration_qc
    from tmem_align.analysis.mcherry_metrics import MCherryMetricConfig

    root, config_path, selection_path = plain(root), plain(config_path), plain(selection_path)
    if json.loads(config_path.read_text()) != contract:
        raise ValueError("Configuration contents differ from declared contract")
    frozen = plain(root / contract["frozen_processing_config"])
    if not frozen.is_relative_to(root) or not frozen.is_file():
        raise ValueError("Missing/outside frozen reference configuration")
    try:
        head = subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
        ).strip()
    except subprocess.CalledProcessError:
        head = None
    return {
        "schema_version": "tmem.well_checkpoint.run.v2",
        "source_version_context": head,
        "source_tree_sha256": source_tree_fingerprint(root),
        "contract": contract,
        "contract_sha256": contract_digest(contract),
        "dataset_config_sha256": sha(config_path),
        "selection_sha256": sha(selection_path),
        "input_document_sha256": {str(p): sha(p) for p in (config_path, selection_path, frozen)},
        "frozen_reference_config": {
            "path": str(frozen.relative_to(root)),
            "sha256": sha(frozen),
            "payload": json.loads(frozen.read_text()),
            "applied_by_legacy_worker": False,
        },
        "parameters": PARAMETERS,
        "mcherry_metric_defaults": asdict(MCherryMetricConfig()),
        "registration_qc_defaults": {
            k: v for k, v in vars(registration_qc).items() if k.startswith("DEFAULT_")
        },
        "phenotype_policy": "REPORTER_ONLY_TECHNICAL_UNAPPROVED_STABLE_CHANNEL_MASK",
        "runtime": runtime if runtime is not None else runtime_fingerprint(),
        "receipt_schema": "tmem.well_checkpoint.v2",
        "aggregate_schema": "tmem.well_checkpoint.aggregate.v2",
    }
