"""Shared audit command utilities; no implicit acquisition-axis selection."""
import importlib.metadata
import hashlib
import inspect
import subprocess
from pathlib import Path

import numpy as np

from .display import LUT, longitudinal_lut
from .evidence import Evidence


def dependency_check():
    import imageio  # noqa: F401
    import nd2  # noqa: F401
    import pytest  # noqa: F401
    import tifffile  # noqa: F401
    from skimage.morphology import remove_small_objects
    if "max_size" not in inspect.signature(remove_small_objects).parameters:
        raise RuntimeError("Reference renderer requires remove_small_objects(max_size=...). "
                           "Use the isolated scikit-image 0.26 environment in the instructions.")
    return {name: importlib.metadata.version(name) for name in
            ["numpy", "scipy", "scikit-image", "tifffile", "nd2", "pytest", "imageio"]}


def context(title, evidence_type, **kwargs):
    root = Path(__file__).resolve().parents[3]
    try:
        top = subprocess.run(["git", "-C", str(root), "rev-parse", "--show-toplevel"],
                             text=True, capture_output=True, check=False)
        own_checkout = top.returncode == 0 and Path(top.stdout.strip()).resolve() == root
    except OSError:
        own_checkout = False
    def git(*args):
        if not own_checkout:
            return "unavailable-source-snapshot"
        try:
            p = subprocess.run(["git", "-C", str(root), *args], text=True,
                               capture_output=True, check=False)
        except OSError:
            return "unavailable-source-snapshot"
        return p.stdout.strip() if p.returncode == 0 else "unavailable-source-snapshot"
    code_files = list((root / "src/tmem_align/audit_v1").glob("*.py"))
    code_files += [root / "scripts" / name for name in ["run_tmem_audit.py",
                   "audit_curated_neurons.py", "assemble_tmem_well.py", "register_tmem_well.py",
                   "run_claire_audit.sh"]]
    return dict(title=title, evidence_type=evidence_type,
                baseline_commit="4a8c4dd7e37637e11ae4bd45ea632c4023e5025f",
                git_checkout=own_checkout,
                checkout_commit=git("rev-parse", "HEAD"), working_tree=git("status", "--short"),
                audit_code_sha256={str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
                                   for p in sorted(code_files)},
                channels={"0": "405", "1": "561", "2": "488"}, **kwargs)


def emit_stages(out, stages, lut, *, channel, provenance, diagnostics):
    e = Evidence(out, provenance)
    for name, array in stages.items():
        a = np.asarray(array)
        display = LUT(0, 1, source="boolean mask") if a.dtype == bool else lut
        if name.endswith("dog") or name.endswith("labels"):
            display = longitudinal_lut(a, source="diagnostic only; this stage's p1/p99.6")
        e.stage(name, a, display, channel=channel, parameters=diagnostics)
    e.finish(diagnostics)
    return e


def read_cyx(path):
    import tifffile
    from .contracts import require_cyx
    with tifffile.TiffFile(path) as tif:
        if tif.series[0].axes != "CYX":
            raise ValueError(f"{path}: require explicitly extracted CYX OME-TIFF")
        array = tif.asarray()
    return require_cyx(array)


def input_record(path):
    p = Path(path).resolve()
    record = dict(path=str(p), size_bytes=p.stat().st_size, mtime_ns=p.stat().st_mtime_ns)
    if p.stat().st_size <= 128 * 1024**2:
        digest = hashlib.sha256()
        with p.open("rb") as f:
            for block in iter(lambda: f.read(1024**2), b""):
                digest.update(block)
        record["file_sha256"] = digest.hexdigest()
    else:
        record["file_sha256"] = None
        record["hash_note"] = "Large input: path/stat plus exact per-stage array hashes recorded"
    return record
