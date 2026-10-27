#!/usr/bin/env python3
"""Read-only 488 panel review: agreement/sensitivity, never accuracy or acceptance."""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import math
import os
import re
import statistics
from collections import Counter
from pathlib import Path
from urllib.parse import quote

DAYS = [8, 12, 16, 20, 25, 29, 32, 36, 39]
FLOW = """flowchart LR
    unavailable["Unavailable: raw detector pixels, IC fields, historical tiles/transforms"]
    registered["Supplied registered TCYX stack"] --> crops["Frozen 128px crops: 488 identity only"]
    crops --> masks["488 segmentation and fixed identity core"]
    masks --> roi["Unchanged 488-derived ROI"]
    roi --> diagnostic["561 diagnostic partition; no accepted export"]
    masks --> qc["Preserve every failed visit and ownership concern"]
    qc --> release["Release blocked: nine-visit gates plus independent review required"]
    crops --> proposals["Radius/area/LUT alternatives: display or sensitivity only, never adopted"]
"""


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def bound_file(root, relative, hashes):
    relative = Path(relative)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("Unsafe trace path")
    path = root / relative
    if not path.resolve().is_relative_to(root.resolve()) or any(
        p.is_symlink() for p in [path, *path.parents] if p != root.parent
    ):
        raise ValueError("Linked or escaped trace path")
    if hashes.get(relative.as_posix()) != digest(path):
        raise ValueError("Trace artifact checksum mismatch: " + str(relative))
    return path


def distribution(values):
    values = [float(v) for v in values]
    if not values or not all(math.isfinite(v) for v in values):
        raise ValueError("Expected finite nonempty diagnostic values")
    return {"min": min(values), "median": statistics.median(values), "max": max(values)}


def tracking_agreement(tracking):
    if tracking.get("all_proposals_unadopted") is not True:
        raise ValueError("Tracking proposals must remain unadopted")
    primary = str(tracking["primary_search_radius_px"])
    grid = tracking["results_by_radius"]
    if primary not in grid:
        raise ValueError("Missing primary diagnostic radius")
    for rows in grid.values():
        if [r["day"] for r in rows] != DAYS or any(r.get("adopted") is not False for r in rows):
            raise ValueError("Require nine ordered, unadopted visits")
    result = {}
    for radius, rows in grid.items():
        differences = [
            math.dist(r["candidate_anchor_yx_px"], p["candidate_anchor_yx_px"])
            for r, p in zip(rows, grid[primary])
        ]
        result[radius] = {
            "departure_from_frozen_anchor_px": distribution(
                r["displacement_from_stored_anchor_px"] for r in rows
            ),
            "departure_from_primary_proposal_px": distribution(differences),
            "visits_differing_from_primary_over_20px": sum(v > 20 for v in differences),
            "descriptive_threshold_not_an_acceptance_gate": True,
        }
    return result


def mask_overlap(roi, mask):
    import numpy as np

    roi, mask = np.asarray(roi, dtype=bool), np.asarray(mask, dtype=bool)
    if roi.shape != mask.shape or roi.ndim != 2:
        raise ValueError("Require shape-matched YX masks")
    intersection = int((roi & mask).sum())
    union = int((roi | mask).sum())
    return {
        "roi_area_px": int(roi.sum()),
        "primary_mask_area_px": int(mask.sum()),
        "roi_supported_by_primary_488_mask_fraction": intersection / roi.sum()
        if roi.any()
        else None,
        "roi_mask_IoU": intersection / union if union else None,
        "agreement_only_not_ROI_ownership": True,
    }


def inspect_case(trace, out, nid):
    import numpy as np
    from PIL import Image, ImageDraw

    manifest = json.loads((trace / "manifest.json").read_text())
    if (
        not manifest.get("complete")
        or manifest.get("real_accepted_ids") != []
        or manifest.get("scientific_inference_ready") is not False
    ):
        raise ValueError("Require finalized unaccepted diagnostic trace")
    hashes = manifest["files"]

    def read(name):
        return json.loads(bound_file(trace, name, hashes).read_text())

    summary = read("summary.json")
    if (
        summary.get("software_execution_complete") is not True
        or summary.get("real_accepted_ids") != []
        or summary.get("scientific_inference_ready") is not False
        or summary.get("production_eligible") is not False
    ):
        raise ValueError("Scientific safeguards are missing")
    tracking, sensitivity = read("tracking_comparison.json"), read("parameter_sensitivity.json")
    if sensitivity.get("all_settings_unadopted") is not True:
        raise ValueError("Segmentation alternatives must remain unadopted")
    records = {s["stage"]: s for s in manifest["stages"]}

    def array(name):
        path = records[name]["artifacts"]["numeric"]["path"]
        return np.load(bound_file(trace, path, hashes), allow_pickle=False)

    geometry = read("crop_geometry.json")
    roi = array("phenotype_roi_holes_filled") if "phenotype_roi_holes_filled" in records else None
    core = array("primary_identity_core") if "primary_identity_core" in records else None
    canvas = Image.new("RGB", (1152, 1296), "#111111")
    draw = ImageDraw.Draw(canvas)
    overlap = []
    colors = {"40": "#00ffff", "60": "#ff40ff", "80": "#ff9d00"}
    for i, day in enumerate(DAYS):
        name = f"visit_{i:02d}_registered_488"
        record = records[name]
        preview = Image.open(
            bound_file(trace, record["artifacts"]["preview"]["path"], hashes)
        ).convert("RGB")
        if preview.size != (128, 128):
            raise ValueError("Expected unchanged 128-pixel crops")
        # Display-only nearest-neighbour enlargement; quantitative arrays stay unchanged.
        preview = preview.resize((384, 384), Image.Resampling.NEAREST)
        pd = ImageDraw.Draw(preview)
        for mask, color in ((roi, "#ff5050"), (core, "#ffff00")):
            if mask is not None:
                inside = np.pad(mask.astype(bool), 1)
                eroded = (
                    inside[1:-1, 1:-1]
                    & inside[:-2, 1:-1]
                    & inside[2:, 1:-1]
                    & inside[1:-1, :-2]
                    & inside[1:-1, 2:]
                )
                for y, x in np.argwhere(mask.astype(bool) & ~eroded):
                    pd.rectangle(
                        (int(x) * 3, int(y) * 3, int(x) * 3 + 2, int(y) * 3 + 2), fill=color
                    )
        ay, ax = geometry[i]["anchor_yx_crop_px"]
        pd.line((ax * 3 - 8, ay * 3, ax * 3 + 8, ay * 3), fill="white", width=2)
        pd.line((ax * 3, ay * 3 - 8, ax * 3, ay * 3 + 8), fill="white", width=2)
        off_crop = []
        for radius, rows in tracking["results_by_radius"].items():
            cy, cx = rows[i]["candidate_anchor_yx_px"]
            y, x = cy - geometry[i]["bounds"]["y0"], cx - geometry[i]["bounds"]["x0"]
            if 0 <= y < 128 and 0 <= x < 128:
                pd.ellipse(
                    (x * 3 - 5, y * 3 - 5, x * 3 + 5, y * 3 + 5),
                    outline=colors.get(radius, "white"),
                    width=2,
                )
            else:
                off_crop.append(radius)
        x0, y0 = (i % 3) * 384, (i // 3) * 432
        valid = summary["valid_488_by_day"][str(day)]
        draw.text((x0 + 5, y0 + 3), f"{nid} Day {day} | QC {valid}", fill="white")
        draw.text(
            (x0 + 5, y0 + 18), "Off-crop radii: " + (",".join(off_crop) or "none"), fill="white"
        )
        canvas.paste(preview, (x0, y0 + 40))
        if roi is not None:
            overlap.append(
                dict(
                    day=day,
                    valid_488=valid,
                    **mask_overlap(roi, array(f"primary_identity_input_{i:02d}")),
                )
            )
    canvas.save(out / (nid + "_488.png"))
    # Show the already-recorded larger registered search window without changing
    # the fixed measurement crop. "raw_search" means before local normalization,
    # not raw detector data or a reconstructed historical alignment input.
    largest = max(tracking["results_by_radius"], key=int)
    context_names = [f"tracking_r{int(largest):03d}_visit_{i:02d}_raw_search" for i in range(9)]
    context_available = all(name in records for name in context_names)
    if context_available:
        context = Image.new("RGB", (1206, 1350), "#111111")
        cd = ImageDraw.Draw(context)
        for i, name in enumerate(context_names):
            record = records[name]
            preview = Image.open(
                bound_file(trace, record["artifacts"]["preview"]["path"], hashes)
            ).convert("RGB")
            y0, y1, x0, x1 = record["details"]["bounds_y0_y1_x0_x1"]
            if preview.size != (x1 - x0, y1 - y0):
                raise ValueError("Search preview shape does not match registered bounds")
            scale = min(402 // preview.width, 402 // preview.height)
            if scale < 1:
                raise ValueError("Search preview exceeds declared display tile")
            preview = preview.resize(
                (preview.width * scale, preview.height * scale), Image.Resampling.NEAREST
            )
            pd = ImageDraw.Draw(preview)
            bounds = geometry[i]["bounds"]
            pd.rectangle(
                (
                    (bounds["x0"] - x0) * scale,
                    (bounds["y0"] - y0) * scale,
                    (bounds["x1"] - x0) * scale,
                    (bounds["y1"] - y0) * scale,
                ),
                outline="white",
            )
            ay, ax = geometry[i]["anchor_yx_registered_px"]
            pd.line(
                (
                    (ax - x0) * scale - 6,
                    (ay - y0) * scale,
                    (ax - x0) * scale + 6,
                    (ay - y0) * scale,
                ),
                fill="white",
                width=2,
            )
            pd.line(
                (
                    (ax - x0) * scale,
                    (ay - y0) * scale - 6,
                    (ax - x0) * scale,
                    (ay - y0) * scale + 6,
                ),
                fill="white",
                width=2,
            )
            for radius, rows in tracking["results_by_radius"].items():
                cy, cx = rows[i]["candidate_anchor_yx_px"]
                x, y = (cx - x0) * scale, (cy - y0) * scale
                pd.ellipse(
                    (x - 5, y - 5, x + 5, y + 5), outline=colors.get(radius, "white"), width=2
                )
            x, y = (i % 3) * 402, (i // 3) * 450
            cd.text((x + 5, y + 4), f"{nid} Day {DAYS[i]} | registered 488 search", fill="white")
            context.paste(preview, (x, y + 40))
        context.save(out / (nid + "_488_search_context.png"))
    return {
        "neuron_id": nid,
        "diagnostic_status": summary["diagnostic_status"],
        "valid_488_visit_count": summary["valid_488_visit_count"],
        "core_area_px": summary["core_area_px"],
        "secondary_soma_single_pass": summary["automated_secondary_soma_single_pass"],
        "stage_status_counts": manifest["stage_status_counts"],
        "larger_registered_search_context_available": context_available,
        "trace_manifest_sha256": digest(trace / "manifest.json"),
        "tracking_agreement": tracking_agreement(tracking),
        "roi_mask_agreement": overlap,
        "segmentation_sensitivity": sensitivity["settings"],
        "independent_labels_supplied_for_this_panel": False,
        "accuracy_established": False,
        "all_proposals_unadopted": True,
        "reviewed_or_accepted": False,
    }


def report(benchmark, out):
    benchmark, out = Path(benchmark).resolve(), Path(out).resolve()
    repo = Path(__file__).resolve().parents[1]
    if out.is_relative_to(repo) or out.is_relative_to(benchmark):
        raise ValueError("Review output must remain outside repository and immutable benchmark")
    state = json.loads((benchmark / "benchmark_summary.json").read_text())
    if state["status"] == "running":
        raise ValueError("Wait for a checkpointed benchmark status before reporting")
    if (
        state["status"] not in {"completed_pending_scientific_review", "partial_or_blocked"}
        or state.get("master_and_configuration_unchanged") is not True
    ):
        raise ValueError("Require unchanged source inputs and a usable benchmark checkpoint")
    if state.get("real_accepted_ids") != [] or state.get("scientific_inference_ready") is not False:
        raise ValueError("Unaccepted diagnostic benchmark required")
    out.mkdir(parents=True, exist_ok=False)
    cases, links = [], []
    for nid in state["selected_neuron_ids"]:
        if not re.fullmatch(r"(E05|F05|I05|J05|M05|N05)_N\d{3}", nid):
            raise ValueError("Invalid neuron identifier")
        status = state["results"][nid]["status"]
        if status == "software_completed":
            cases.append(inspect_case(benchmark / "tracks" / nid, out, nid))
            gallery = quote(os.path.relpath(benchmark / "tracks" / nid / "index.html", out))
            links.append(
                f'<h2>{html.escape(nid)}</h2><p><a href="{gallery}">Full numeric-stage gallery and provenance</a></p>'
                f'<img src="{nid}_488.png" alt="Nine 488 visits for {nid}">'
            )
            if cases[-1]["larger_registered_search_context_available"]:
                links.append(
                    f"<details><summary>Larger registered 488 search context (white rectangle = unchanged measurement crop)</summary>"
                    f'<img src="{nid}_488_search_context.png" alt="Registered 488 search context for {nid}"></details>'
                )
        else:
            links.append(f"<p>{html.escape(nid)}: {html.escape(status)}; not evaluated.</p>")
    compact = {
        "schema_version": "tmem.portable_panel_review.v1",
        "benchmark_summary_sha256": digest(benchmark / "benchmark_summary.json"),
        "selected_neuron_ids": state["selected_neuron_ids"],
        "execution_counts": dict(Counter(r["status"] for r in state["results"].values())),
        "original_master_sha256": state["input_files"]["master"]["sha256"],
        "configuration_sha256": state["configuration"]["sha256"],
        "days": DAYS,
        "cases": cases,
        "real_accepted_ids": [],
        "scientific_inference_ready": False,
        "interpretation": "488 agreement and sensitivity only; frozen anchors are not ground truth.",
    }
    (out / "panel_summary.json").write_text(json.dumps(compact, indent=2, allow_nan=False) + "\n")
    (out / "processing_flow.mmd").write_text(FLOW)
    with (out / "review_template.csv").open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(
            [
                "neuron_id",
                "day",
                "trace_manifest_sha256",
                "reviewer",
                "same_cell_yes_no_uncertain",
                "ROI_ownership_clear_uncertain_contaminated",
                "notes",
            ]
        )
        for case in cases:
            for day in DAYS:
                writer.writerow(
                    [case["neuron_id"], day, case["trace_manifest_sha256"], "", "", "", ""]
                )
    (out / "index.html").write_text(
        '<!doctype html><meta charset="utf-8"><title>488 panel review</title>'
        "<style>body{font:16px system-ui;max-width:1200px;margin:30px auto}img{width:100%;image-rendering:pixelated}</style>"
        "<h1>488 diagnostic review — not accepted tracks</h1>"
        "<p>Fixed LUT 0–4095; fixed crops use 3× nearest-neighbour display only; search contexts use an integer enlargement. White cross: frozen anchor. "
        "Circles: radius 40 cyan, 60 magenta, 80 orange. Yellow: fixed core; red: fixed ROI. "
        "Off-crop proposals are listed, not silently clipped into the image. "
        "No 561 data were read by this report. These marks do not establish cell identity or ROI ownership.</p>"
        "<p>Registered stack → frozen 488 crops → masks/core → fixed ROI → 561 diagnostic partition. "
        "Raw IC/stitching/history unavailable. Release blocked pending all-nine gates and independent review. "
        '<a href="processing_flow.mmd">Compact flowchart</a> · '
        '<a href="review_template.csv">Blank independent-review sheet</a> · '
        '<a href="panel_summary.json">Bound numeric comparison</a></p>' + "".join(links)
    )
    return compact


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    report(args.benchmark, args.out)
