#!/usr/bin/env python3
"""Generate actual per-position ND2 stage graphics before site matching exists.

This is an explicitly bounded local/pilot diagnostic. It does not assert any
cross-day correspondence, whole-well coverage, tracking identity or IC benefit.
"""
import argparse
import json
from pathlib import Path
import re
import sys

import full_dataset as f
import project_adapter as a


def channel_map(header, profile):
    names = header["channels"]
    labels = profile.get("metadata_labels", {})
    mapping = {}
    for role in profile["channels"]:
        if role in labels:
            matches = [n for n in names if n == labels[role]]
        elif role in {"405", "488", "561"}:
            matches = [n for n in names if re.search(r"(?<!\d)" + role + r"(?!\d)", n)]
        else:
            matches = [n for n in names if n == role]
        if len(matches) != 1:
            raise ValueError(f"Cannot uniquely map {role} from actual metadata: {names}; supply metadata_labels in profile")
        mapping[role] = matches[0]
    if len(set(mapping.values())) != len(mapping):
        raise ValueError("Two roles map to the same optical channel")
    return mapping


def run(inventory, profile, repo, out, max_files=4, wells=None, days=None):
    import numpy as np
    out = f.new_directory(out, repo, inventory["raw_root"])
    source = f.source_binding(repo)
    _, tracker, preprocessing = a.attach_repo(repo)
    candidates = [h for h in inventory["headers"] if not h["error"] and h["modality"] == "fluorescence"
                  and (not wells or h["well"] in wells) and (not days or h["day"] in days)]
    # Prefer a balanced 2-well x 2-visit pilot when named; no hidden truncation.
    candidates.sort(key=lambda h: (h["day"], h["well"], h["path"]))
    selected = candidates[:max_files]
    if max_files < 1 or not selected:
        raise ValueError("No selected original fluorescence files")
    report = {"source": source, "files_available_after_filters": len(candidates), "max_files": max_files,
              "selected_files": len(selected), "all_filtered_files_processed": len(selected) == len(candidates),
              "cross_day_site_correspondence_verified": False, "whole_well_coverage_verified": False,
              "accepted_identities": 0, "results": []}
    for h in selected:
        if h["sizes"].get("T", 1) > 1 or h["sizes"].get("Z", 1) > 1:
            raise ValueError("T/Z>1 requires an explicit validated policy; no silent first-plane selection")
        if f.stat_record(h["path"]) != h["stat"]:
            raise ValueError("Original changed since header inventory")
        checksum = f.digest(h["path"])
        mapping = channel_map(h, profile)
        for position in range(h["declared_positions"]):
            key = f"{h['well']}_day{h['day']}_P{position}_{checksum[:8]}"
            case = out / key
            case.mkdir()
            obs = {"path": h["path"], "header": h, "position": position, "time": 0, "z": 0,
                   "channel_map": mapping}
            observer = a.Observer(case / "stages", profile["channels"], profile["luts"], profile["identity_channel"],
                                  arrays=profile["processing"].get("trace_arrays", False))
            record = {"case": key, "original_path_private": h["path"], "original_sha256": checksum,
                      "position_index": position, "site_identity": "unverified; P is extraction index only",
                      "ic_applied": False, "alignment": "unavailable: cross-day site mapping not authenticated",
                      "tracking": "unavailable: no cross-day identity asserted"}
            try:
                raw, remap = a.read_selection(obs, profile["channels"], profile["processing"]["max_read_bytes"])
                corrected = preprocessing.preprocess_image(raw, background_radius=profile["processing"].get("background_radius"),
                                                           trace=observer, trace_prefix="preprocess")
                np.save(case / "EXACT_SELECTED_ORIGINAL.npy", raw, allow_pickle=False)
                np.save(case / "PREPROCESSED.npy", corrected, allow_pickle=False)
                record["channel_remap"] = remap
                if profile["name"] == "february_neuron" and profile["processing"].get("candidate_tracking"):
                    image = corrected[profile["channels"].index("488")]
                    y, x = tracker.auto_day8_anchor(image, radius=12)
                    try:
                        _, meta = tracker.segment_neuron_in_box(image, y, x, 128, 180, trace=observer,
                                                                trace_prefix="local_segmentation")
                        record["segmentation"] = a.clean(meta)
                    except RuntimeError as error:
                        if isinstance(error, tracker.SegmentationTraceError):
                            raise
                        record["segmentation"] = {"status": "failed", "reason": str(error)}
                if checksum != f.digest(h["path"]) or f.stat_record(h["path"]) != h["stat"]:
                    raise ValueError("Original changed during preview extraction")
                record["status"] = "completed_diagnostic"
            except Exception as error:
                record.update(status="failed", error=type(error).__name__ + ": " + str(error))
            finally:
                observer.finish()
                record["outputs"] = f.output_records(case)
                f.atomic_json(case / "PREVIEW_RECEIPT_PRIVATE.json", record)
                report["results"].append(record)
                f.atomic_json(out / "PREVIEW_STATUS_PRIVATE.json", report)
    report["source_unchanged"] = f.source_binding(repo) == source
    report["passed_extraction"] = all(r["status"] == "completed_diagnostic" for r in report["results"]) and report["source_unchanged"]
    f.atomic_json(out / "PREVIEW_STATUS_PRIVATE.json", report)
    links = [f'<li><a href="{r["case"]}/stages/ACTUAL_IMAGE_FLOWCHART.svg">{r["case"]}: {r["status"]}</a></li>' for r in report["results"]]
    (out / "OPEN_ACTUAL_IMAGE_FLOWCHARTS.html").write_text('<!doctype html><meta charset="utf-8"><title>Actual ND2 pilot graphics</title><h1>Actual original ND2 stage graphics</h1><p>Per-position diagnostics; cross-day identity, calibration and whole-well coverage remain unverified.</p><ul>' + "".join(links) + "</ul>")
    return report


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for name in ["inventory", "profile", "repo", "out"]:
        p.add_argument("--" + name, type=Path, required=True)
    p.add_argument("--max-files", type=int, default=4)
    p.add_argument("--wells", nargs="+")
    p.add_argument("--days", nargs="+", type=int)
    args = p.parse_args()
    try:
        result = run(f.load(args.inventory), f.load(args.profile), args.repo, args.out, args.max_files, args.wells, args.days)
        print(json.dumps({k: v for k, v in result.items() if k not in {"source", "results"}}, indent=2))
        print("OPEN=" + str(args.out / "OPEN_ACTUAL_IMAGE_FLOWCHARTS.html"))
        raise SystemExit(0 if result["passed_extraction"] else 2)
    except Exception as exc:
        print("STOP: " + str(exc), file=sys.stderr)
        raise SystemExit(2)
