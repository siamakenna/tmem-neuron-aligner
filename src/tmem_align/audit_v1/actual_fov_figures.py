"""Image-rich, read-only figures from verified registered-track executions.

This connection reuses observed production arrays. It never segments again,
changes measurement geometry, supplies human labels, or maps original ND2 FOVs
to historical atlas coordinates.
"""

from __future__ import annotations

import base64
import csv
import hashlib
import html
import io
import json
import math
import os
import re
import textwrap
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy.ndimage import label, maximum_filter

from .contracts import Bounds
from .display import LUT
from .stage_trace import array_sha256, verify_trace
from .visualization import propose_lut_bbox, render_preview

SCHEMA = "tmem.actual_fov_figures.v1"
DAYS = (8, 12, 16, 20, 25, 29, 32, 36, 39)
REPO = Path(__file__).resolve().parents[3]
CASE = re.compile(r"[A-P]\d{2}_N\d+\Z")


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024**2), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _plain(path):
    path = Path(os.path.abspath(Path(path).expanduser()))
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("Linked input/output components are not allowed")
    return path


def _child(root, relative):
    relative = Path(relative)
    if relative.is_absolute() or ".." in relative.parts or "\\" in str(relative):
        raise ValueError("Unsafe source artifact path")
    path = _plain(root / relative)
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError("Missing regular source artifact")
    return path


def _json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON field")
            result[key] = value
        return result

    return json.loads(
        Path(path).read_text(),
        object_pairs_hook=unique,
        parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
    )


def _write(path, value):
    data = value if isinstance(value, bytes) else value.encode()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(data)


def _write_json(path, value):
    _write(path, json.dumps(value, indent=2, allow_nan=False) + "\n")


def _csv(path, rows):
    keys = list(dict.fromkeys(key for row in rows for key in row))
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=keys)
    writer.writeheader()
    for row in rows:
        writer.writerow(
            {k: json.dumps(v) if isinstance(v, (list, dict)) else v for k, v in row.items()}
        )
    _write(path, stream.getvalue())


class TraceCase:
    """Verify once, then bind every actual artifact consumed by this report."""

    def __init__(self, root):
        self.root = _plain(root)
        self.bindings = {}
        self.manifest = verify_trace(self.root)
        self.manifest_sha = sha(self.root / "manifest.json")
        self.bindings[str(self.root / "manifest.json")] = self.manifest_sha
        self.meta = self.manifest["metadata"]
        self.nid = self.meta.get("neuron_id")
        if (
            self.meta.get("mode") != "registered-track"
            or not isinstance(self.nid, str)
            or not CASE.fullmatch(self.nid)
            or self.root.name != self.nid
            or self.meta.get("expected_days") != list(DAYS)
            or self.meta.get("input_axes") != "TCYX"
            or "registered" not in self.meta.get("coordinate_system", "")
        ):
            raise ValueError("Require an explicit nine-visit registered-track trace")
        self.stages = {r["stage"]: r for r in self.manifest["stages"]}
        self.cfg = self.meta["parameters"]
        if self.cfg["bbox_size"] != 128:
            raise ValueError("Only the frozen 128-pixel crop is supported")
        self.geometry = self.read_json("crop_geometry.json")
        self.segmentation = self.read_json("parameter_sensitivity.json")
        self.tracking = self.read_json("tracking_comparison.json")
        self.summary = self.read_json("summary.json")
        if (
            len(self.geometry) != 9
            or [r["day"] for r in self.geometry] != list(DAYS)
            or [r["time_index"] for r in self.geometry] != list(range(9))
        ):
            raise ValueError("Crop geometry must contain each chronological visit once")
        self.arrays = {}

    def read(self, relative):
        path = _child(self.root, relative)
        expected = self.manifest["files"].get(relative)
        if not expected or sha(path) != expected:
            raise ValueError("Source is absent from inventory or changed: " + relative)
        self.bindings[str(path)] = expected
        return path

    def read_json(self, relative):
        return _json(self.read(relative))

    def array(self, name, *, optional=False):
        record = self.stages.get(name)
        if record is None or record["status"] != "executed":
            if optional:
                return None
            raise ValueError("Required numeric stage unavailable: " + name)
        if name not in self.arrays:
            artifact = record["artifacts"]["numeric"]
            self.arrays[name] = np.load(self.read(artifact["path"]), allow_pickle=False)
        return self.arrays[name]

    def card(self, name, title=None):
        record = self.stages.get(name)
        caption = "No recorded execution; not replaced with a fake mask."
        image = None
        if record is not None:
            caption = record.get("why", "")
            artifact = record.get("artifacts", {}).get("preview")
            if artifact and record["status"] == "executed":
                path = self.read(artifact["path"])
                image = np.asarray(Image.open(path).convert("RGB"))
        return {
            "title": title or name,
            "image": image,
            "caption": caption,
            "stage": name,
            "status": record["status"] if record else "unavailable",
            "provenance": {
                "trace_manifest_sha256": self.manifest_sha,
                "record": record,
                "coordinate_system": self.meta["coordinate_system"],
            },
        }

    def finish(self):
        for path, expected in self.bindings.items():
            if sha(path) != expected:
                raise ValueError("Trace source changed during figure generation")


def winning_candidate(stages, prefix):
    """Follow the production selected component, not the first threshold tried."""
    chosen = stages.get(prefix + "_selected_component")
    if not chosen or chosen["status"] != "executed":
        return None
    parents = [
        p
        for p in chosen.get("parents", [])
        if re.fullmatch(re.escape(prefix) + r"_candidate_\d+_selection", p)
    ]
    if len(parents) != 1 or parents[0] not in stages:
        raise ValueError("Selected component lacks its actual threshold parent")
    return parents[0].removesuffix("_selection")


def viewing_metrics(image, core, roi, anchor, lut, *, padding=2, min_area=20):
    """Measure viewing footprint and dropped frozen support, never new geometry."""
    a = np.asarray(image)
    for mask in (core, roi):
        if mask is not None and (mask.dtype != bool or mask.shape != a.shape):
            raise ValueError("Frozen support must be a same-coordinate Boolean mask")
    result = []
    for policy in ("visible", "within_range"):
        proposal = propose_lut_bbox(
            a, lut, anchor_yx=anchor, padding=padding, min_area=min_area, range_policy=policy
        )
        bounds = Bounds(**proposal["bounds"]) if proposal["bounds"] else None
        count = (bounds.y1 - bounds.y0) * (bounds.x1 - bounds.x0) if bounds else 0
        row = {
            "policy": policy,
            "status": proposal["status"],
            "proposal": proposal,
            "fixed_box_area_px": int(a.size),
            "displayed_area_px": count,
            "view_area_reduction_fraction": 1 - count / a.size,
            "anchor_in_view": bool(
                bounds and bounds.y0 <= anchor[0] < bounds.y1 and bounds.x0 <= anchor[1] < bounds.x1
            ),
            "measurement_geometry_changed": False,
            "adopted": False,
        }
        for name, mask in (("core", core), ("ROI", roi)):
            total = int(mask.sum()) if mask is not None else None
            retained = int(bounds.crop(mask).sum()) if bounds and mask is not None else 0
            row[name + "_retained_fraction"] = retained / total if total else None
            row[name + "_lost_pixels"] = total - retained if total is not None else None
        row["interpretation"] = (
            "failure_no_view"
            if bounds is None
            else "frozen_support_unavailable_no_retention_claim"
            if core is None or roi is None
            else "degradation_frozen_support_lost"
            if any(row[k] for k in ("core_lost_pixels", "ROI_lost_pixels"))
            else "neutral_same_box"
            if count == a.size
            else "smaller_view_support_retained_not_accuracy"
        )
        result.append(row)
    return result


def peak_statistics(surface, *, minimum_score=0.25, separation=5):
    """8-connected plateaus of local maxima in an11x11 window; no identity truth."""
    a = np.asarray(surface)
    if a.ndim != 2 or not a.size or not np.isfinite(a).all():
        raise ValueError("Correlation surface must be finite nonempty YX")
    maxima = (a == maximum_filter(a, size=2 * separation + 1, mode="constant", cval=-np.inf)) & (
        a >= minimum_score
    )
    components, count = label(maxima, structure=np.ones((3, 3)))
    peaks = []
    for component in range(1, count + 1):
        yy, xx = np.where(components == component)
        values = a[yy, xx]
        order = np.lexsort((xx, yy, -values))
        y, x = int(yy[order[0]]), int(xx[order[0]])
        peaks.append({"y": y, "x": x, "score": float(a[y, x]), "plateau_pixels": len(yy)})
    peaks.sort(key=lambda p: (-p["score"], p["y"], p["x"]))
    return {
        "local_peak_count": len(peaks),
        "peaks": peaks,
        "top_tied_locations": int(np.isclose(a, a.max(), atol=1e-7, rtol=0).sum()),
        "ambiguity_not_accuracy": True,
        "definition": "Local maxima >=0.25;11x11 window;8-connected plateaus count once; row-major tie break",
    }


def sensitivity_rows(case):
    settings = case.segmentation["settings"]
    if [s["segmentation_min_area_px"] for s in settings] != [140, 180, 220]:
        raise ValueError("Require the declared complete area grid140/180/220")
    radii = case.tracking["results_by_radius"]
    if set(radii) != {"40", "60", "80"}:
        raise ValueError("Require the declared complete radius grid40/60/80")
    segmentation, tracking = [], []
    for setting in settings:
        area = setting["segmentation_min_area_px"]
        visits = setting["visits"]
        if len(visits) != 9 or [v["day"] for v in visits] != list(DAYS):
            raise ValueError("Missing or duplicate area-grid visit")
        prefix = "primary_segmentation" if area == 180 else f"sensitivity_area_{area:04d}"
        for i, visit in enumerate(visits):
            mask = case.array(f"{prefix}_visit_{i:02d}_mask", optional=True)
            baseline = case.array(f"primary_segmentation_visit_{i:02d}_mask", optional=True)
            if mask is not None and (
                mask.dtype != bool
                or mask.shape != (128, 128)
                or int(mask.sum()) != visit["mask_area_px"]
            ):
                raise ValueError("Area-grid scalar/actual mask mismatch")
            baseline_valid = bool(case.segmentation["settings"][1]["visits"][i]["valid_488_mask"])
            valid = visit["valid_488_mask"]
            if type(valid) is not bool:
                raise ValueError("Validity flag must be Boolean")
            union = (
                int((mask | baseline).sum()) if mask is not None and baseline is not None else None
            )
            iou = float((mask & baseline).sum()) / union if union else None
            if (
                iou is not None
                and visit.get("mask_IoU_vs_primary") is not None
                and not math.isclose(iou, visit["mask_IoU_vs_primary"], abs_tol=1e-12)
            ):
                raise ValueError("Area-grid IoU/actual mask mismatch")
            winner = winning_candidate(case.stages, f"{prefix}_visit_{i:02d}")
            components = case.array(winner + "_components", optional=True) if winner else None
            component_count = (
                int(np.unique(components[components > 0]).size) if components is not None else None
            )
            segmentation.append(
                {
                    "neuron_id": case.nid,
                    "day": DAYS[i],
                    "minimum_area_px": area,
                    "valid_488_mask": valid,
                    "primary_valid_488_mask": baseline_valid,
                    "flag_change": "gained_diagnostic_flag_not_acceptance"
                    if valid and not baseline_valid
                    else "lost_diagnostic_flag"
                    if baseline_valid and not valid
                    else "neutral_flag",
                    "actual_mask_stage": f"{prefix}_visit_{i:02d}_mask",
                    "mask_area_px": visit["mask_area_px"],
                    "mask_IoU_vs_primary": iou,
                    "saved_summary_mask_IoU": visit.get("mask_IoU_vs_primary"),
                    "candidate_component_count": component_count,
                    "competing_component_count": max(0, component_count - 1)
                    if component_count is not None
                    else None,
                    "core_constructed": setting["core_constructed"],
                    "core_area_px": setting["core_area_px"],
                    "core_rejection": setting["core_rejection"],
                    "stage_available": mask is not None,
                    "adopted": False,
                }
            )
    for radius in (40, 60, 80):
        visits = radii[str(radius)]
        if len(visits) != 9 or [r["day"] for r in visits] != list(DAYS):
            raise ValueError("Missing or duplicate tracking visit")
        for i, visit in enumerate(visits):
            primary = radii["60"][i]
            surface = case.array(f"tracking_r{radius:03d}_visit_{i:02d}_correlation", optional=True)
            score = visit.get("diagnostic_match_score")
            if score is not None and (type(score) not in (int, float) or not np.isfinite(score)):
                raise ValueError("Nonfinite tracking score cannot be invented")
            point = np.asarray(visit["candidate_anchor_yx_px"], dtype=float)
            stored = np.asarray(visit["stored_anchor_yx_px"], dtype=float)
            if (
                point.shape != (2,)
                or stored.shape != (2,)
                or not np.isfinite([point, stored]).all()
            ):
                raise ValueError("Invalid tracking coordinates")
            delta = float(np.linalg.norm(point - np.asarray(primary["candidate_anchor_yx_px"])))
            stats = peak_statistics(surface) if surface is not None else None
            chosen = case.stages.get(f"tracking_r{radius:03d}_visit_{i:02d}_chosen_peak", {})
            details = chosen.get("details", {})
            if not np.allclose(
                stored, case.geometry[i]["anchor_yx_registered_px"], rtol=0, atol=1e-8
            ):
                raise ValueError("Tracking summary stored anchor differs from frozen geometry")
            if details.get("candidate_anchor_yx_px") is not None and not np.allclose(
                point, details["candidate_anchor_yx_px"], rtol=0, atol=1e-8
            ):
                raise ValueError("Tracking summary candidate differs from recorded chosen peak")
            search_name = f"tracking_r{radius:03d}_visit_{i:02d}_raw_search"
            search = case.array(search_name, optional=True)
            nominal_side = 2 * radius + case.tracking["diagnostic_template_size_px"]
            if surface is not None and details.get("correlation_peak_yx") is not None:
                y, x = details["correlation_peak_yx"]
                if not (0 <= y < surface.shape[0] and 0 <= x < surface.shape[1]) or not np.isclose(
                    surface[y, x], score, atol=1e-6
                ):
                    raise ValueError("Tracking chosen peak differs from source surface")
            tracking.append(
                {
                    "neuron_id": case.nid,
                    "day": DAYS[i],
                    "radius_px": radius,
                    "score": score,
                    "score_pass": visit["diagnostic_score_pass"],
                    "inherited_tracking_valid": visit["historical_tracking_valid"],
                    "reference_frozen_visit_day": visit["reference_frozen_visit_day"],
                    "stored_anchor_yx_px": stored.tolist(),
                    "candidate_anchor_yx_px": point.tolist(),
                    "displacement_from_stored_anchor_px": float(np.linalg.norm(point - stored)),
                    "candidate_change_from_radius60_px": delta,
                    "interpretation": "unchanged_peak"
                    if delta < 1e-8
                    else "changed_peak_not_identity_accuracy",
                    "nearest_other_stored_anchor": visit["nearest_other_stored_anchor"],
                    "actual_search_shape_yx": list(search.shape) if search is not None else None,
                    "search_bounds": case.stages.get(search_name, {})
                    .get("details", {})
                    .get("bounds_y0_y1_x0_x1"),
                    "boundary_limited_search": any(n < nominal_side for n in search.shape)
                    if search is not None
                    else None,
                    "peak_statistics": stats,
                    "chosen_peak_details": details,
                    "stage_available": surface is not None,
                    "adopted": False,
                }
            )
    return segmentation, tracking


def _stat(path):
    s = Path(path).stat()
    return {"path": str(path), "bytes": s.st_size, "mtime_ns": s.st_mtime_ns, "inode": s.st_ino}


def bind_fov(case, dataset, declaration, master):
    """Load one well only; exact crop/master equality establishes the shown mapping."""
    import tifffile

    rows = sorted(
        [r for r in master if r["neuron_id"] == case.nid], key=lambda r: int(r["time_index"])
    )
    if (
        len(rows) != 9
        or [int(r["day"]) for r in rows] != list(DAYS)
        or [int(r["time_index"]) for r in rows] != list(range(9))
    ):
        raise ValueError("Require nine unique source master visits")
    wells = {r["well"] for r in rows}
    if len(wells) != 1:
        raise ValueError("A track cannot switch source well")
    well = next(iter(wells))
    source = declaration["stacks"][well]
    path = _child(dataset, source["path"])
    before = _stat(path)
    with tifffile.TiffFile(path) as tif:
        if len(tif.series) != 1:
            raise ValueError("Require one explicit registered TIFF series")
        series = tif.series[0]
        if (
            series.axes != "TCYX"
            or list(series.shape) != case.meta["input_shape"]
            or tuple(series.shape[:2]) != (9, 3)
            or str(series.dtype) != case.meta["input_dtype"]
        ):
            raise ValueError("Registered stack axes/shape/dtype differ from trace")
    try:
        stack = tifffile.memmap(path)
    except ValueError:
        with tifffile.TiffFile(path) as tif:
            if (
                np.prod(tif.series[0].shape) * np.dtype(tif.series[0].dtype).itemsize
                > 512 * 1024**2
            ):
                raise ValueError("Compressed one-well stack exceeds512MiB memory guard") from None
            stack = tif.asarray()
    fov_records = []
    for i, (row, geo) in enumerate(zip(rows, case.geometry)):
        anchor = [float(row["anchor_y"]), float(row["anchor_x"])]
        if not np.allclose(anchor, geo["anchor_yx_registered_px"], rtol=0, atol=1e-8):
            raise ValueError("Master anchor differs from frozen trace")
        bounds = Bounds(**geo["bounds"]).validate(stack.shape[-2:])
        if (bounds.y1 - bounds.y0, bounds.x1 - bounds.x0) != (128, 128):
            raise ValueError("Frozen crop must be128x128")
        if any(int(row["bbox_" + k]) != getattr(bounds, k) for k in ("y0", "y1", "x0", "x1")):
            raise ValueError("Master bounding box differs from trace")
        local = [anchor[0] - bounds.y0, anchor[1] - bounds.x0]
        if not np.allclose(local, geo["anchor_yx_crop_px"], rtol=0, atol=1e-8):
            raise ValueError("Crop anchor coordinate mapping differs")
        plane = stack[i, 2]
        crop = case.array(f"visit_{i:02d}_registered_488")
        if plane.dtype != crop.dtype or not np.array_equal(bounds.crop(plane), crop):
            raise ValueError("Live FOV crop differs from recorded production input")
        fov_records.append(
            {
                "day": DAYS[i],
                "time_index": i,
                "well": well,
                "bounds": vars(bounds),
                "anchor_yx_registered_px": anchor,
                "anchor_yx_crop_px": local,
                "live_FOV_488_array_sha256": array_sha256(plane),
                "live_crop_exactly_equal": True,
                "historical_stack_sha256": source["sha256"],
                "whole_stack_rehashed_here": False,
                "source_stat": before,
                "coordinate_stream": "historical_registered_not_original_ND2",
            }
        )
    if _stat(path) != before:
        raise ValueError("FOV source changed while binding")
    return stack, fov_records


def _png_bytes(rgb):
    stream = io.BytesIO()
    Image.fromarray(np.asarray(rgb, dtype=np.uint8)).save(stream, format="PNG")
    return stream.getvalue()


def _font(size):
    try:
        return ImageFont.truetype("DejaVuSans.ttf", size)
    except OSError:
        return ImageFont.load_default(size=size)


def render_sheet(
    out, stem, title, cards, *, subtitle="Registered source; diagnostics only; no human approval"
):
    """One layout produces readable PNG and self-contained image-rich SVG."""
    columns, cw, ch, margin = 5, 330, 430, 24
    width, height = columns * cw + 2 * margin, math.ceil(len(cards) / columns) * ch + 140
    canvas = Image.new("RGB", (width, height), "#f4f7fb")
    draw = ImageDraw.Draw(canvas)
    draw.text((margin, 20), title, font=_font(25), fill="#14283e")
    draw.text((margin, 60), subtitle, font=_font(16), fill="#53677b")
    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#f4f7fb"/>',
        f'<text x="24" y="43" font-family="sans-serif" font-size="25">{html.escape(title)}</text>',
        f'<text x="24" y="80" font-family="sans-serif" font-size="16">{html.escape(subtitle)}</text>',
    ]
    metadata = []
    for number, card in enumerate(cards):
        x, y = margin + number % columns * cw, 110 + number // columns * ch
        title_lines = textwrap.wrap(f"{number + 1}. {card['title']}", width=34)[:2]
        for j, line in enumerate(title_lines):
            draw.text((x, y + 19 * j), line, font=_font(16), fill="#14283e")
            svg.append(
                f'<text x="{x}" y="{y + 16 + 19 * j}" font-family="sans-serif" font-size="16">{html.escape(line)}</text>'
            )
        rgb = card.get("image")
        if rgb is not None:
            image = Image.fromarray(np.asarray(rgb, dtype=np.uint8)).convert("RGB")
            scale = min(300 / image.width, 285 / image.height)
            image = image.resize(
                (max(1, round(image.width * scale)), max(1, round(image.height * scale))),
                Image.Resampling.NEAREST,
            )
            ix, iy = x + (300 - image.width) // 2, y + 48
            canvas.paste(image, (ix, iy))
            encoded = base64.b64encode(_png_bytes(np.asarray(image))).decode()
            svg.append(
                f'<image x="{ix}" y="{iy}" width="{image.width}" height="{image.height}" href="data:image/png;base64,{encoded}"/>'
            )
        else:
            draw.rectangle((x, y + 48, x + 300, y + 333), fill="#fff2da", outline="#d39838")
            draw.text((x + 12, y + 120), "UNAVAILABLE / FAILED", font=_font(16), fill="#8a4e00")
            svg.append(
                f'<rect x="{x}" y="{y + 48}" width="300" height="285" fill="#fff2da"/><text x="{x + 10}" y="{y + 145}" font-size="16">UNAVAILABLE / FAILED</text>'
            )
        text = card.get("caption", "")
        for j, line in enumerate(textwrap.wrap(text, width=43)[:5]):
            draw.text((x, y + 344 + j * 16), line, font=_font(12), fill="#53677b")
            svg.append(
                f'<text x="{x}" y="{y + 356 + j * 16}" font-family="sans-serif" font-size="12">{html.escape(line)}</text>'
            )
        metadata.append({k: v for k, v in card.items() if k != "image"})
    svg.append("</svg>")
    _write(out / (stem + ".png"), _png_bytes(np.asarray(canvas)))
    _write(out / (stem + ".svg"), "\n".join(svg))
    return {
        "stem": stem,
        "title": title,
        "cards": metadata,
        "PNG": stem + ".png",
        "SVG": stem + ".svg",
    }


def _rendered_card(case, name, rgb, title, caption, **details):
    return {
        "title": title,
        "image": rgb,
        "caption": caption,
        "stage": name,
        "status": "display_only",
        "provenance": {
            "trace_manifest_sha256": case.manifest_sha,
            "parameters": details,
            "quantitative_input_unchanged": True,
        },
    }


def _outline_card(case, i, mask_name, title):
    raw = case.array(f"visit_{i:02d}_registered_488")
    mask = case.array(mask_name, optional=True)
    if mask is None:
        return case.card(mask_name, title)
    rgb = render_preview(
        raw, LUT(**case.cfg["luts"]["488"]), overlays=[{"mask": mask, "color": (255, 210, 0)}]
    )
    return _rendered_card(
        case,
        mask_name,
        rgb,
        title,
        "Yellow contour on unchanged recorded raw488 crop; not ownership approval.",
        overlay_stage=mask_name,
    )


def processing_cards(case, i, plane, source):
    """Actual winning morphology, not an illustrative threshold substitute."""
    prefix = f"primary_segmentation_visit_{i:02d}"
    raw_lut = LUT(**case.cfg["luts"]["488"])
    fov = Image.fromarray(render_preview(plane, raw_lut))
    d = ImageDraw.Draw(fov)
    b = source["bounds"]
    d.rectangle((b["x0"], b["y0"], b["x1"] - 1, b["y1"] - 1), outline=(255, 210, 0), width=8)
    ay, ax = source["anchor_yx_registered_px"]
    d.line((ax - 20, ay, ax + 20, ay), fill=(0, 255, 255), width=6)
    d.line((ax, ay - 20, ax, ay + 20), fill=(0, 255, 255), width=6)
    cards = [
        _rendered_card(
            case,
            "live_registered_FOV",
            np.asarray(fov),
            "Full registered488 FOV → original box",
            "Yellow=stored128-pixel box. This is historical registered context, not raw ND2 or verified whole well.",
            **source,
        )
    ]
    for suffix, title in (
        ("crop", "Exact128×128 spatial box"),
        ("normalized", "Normalize: production percentiles"),
        ("smoothed", "Smooth: production Gaussian"),
        ("segmentation_seed", "Recorded discovery seed"),
        ("allowed_region", "Allowed region from stored prior"),
    ):
        cards.append(case.card(prefix + "_" + suffix, title))
    winner = winning_candidate(case.stages, prefix)
    for suffix, title in (
        ("threshold", "Winning candidate: threshold"),
        ("small_objects_removed", "Remove small objects"),
        ("closed", "Morphology: closing"),
        ("holes_filled", "Morphology: fill holes"),
        ("components", "Candidate component labels"),
    ):
        cards.append(
            case.card((winner or prefix + "_winning_candidate_unavailable") + "_" + suffix, title)
        )
    alternatives = sorted(
        n
        for n in case.stages
        if n.startswith(prefix + "_candidate_")
        and n.endswith("_threshold")
        and (not winner or not n.startswith(winner + "_"))
    )
    if alternatives:
        cards.append(case.card(alternatives[0], "Competing threshold, NOT selected"))
    cards += [
        case.card(prefix + "_selected_component", "Actual selected soma support"),
        _outline_card(case, i, prefix + "_mask", "Selected soma contour"),
    ]
    qc = case.card(prefix + "_qc", "Unchanged visit QC / failure")
    qc_details = case.stages.get(prefix + "_qc", {}).get("details", {})
    qc["title"] = "Visit QC valid=" + str(qc_details.get("valid_488_mask", "unavailable"))
    qc["caption"] = (
        f"valid_488_mask={qc_details.get('valid_488_mask')}; tracking_valid_inherited={qc_details.get('tracking_valid_inherited')}. Unchanged original gates; no approval."
    )
    cards.append(qc)
    for suffix, title in (
        ("template", "Fixed Day8 tracking template"),
        ("raw_search", "Actual radius60 search"),
        ("normalized_search", "Normalize tracking search"),
        ("correlation", "Actual template correlation"),
        ("chosen_peak", "Recorded chosen peak"),
    ):
        cards.append(case.card(f"tracking_r060_visit_{i:02d}_" + suffix, title))
    for name, title in (
        ("primary_identity_vote_count", "Longitudinal support votes"),
        ("primary_identity_consensus", "Consensus support"),
        ("primary_identity_core", "Frozen identity core"),
    ):
        cards.append(case.card(name, title))
    cards += [
        _outline_card(case, i, "primary_identity_core", "Core contour on same raw crop"),
        _outline_card(case, i, "phenotype_roi_holes_filled", "Final fixed diagnostic ROI"),
    ]
    return cards


def comparison_cards(case, i, view_rows, lut):
    raw = case.array(f"visit_{i:02d}_registered_488")
    cards = [
        case.card(f"visit_{i:02d}_registered_488", "Recorded fixed spatial box"),
        _rendered_card(
            case,
            "same_crop_comparison_LUT",
            render_preview(raw, lut),
            "SAME pixels; declared comparison LUT",
            f"Display{lut.low}..{lut.high}ADU; not calibration, segmentation or adoption.",
        ),
    ]
    for row in view_rows:
        bounds = Bounds(**row["proposal"]["bounds"]) if row["proposal"]["bounds"] else None
        cards.append(
            _rendered_card(
                case,
                row["policy"],
                render_preview(raw, lut, bounds=bounds) if bounds else None,
                row["policy"] + ": " + row["status"],
                row["interpretation"] + "; geometry remains unchanged.",
                proposal=row,
            )
        )
    for area in (140, 180, 220):
        prefix = "primary_segmentation" if area == 180 else f"sensitivity_area_{area:04d}"
        card = case.card(f"{prefix}_visit_{i:02d}_mask", f"SAME visit; min_area={area}")
        setting = next(
            s for s in case.segmentation["settings"] if s["segmentation_min_area_px"] == area
        )
        visit = setting["visits"][i]
        card["caption"] = (
            f"Valid flag={visit['valid_488_mask']}; mask={visit['mask_area_px']}px; IoU vs180={visit['mask_IoU_vs_primary']}. Diagnostic only, not acceptance."
        )
        cards.append(card)
    for radius in (40, 60, 80):
        card = case.card(
            f"tracking_r{radius:03d}_visit_{i:02d}_correlation",
            f"SAME visit; search radius={radius}",
        )
        visit = case.tracking["results_by_radius"][str(radius)][i]
        score = visit["diagnostic_match_score"]
        score_text = f"{score:.3f}" if score is not None else "unavailable"
        card["caption"] = (
            f"Score={score_text}; offset from stored anchor={visit['displacement_from_stored_anchor_px']:.2f}px. Stored anchor is not independent truth."
        )
        cards.append(card)
    return cards


def overview_cards(case, tracking):
    cards = []
    for i, day in enumerate(DAYS):
        row = next(r for r in tracking if r["day"] == day and r["radius_px"] == 60)
        card = _outline_card(
            case, i, "phenotype_roi_holes_filled", f"Day{day}; fixed ROI + tracking proposal"
        )
        rgb = card.get("image")
        in_crop = False
        if rgb is not None:
            image = Image.fromarray(rgb)
            geo = case.geometry[i]
            y, x = row["candidate_anchor_yx_px"]
            y -= geo["bounds"]["y0"]
            x -= geo["bounds"]["x0"]
            if 0 <= y < 128 and 0 <= x < 128:
                in_crop = True
                draw = ImageDraw.Draw(image)
                draw.line((x - 4, y, x + 4, y), fill=(0, 255, 255))
                draw.line((x, y - 4, x, y + 4), fill=(0, 255, 255))
            card["image"] = np.asarray(image)
        card["caption"] = (
            f"{'Cyan=unadopted r60 candidate' if in_crop else 'Candidate OFF_CROP / unavailable; not recentered'}; displacement from stored anchor={row['displacement_from_stored_anchor_px']:.2f}px. Yellow=fixed ROI; no approval."
        )
        card["provenance"]["tracking"] = row
        cards.append(card)
    return cards


def run(traces, dataset, out, *, render_cases, days=None, lut_low=None, lut_high=None):
    """Reuse all saved diagnostic cases; draw only explicitly selected large stories."""
    traces, dataset, out = map(_plain, (traces, dataset, out))
    implementation = {
        str(path): sha(path)
        for path in (
            Path(__file__),
            Path(__file__).with_name("visualization.py"),
            Path(__file__).with_name("display.py"),
            REPO / "scripts/render_actual_fov_figures.py",
        )
    }
    if (
        not traces.is_dir()
        or not dataset.is_dir()
        or out.exists()
        or out.is_relative_to(REPO)
        or any(out.is_relative_to(p) or p.is_relative_to(out) for p in (traces, dataset))
    ):
        raise ValueError("Choose a new private output outside inputs and Git")
    if len(render_cases) != len(set(render_cases)) or not render_cases:
        raise ValueError("Choose distinct explicit render-case IDs")
    if days is not None and (
        not days or len(days) != len(set(days)) or not set(days).issubset(DAYS)
    ):
        raise ValueError("Depicted days must be a distinct subset of nine known visits")
    if (lut_low is None) != (lut_high is None):
        raise ValueError("Declare both comparison LUT limits or neither")
    if lut_low is not None and (
        any(
            isinstance(v, bool) or not isinstance(v, (int, float)) or not np.isfinite(v)
            for v in (lut_low, lut_high)
        )
        or not 0 <= lut_low < lut_high <= 65535
    ):
        raise ValueError("Comparison LUT requires finite ordered0..65535 limits")
    declaration_path = _child(dataset, "dataset_manifest.json")
    declaration_sha = sha(declaration_path)
    declaration = _json(declaration_path)
    if declaration.get("channels") != ["405", "561", "488"] or declaration.get("days") != list(
        DAYS
    ):
        raise ValueError("Dataset channel/day declarations differ")
    master_path = _child(dataset, declaration["master"]["path"])
    master_sha = sha(master_path)
    if master_sha != declaration["master"]["sha256"]:
        raise ValueError("Master source checksum changed")
    with master_path.open(newline="") as stream:
        master = list(csv.DictReader(stream))
    roots = sorted(p for p in traces.iterdir() if p.is_dir())
    if not roots or any(p.is_symlink() or not CASE.fullmatch(p.name) for p in roots):
        raise ValueError("Require regular declared track directories")
    if not set(render_cases).issubset({p.name for p in roots}):
        raise ValueError("Unknown render-case ID")
    out.mkdir(parents=True, mode=0o700, exist_ok=False)
    views, segs, tracks, sheets, sources, summaries = [], [], [], [], [], []
    bindings = {str(master_path): master_sha, str(declaration_path): declaration_sha}
    stats = []
    for root in roots:
        case = TraceCase(root)
        print("VERIFY_RENDER_CASE=" + case.nid, flush=True)
        stack, fovs = bind_fov(case, dataset, declaration, master)
        sources.append(
            {
                "neuron_id": case.nid,
                "trace": str(root),
                "trace_manifest_sha256": case.manifest_sha,
                "source_code_matches_current": {
                    name: sha(_child(REPO, name)) == expected
                    for name, expected in case.meta["source_file_sha256"].items()
                },
                "FOV_bindings": fovs,
            }
        )
        stats.append(fovs[0]["source_stat"])
        seg, track = sensitivity_rows(case)
        segs.extend(seg)
        tracks.extend(track)
        core = case.array("primary_identity_core", optional=True)
        roi = case.array("phenotype_roi_holes_filled", optional=True)
        comparison_lut = (
            LUT(lut_low, lut_high, "488") if lut_low is not None else LUT(**case.cfg["luts"]["488"])
        )
        case_views = []
        for i in range(9):
            raw = case.array(f"visit_{i:02d}_registered_488")
            rows = viewing_metrics(
                raw,
                core,
                roi,
                case.geometry[i]["anchor_yx_crop_px"],
                comparison_lut,
                padding=case.cfg["lut_box"]["padding"],
                min_area=case.cfg["lut_box"]["min_area"],
            )
            for row in rows:
                row.update(
                    neuron_id=case.nid,
                    day=DAYS[i],
                    source_crop_array_sha256=array_sha256(raw),
                    source_trace_manifest_sha256=case.manifest_sha,
                    comparison_lut=comparison_lut.metadata(),
                    FOV_area_px=int(np.prod(stack.shape[-2:])),
                    frozen_QC_unchanged=True,
                )
            case_views.extend(rows)
        views.extend(case_views)
        if case.nid in render_cases:
            first_sheet = len(sheets)
            failed = [day for day in DAYS if not case.summary["valid_488_by_day"][str(day)]]
            depicted = sorted(days if days is not None else set([8, 25, 39] + failed[:1]))
            for day in depicted:
                i = DAYS.index(day)
                stem = case.nid + f"_day{day:02d}"
                sheets.append(
                    render_sheet(
                        out,
                        stem + "_flow",
                        f"{case.nid} Day{day}: actual recorded processing",
                        processing_cards(case, i, stack[i, 2], fovs[i]),
                    )
                )
                sheets.append(
                    render_sheet(
                        out,
                        stem + "_comparison",
                        f"{case.nid} Day{day}: same-input proposals and sensitivity",
                        comparison_cards(
                            case, i, [r for r in case_views if r["day"] == day], comparison_lut
                        ),
                    )
                )
            sheets.append(
                render_sheet(
                    out,
                    case.nid + "_nine_visits",
                    case.nid + ": all nine visits, fixed ROI and centroid proposals",
                    overview_cards(case, track),
                )
            )
            for sheet in sheets[first_sheet:]:
                match = re.search(r"_day(\d+)_", sheet["stem"])
                sheet.update(
                    neuron_id=case.nid,
                    day=int(match[1]) if match else None,
                    kind="flow"
                    if sheet["stem"].endswith("_flow")
                    else "comparison"
                    if sheet["stem"].endswith("_comparison")
                    else "nine_visits",
                    trace_manifest_sha256=case.manifest_sha,
                    configuration_sha256=hashlib.sha256(
                        json.dumps(case.cfg, sort_keys=True).encode()
                    ).hexdigest(),
                )
        summaries.append(
            {
                "neuron_id": case.nid,
                "original_diagnostic_status": case.summary["diagnostic_status"],
                "original_valid_visits": case.summary["valid_488_visit_count"],
                "area_valid_counts": {
                    str(a): sum(r["valid_488_mask"] for r in seg if r["minimum_area_px"] == a)
                    for a in (140, 180, 220)
                },
                "original_failures_preserved": True,
                "accepted": False,
            }
        )
        case.finish()
        bindings.update(case.bindings)
        if isinstance(stack, np.memmap):
            stack._mmap.close()
        del stack, case
    for path, expected in bindings.items():
        if sha(path) != expected:
            raise ValueError("Bound input changed during rendering")
    if any(_stat(record["path"]) != record for record in stats):
        raise ValueError("Registered stack stat changed during rendering")
    if any(sha(path) != expected for path, expected in implementation.items()):
        raise ValueError("Renderer/visualization implementation changed during rendering")
    _csv(out / "viewing_comparisons.csv", views)
    _csv(out / "segmentation_sensitivity.csv", segs)
    _csv(out / "tracking_sensitivity.csv", tracks)
    _write_json(
        out / "case_summary.json",
        {"schema_version": SCHEMA, "cases": summaries, "adopted": False, "accepted_ids": []},
    )
    _csv(
        out / "figure_index.csv",
        [
            {
                "title": s["title"],
                "PNG": s["PNG"],
                "SVG": s["SVG"],
                "card_count": len(s["cards"]),
                "neuron_id": s["neuron_id"],
                "day": s["day"],
                "kind": s["kind"],
                "source_trace_manifest_sha256": s["trace_manifest_sha256"],
                "configuration_sha256": s["configuration_sha256"],
            }
            for s in sheets
        ],
    )
    _csv(
        out / "IMPLEMENTED_EXECUTED_VALIDATED.csv",
        [
            {
                "stage": "Saved registered segmentation/tracking figures",
                "implemented": True,
                "executed": True,
                "validated": "source/crop integrity; not independent identity accuracy",
            },
            {
                "stage": "LUT box viewing comparisons",
                "implemented": True,
                "executed": True,
                "validated": "display-only retained/lost support; not measurement adoption",
            },
            {
                "stage": "Original ND2 to historical atlas mapping",
                "implemented": False,
                "executed": False,
                "validated": "BLOCKED; no coordinate mapping supplied",
            },
            {
                "stage": "Historical IC/stitching and biological approval",
                "implemented": False,
                "executed": False,
                "validated": "BLOCKED; authentic calibration/geometry/human evidence required",
            },
        ],
    )
    report = (
        "# Actual registered-FOV evidence\n\n"
        f"{len(summaries)} existing cases; nine visits each. Saved production arrays reused, not recomputed. "
        "The live registered FOV crop equals the recorded crop exactly. These are not newly registered original ND2 fields or verified whole wells.\n\n"
        "## What / why / limits\n\n"
        "Normalization and smoothing expose estimation inputs; threshold/morphology cards follow the actual winning component parent. "
        "Search/correlation/peak records explain competing proposals; all nine-visit masks and failures remain. "
        "Areas140/180/220 change component preference, not necessarily a strict final soma-area floor. "
        "Radii40/60/80 alter the available search region; stronger scores or proximity to another stored anchor do not establish identity.\n\n"
        f"Comparison range: {lut_low}..{lut_high}ADU when declared, otherwise each trace's recorded LUT. "
        "For the predeclared200..2000 exploration, roughly120ADU background motivated a lower viewing cutoff and the upper cutoff deliberately tests bright-signal exclusion. "
        "It is not optimal tuning or physical calibration. Visible means pixel>low; within_range means low<pixel<=high. "
        "A smaller viewport can drop frozen ROI/core pixels; no proposal changes segmentation, tracking or measurement geometry. "
        "All tables retain neutral and degraded results, including per-case gained/lost flags. No best measurement setting is selected.\n\n"
        "## Still blocked\n\n"
        "Historical detector IC/flat/dark, tile geometry, original-to-atlas mapping, independent identity/ownership, separate final561 review and all-nine acceptance remain required. "
        "No accuracy, accepted measurement, treatment, survival or discovery is established. Original failed QC, exclusions and human decisions are unchanged.\n"
    )
    _write(out / "WHAT_WHY_RESULTS.md", report)
    page = [
        '<!doctype html><html lang="en"><meta charset="utf-8"><title>Actual FOV evidence</title>',
        "<style>body{font:17px system-ui;margin:32px;background:#f4f7fb;color:#14283e}img{width:100%;max-width:1700px}pre{white-space:pre-wrap;overflow-wrap:anywhere}article{margin:32px 0}a{color:#175694}</style>",
        "<h1>Actual registered-FOV → soma → tracking → ROI</h1><p>Source-bound diagnostics, not raw-ND2 mapping, validated whole-well assembly or human approval.</p>",
        "<nav>"
        + " · ".join(
            f'<a href="#{html.escape(s["stem"])}">{html.escape(s["title"])}</a>' for s in sheets
        )
        + "</nav>",
    ]
    for sheet in sheets:
        page.append(
            f'<article id="{html.escape(sheet["stem"])}"><h2>{html.escape(sheet["title"])}</h2><a href="{sheet["SVG"]}">Self-contained SVG</a><img src="{sheet["PNG"]}" alt="{html.escape(sheet["title"])}"><details><summary>Every card: source, parameters, display and purpose</summary><pre>{html.escape(json.dumps(sheet["cards"], indent=2))}</pre></details></article>'
        )
    page.append(
        "<h2>Tables and limits</h2><ul>"
        + "".join(
            f'<li><a href="{name}">{name}</a></li>'
            for name in [
                "viewing_comparisons.csv",
                "segmentation_sensitivity.csv",
                "tracking_sensitivity.csv",
                "case_summary.json",
                "WHAT_WHY_RESULTS.md",
                "IMPLEMENTED_EXECUTED_VALIDATED.csv",
            ]
        )
        + "</ul></html>"
    )
    _write(out / "index.html", "\n".join(page))
    outputs = {p.name: sha(p) for p in sorted(out.iterdir()) if p.is_file()}
    result = {
        "schema_version": SCHEMA,
        "sources": sources,
        "source_files_sha256": bindings,
        "current_renderer_sha256": implementation[str(Path(__file__))],
        "current_implementation_sha256": implementation,
        "sheets": sheets,
        "render_cases": list(render_cases),
        "requested_days": days,
        "selection_basis": "explicit case/day selection; defaults include earliest primary failure; no561 selection",
        "comparison_lut_declaration": {
            "low": lut_low,
            "high": lut_high,
            "frozen_across_visits": True,
        },
        "outputs_sha256": outputs,
        "all_proposals_unadopted": True,
        "measurement_geometry_changed": False,
        "accepted_export_written": False,
        "real_accepted_ids": [],
        "scientific_inference_ready": False,
    }
    _write_json(out / "figure_manifest.json", result)
    return result
