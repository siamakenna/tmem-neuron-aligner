#!/usr/bin/env python3
"""Save actual production intermediates; no accepted measurements or review changes."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def _image(path, expected_axes):
    import numpy as np
    path = Path(path)
    if path.suffix.lower() == ".npy":
        if expected_axes != "CYX":
            raise ValueError("Registered stacks require a TIFF with explicitTCYX axes")
        return np.load(path, allow_pickle=False)
    if path.suffix.lower() not in {".tif", ".tiff"}:
        raise ValueError("Supply NPY(CYX) or an explicitly labelled TIFF")
    import tifffile
    with tifffile.TiffFile(path) as tif:
        if len(tif.series) != 1 or tif.series[0].axes != expected_axes:
            raise ValueError(f"Require one TIFF series with explicit{expected_axes} axes")
        return tif.asarray()


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="mode", required=True)
    track = sub.add_parser("registered-track", help="Trace stored anchors; historicalIC/alignment remain unavailable")
    track.add_argument("--stack", type=Path, required=True)
    track.add_argument("--master", type=Path, required=True)
    track.add_argument("--neuron-id", required=True)
    pair = sub.add_parser("raw-pair", help="Execute supplied detector-coordinateCYX correction and488 alignment")
    pair.add_argument("--reference", type=Path, required=True)
    pair.add_argument("--moving", type=Path, required=True)
    pair.add_argument("--flatfield", type=Path)
    pair.add_argument("--flatfield-coordinate-system", choices=["detector"])
    pair.add_argument("--darkfield", type=float)
    pair.add_argument("--background-radius", type=int)
    for command in [track, pair]:
        command.add_argument("--out", type=Path, required=True)
        command.add_argument("--config", type=Path)
    args = p.parse_args(argv)
    from tmem_align.audit_v1.pipeline_diagnostics import (
        file_record, load_config, trace_raw_pair, trace_registered_track, verify_trace)
    cfg = load_config(args.config)
    paths = [args.stack, args.master] if args.mode == "registered-track" else [args.reference, args.moving]
    if args.mode == "raw-pair" and args.flatfield:
        if args.flatfield.suffix.lower() != ".npy":
            p.error("--flatfield must be a pickle-free matching detector-coordinate.npy")
        paths.append(args.flatfield)
    if args.config:
        paths.append(args.config)
    before = [file_record(path) for path in paths]
    metadata = dict(inputs=before, invoked_mode=args.mode)
    if args.mode == "registered-track":
        import pandas as pd
        manifest = trace_registered_track(_image(args.stack, "TCYX"), pd.read_csv(args.master),
            args.neuron_id, args.out, config=cfg, metadata=metadata)
    else:
        import numpy as np
        manifest = trace_raw_pair(_image(args.reference, "CYX"), _image(args.moving, "CYX"), args.out,
            flatfield=np.load(args.flatfield, allow_pickle=False) if args.flatfield else None,
            flatfield_coordinate_system=args.flatfield_coordinate_system,
            darkfield=args.darkfield, background_radius=args.background_radius,
            config=cfg, metadata=metadata)
    if before != [file_record(path) for path in paths]:
        # This marker intentionally invalidates the finished inventory. A
        # consumer cannot verify this directory while overlooking a changed
        # source that was detected only after processing completed.
        import json
        (args.out / "SOURCE_CHANGED.json").write_text(json.dumps({
            "status": "unusable_source_changed", "real_accepted_ids": [],
            "scientific_inference_ready": False}, indent=2) + "\n")
        raise RuntimeError("A source file changed during execution; this result must not be used")
    verify_trace(args.out)
    status = manifest["summary"]["diagnostic_status"]
    print("TMEM_DIAGNOSTIC_STATUS=" + status)
    print("TMEM_DIAGNOSTIC_MANIFEST=" + str((args.out / "manifest.json").resolve()))
    print("No review was approved and no accepted metricsCSV was written.")
    # A diagnosed scientific rejection is completed diagnostic software work.
    # Explicit JSON status and gates prevent this exit code granting acceptance.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
