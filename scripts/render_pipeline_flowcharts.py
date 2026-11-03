#!/usr/bin/env python3
"""Render exact workflow graphics and optional verified, recorded stage previews.

The workflow diagrams describe required processing. They are never labelled as
proof that an ND2 experiment ran. When --trace is supplied, every trace artifact
is verified before its existing display-only PNG can appear in these graphics.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import html
import io
import json
import math
from pathlib import Path
import re
import sys
import textwrap
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
WIDTH = 1200
COLORS = dict(ink="#14283e", muted="#53677b", border="#b7c8d8", blue="#e9f3fc",
              amber="#fff2da", white="#ffffff", backdrop="#f4f7fb")

ND2_NODES = [
    ("nd2", 440, 190, "Original ND2 inputs", "Read source pixels; retain ND2 SHA256, axes, channels, time and position indices."),
    ("inventory", 440, 350, "Inventory and geometry", "Resolve original channels, physical pixel size, FOV positions and per-well visit membership."),
    ("geometry", 50, 350, "FOV placement contract", "Record detector orientation, stage coordinates, overlap and the geometry authority."),
    ("preprocess", 440, 510, "Detector preprocessing", "Save raw, dark-subtracted, flatfield/IC before and after, background and downstream pixels."),
    ("intermediates", 830, 510, "Small intermediate records", "Each numeric array has a preview, parameters, parents, input hash and what/why explanation."),
    ("stitch", 440, 670, "Assemble one well per visit", "Place corrected FOVs in a common well canvas; preserve tile transforms and coverage."),
    ("seams", 830, 670, "Seams and support QC", "Inspect tile overlaps, seam residuals, missing regions and supported pixels."),
    ("register", 440, 830, "Register whole-well visits", "Estimate longitudinal motion with 488; apply the same accepted transform to every channel."),
    ("segtrack", 440, 990, "488 segmentation and tracking", "Expose threshold candidates, morphology, components, selected soma and tracking alternatives."),
    ("lut", 830, 990, "Display LUT / viewing box", "Fixed ranges and constrained box proposals are display-only until independently reviewed."),
    ("gate", 440, 1150, "Identity and ROI evidence gate", "Preserve all nine visits, ownership checks, source bindings and explicit exclusion reasons."),
    ("phenotype", 440, 1310, "Independent 561 phenotype", "Compute punctate/diffuse measurements only under the original review and QC rules."),
]
ND2_EDGES = [("nd2", "inventory"), ("inventory", "preprocess"), ("inventory", "geometry"),
             ("geometry", "stitch"), ("preprocess", "stitch"), ("preprocess", "intermediates"),
             ("stitch", "seams"), ("stitch", "register"), ("register", "segtrack"),
             ("segtrack", "lut"), ("segtrack", "gate"), ("gate", "phenotype")]
SEG_NODES = [
    ("source", 440, 190, "Before segmentation", "Registered 488 source and frozen anchor; retain raw intensities and supported-pixel mask."),
    ("normalize", 440, 350, "Normalize and smooth", "Save the actual estimation image, smoothing result, seed and allowed region."),
    ("candidates", 440, 510, "Threshold candidates", "Record every threshold candidate before and after morphology and component labeling."),
    ("compare", 830, 510, "Parameter sensitivity", "Change one declared parameter at a time; retain failures and never rank using 561."),
    ("select", 440, 670, "Select the soma support", "Save component scores, chosen support and validity reasons; image review checks identity."),
    ("track", 50, 830, "Soma tracking", "Template, search region, correlation surface, peak and displacement from the frozen anchor."),
    ("consensus", 440, 830, "Longitudinal 488 identity core", "Show visit masks, vote counts, consensus, hole filling and final core."),
    ("lut", 830, 830, "LUT-constrained box proposal", "Declare intensity range, visible/within-range policy, anchor component and padding."),
    ("roi", 440, 990, "After segmentation: fixed ROI", "Record core and dilation separately; preserve geometry and unresolved neighbor ownership."),
    ("review", 440, 1150, "Review and automated QC", "A stronger score or a smaller ROI is not proof of identity or ownership."),
    ("measure", 440, 1310, "Independent 561 measurements", "Save local background, DoG response, puncta mask and diffuse residual; export stays gated."),
]
SEG_EDGES = [("source", "normalize"), ("normalize", "candidates"), ("candidates", "compare"),
             ("candidates", "select"), ("select", "track"), ("select", "consensus"),
             ("select", "lut"), ("consensus", "roi"), ("roi", "review"), ("track", "review"),
             ("review", "measure")]
CATEGORIES = [
    ("Original ND2 read", ("nd2_read", "nd2_raw", "original_nd2")),
    ("Before IC", ("reference_preprocess_00_before_ic", "before_ic", "00_before")),
    ("After IC", ("reference_preprocess_03_after_ic_float", "after_ic", "03_after")),
    ("After background", ("reference_preprocess_05_after_background_float", "after_background", "05_after")),
    ("Stitched well", ("well_mosaic", "stitched_well", "assembled_well")),
    ("Alignment / registered input", ("registered_moving_cyx", "registered_overlap_488", "registered_488", "aligned")),
    ("During segmentation", ("normalized", "smoothed", "threshold", "candidate")),
    ("Selected segmentation", ("selected_mask", "final_mask", "selected_component")),
    ("Tracking", ("correlation", "tracking_search", "tracking_template")),
    ("Final core / ROI", ("identity_core", "phenotype_roi", "primary_identity_core")),
    ("Puncta / diffuse", ("puncta", "diffuse", "dog_response")),
]


def sha(data):
    return hashlib.sha256(data).hexdigest()


def _safe_artifact(root, relative):
    value = Path(relative)
    if value.is_absolute() or ".." in value.parts or "\\" in str(value):
        raise ValueError("Unsafe trace preview path")
    path = root / value
    cursor = path
    while cursor != root:
        if cursor.is_symlink():
            raise ValueError("Linked trace preview")
        cursor = cursor.parent
    if not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("Missing trace preview")
    return path


def trace_evidence(trace=None):
    if trace is None:
        return dict(trace_integrity_verified=False, trace_input_kind="no_trace_supplied",
                    original_nd2_source_recorded=False, original_nd2_pipeline_validated=False,
                    previews=[], unavailable_categories=[name for name, _ in CATEGORIES])
    from tmem_align.audit_v1.stage_trace import verify_trace
    root = Path(trace).resolve()
    if Path(trace).is_symlink():
        raise ValueError("Linked trace roots are not allowed")
    original_manifest = _safe_artifact(root, "manifest.json").read_bytes()
    manifest = verify_trace(root)
    if _safe_artifact(root, "manifest.json").read_bytes() != original_manifest:
        raise ValueError("Trace manifest changed during graphic verification")
    metadata = manifest.get("metadata", {})
    supplied = metadata.get("supplied_input_provenance", {})
    if not isinstance(supplied, dict):
        supplied = {}
    inputs = metadata.get("inputs", supplied.get("inputs", []))
    if not isinstance(inputs, list):
        inputs = []
    nd2 = any(isinstance(item, dict) and str(item.get("path", "")).lower().endswith(".nd2")
              and re.fullmatch(r"[0-9a-f]{64}", str(item.get("sha256", ""))) for item in inputs)
    mode = metadata.get("mode", metadata.get("invoked_mode", supplied.get("invoked_mode")))
    registered = mode == "registered-track" or "registered" in str(metadata.get("coordinate_system", ""))
    available = [r for r in manifest["stages"] if r["status"] == "executed" and "preview" in r.get("artifacts", {})]
    available.sort(key=lambda r: r.get("channel") != "488")
    selected, missing = [], []
    for label, tokens in CATEGORIES:
        # Prefer exact/current production names before broad aliases. A source
        # stage can intentionally represent both decoded input and before-IC;
        # do not select the moving image merely to make cards unique.
        record = next((r for token in tokens for r in available
                       if token in r["stage"].lower()), None)
        if record is None and label == "Original ND2 read" and nd2:
            record = next((r for r in available
                           if r["stage"] == "reference_preprocess_00_before_ic"), None)
        if record is None:
            missing.append(label)
            continue
        artifact = record["artifacts"]["preview"]
        path = _safe_artifact(root, artifact["path"])
        content = path.read_bytes()
        if sha(content) != artifact["sha256"]:
            raise ValueError("Trace preview changed after verification")
        selected.append(dict(category=label, stage=record["stage"], channel=record.get("channel"),
                             why=record.get("why", ""), preview_sha256=sha(content),
                             data_url="data:image/png;base64," + base64.b64encode(content).decode()))
    if _safe_artifact(root, "manifest.json").read_bytes() != original_manifest:
        raise ValueError("Trace manifest changed while collecting graphics")
    return dict(trace_integrity_verified=True, trace_manifest_sha256=sha(original_manifest), trace_mode=mode,
                trace_input_kind="original_ND2_source_recorded" if nd2 else "registered_inputs_declared" if registered else "unclassified_trace",
                original_nd2_source_recorded=bool(nd2), original_nd2_pipeline_validated=False,
                trace_stage_status_counts=manifest["stage_status_counts"], previews=selected,
                unavailable_categories=missing)


def _lines(text, width):
    return textwrap.wrap(str(text), width=width, break_long_words=True) or [""]


def build_svg(title, nodes, edges, evidence):
    rows = (len(CATEGORIES) + 2) // 3
    height = 1580 + rows * 245
    esc = html.escape
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="{height}" viewBox="0 0 1200 {height}" role="img">',
           f'<title>{esc(title)}</title>',
           '<defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8" fill="#53677b"/></marker></defs>',
           '<rect width="1200" height="100%" fill="#f4f7fb"/>',
           f'<text x="50" y="58" font-family="sans-serif" font-size="30" font-weight="bold" fill="#14283e">{esc(title)}</text>',
           '<text x="50" y="95" font-family="sans-serif" font-size="18" fill="#53677b">WORKFLOW DESIGN — does not establish that these steps executed on original ND2 data.</text>',
           f'<text x="50" y="127" font-family="sans-serif" font-size="16" fill="#53677b">Recorded trace: {esc(evidence["trace_input_kind"])}. Preview integrity verified: {str(evidence["trace_integrity_verified"]).lower()}.</text>']
    positions = {node[0]: node for node in nodes}
    for start, end in edges:
        _, x1, y1, *_ = positions[start]
        _, x2, y2, *_ = positions[end]
        if y1 == y2:
            ax, ay = (x1 + 320 if x2 > x1 else x1), y1 + 60
            bx, by = (x2 if x2 > x1 else x2 + 320), y2 + 60
        elif x1 == x2:
            ax, ay, bx, by = x1 + 160, y1 + 120, x2 + 160, y2
        else:
            ax, ay = (x1 + 320 if x2 > x1 else x1), y1 + 60
            bx, by = (x2 if x2 > x1 else x2 + 320), y2 + 60
            middle_x = (ax + bx) / 2
            out.append(f'<path d="M{ax},{ay} L{middle_x},{ay} L{middle_x},{by} L{bx},{by}" fill="none" stroke="#53677b" stroke-width="2.4" marker-end="url(#arrow)"/>')
            continue
        middle = (ay + by) / 2
        out.append(f'<path d="M{ax},{ay} C{ax},{middle} {bx},{middle} {bx},{by}" fill="none" stroke="#53677b" stroke-width="2.4" marker-end="url(#arrow)"/>')
    for _, x, y, heading, body in nodes:
        fill = "#fff2da" if "gate" in heading.lower() or "QC" in heading else "#e9f3fc"
        out.append(f'<rect x="{x}" y="{y}" width="320" height="120" rx="14" fill="{fill}" stroke="#b7c8d8"/>')
        for i, line in enumerate(_lines(heading, 26)):
            out.append(f'<text x="{x+16}" y="{y+26+i*20}" font-family="sans-serif" font-size="17" font-weight="bold" fill="#14283e">{esc(line)}</text>')
        for i, line in enumerate(_lines(body, 37)):
            out.append(f'<text x="{x+16}" y="{y+66+i*16}" font-family="sans-serif" font-size="13" fill="#14283e">{esc(line)}</text>')
    out.append('<text x="50" y="1494" font-family="sans-serif" font-size="24" font-weight="bold" fill="#14283e">Recorded before / during / after previews</text>')
    out.append('<text x="50" y="1527" font-family="sans-serif" font-size="15" fill="#53677b">Existing display PNGs only. Missing stages remain unavailable. Quantitative arrays are unchanged.</text>')
    previews = {item["category"]: item for item in evidence["previews"]}
    for i, (category, _) in enumerate(CATEGORIES):
        x, y = 50 + (i % 3) * 390, 1560 + (i // 3) * 245
        out.append(f'<rect x="{x}" y="{y}" width="320" height="220" rx="10" fill="white" stroke="#b7c8d8"/>')
        out.append(f'<text x="{x+14}" y="{y+24}" font-family="sans-serif" font-size="15" font-weight="bold" fill="#14283e">{esc(category)}</text>')
        item = previews.get(category)
        if item:
            out.append(f'<image x="{x+14}" y="{y+38}" width="132" height="132" preserveAspectRatio="xMidYMid meet" href="{item["data_url"]}"/>')
            for k, line in enumerate(_lines(item["stage"], 20)[:7]):
                out.append(f'<text x="{x+158}" y="{y+57+k*17}" font-family="sans-serif" font-size="12" fill="#14283e">{esc(line)}</text>')
            out.append(f'<text x="{x+14}" y="{y+199}" font-family="sans-serif" font-size="12" fill="#53677b">Recorded channel {esc(str(item["channel"]))}; display-only preview.</text>')
        else:
            out.append(f'<text x="{x+14}" y="{y+85}" font-family="sans-serif" font-size="17" fill="#53677b">Unavailable in supplied evidence</text>')
            out.append(f'<text x="{x+14}" y="{y+117}" font-family="sans-serif" font-size="13" fill="#53677b">No replacement image has been invented.</text>')
    out.append('</svg>')
    return "\n".join(out) + "\n"


def _raster(svg, path):
    """Rasterize this module's bounded SVG vocabulary with Pillow, not AI images.

    Coordinates/text/labels come from the same SVG. Existing PNGs are resized
    only for display; their original numeric arrays and trace files are untouched.
    """
    from PIL import Image, ImageDraw, ImageFont
    def font_at_size(size, bold=False):
        candidates = [
            "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf",
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else
            "/System/Library/Fonts/Supplemental/Arial.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
            "/Library/Fonts/Arial Bold.ttf" if bold else "/Library/Fonts/Arial.ttf",
        ]
        for candidate in candidates:
            try:
                return ImageFont.truetype(candidate, size)
            except OSError:
                pass
        try:
            return ImageFont.load_default(size=size)
        except TypeError as error:
            raise RuntimeError("PNG graphics need a scalable font or Pillow >=10.1; SVG remains available") from error
    root = ET.fromstring(svg)
    scale = 2
    width, height = int(root.get("width")), int(root.get("height"))
    canvas = Image.new("RGB", (width * scale, height * scale), COLORS["backdrop"])
    draw = ImageDraw.Draw(canvas)
    def number(element, key, default=0):
        raw = element.get(key, str(default))
        return (height if key == "height" else width) if raw == "100%" else float(raw)
    for element in root:
        tag = element.tag.rsplit("}", 1)[-1]
        if tag == "rect":
            x, y, w, h = [number(element, k) for k in ("x", "y", "width", "height")]
            draw.rounded_rectangle([x*scale,y*scale,(x+w)*scale,(y+h)*scale],
                radius=number(element,"rx")*scale, fill=element.get("fill"), outline=element.get("stroke"), width=scale)
        elif tag == "text":
            size = int(float(element.get("font-size", "16")) * scale)
            font = font_at_size(size, element.get("font-weight") == "bold")
            draw.text((number(element,"x")*scale,number(element,"y")*scale), element.text or "", font=font,
                      fill=element.get("fill",COLORS["ink"]), anchor="ls")
        elif tag == "path":
            values = [float(v) for v in re.findall(r"-?\d+(?:\.\d+)?", element.get("d", ""))]
            if "C" in element.get("d", ""):
                x0,y0,x1,y1,x2,y2,x3,y3 = values
                points = []
                for step in range(31):
                    t = step/30; u = 1-t
                    points.append(((u**3*x0+3*u*u*t*x1+3*u*t*t*x2+t**3*x3)*scale,
                                   (u**3*y0+3*u*u*t*y1+3*u*t*t*y2+t**3*y3)*scale))
            else:
                points = [(values[i]*scale,values[i+1]*scale) for i in range(0,len(values),2)]
            draw.line(points, fill=element.get("stroke",COLORS["muted"]), width=5)
            if element.get("marker-end") and len(points)>1:
                px,py=points[-1];qx,qy=points[-2];length=math.hypot(px-qx,py-qy) or 1
                ux,uy=(px-qx)/length,(py-qy)/length
                draw.polygon([(px,py),(px-16*ux+8*uy,py-16*uy-8*ux),
                              (px-16*ux-8*uy,py-16*uy+8*ux)],fill=COLORS["muted"])
        elif tag == "image":
            content = base64.b64decode(element.get("href").split(",",1)[1])
            image = Image.open(io.BytesIO(content)).convert("RGB")
            w,h=int(number(element,"width")*scale),int(number(element,"height")*scale)
            ratio = min(w/image.width, h/image.height)
            image = image.resize((max(1,round(image.width*ratio)),max(1,round(image.height*ratio))),
                                 resample=Image.Resampling.NEAREST)
            canvas.paste(image,(int(number(element,"x")*scale)+(w-image.width)//2,
                                int(number(element,"y")*scale)+(h-image.height)//2))
    canvas.save(path.with_suffix(".png"))


def render(out, *, trace=None, raster=False):
    evidence = trace_evidence(trace)
    out = Path(out)
    if out.exists() or out.is_symlink():
        raise FileExistsError("Use a new graphic output directory")
    out.mkdir(parents=True)
    charts = [("original_ND2_to_well.svg", "Original ND2 to whole-well analysis", ND2_NODES, ND2_EDGES),
              ("segmentation_tracking.svg", "Segmentation, soma tracking and phenotype", SEG_NODES, SEG_EDGES)]
    exports = []
    for name, title, nodes, edges in charts:
        svg = build_svg(title, nodes, edges, evidence)
        (out / name).write_text(svg)
        exports.append(name)
        if raster:
            _raster(svg, out / name)
            exports.append(str(Path(name).with_suffix(".png")))
    public = {key: value for key, value in evidence.items() if key != "previews"}
    public["previews"] = [{key: value for key, value in item.items() if key != "data_url"} for item in evidence["previews"]]
    public.update(schema_version="tmem.graphic_flowcharts.v1", evidence_type="WORKFLOW_DESIGN_WITH_OPTIONAL_VERIFIED_RECORDED_PREVIEWS",
                  scientific_inference_ready=False, real_accepted_ids=[],
                  script_sha256=sha(Path(__file__).read_bytes()), graphic_files=exports)
    (out / "flowchart_provenance.json").write_text(json.dumps(public, indent=2, allow_nan=False) + "\n")
    cards = ''.join(f'<section><h2>{html.escape(title)}</h2><a href="{name}">Open standalone SVG</a><img src="{name}" alt="{html.escape(title)}"></section>'
                    for name, title, _, _ in charts)
    (out / "index.html").write_text('<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>TMEM106B graphical processing flowcharts</title><style>body{font:17px system-ui;max-width:1250px;margin:30px auto;padding:0 20px;color:#14283e;background:#f4f7fb}img{width:100%;height:auto}section{margin:35px 0}a{color:#0759a4}pre{white-space:pre-wrap}</style>'
        '<h1>TMEM106B graphical processing flowcharts</h1><p>These are workflow designs. Recorded previews, when available, are copied from an integrity-verified trace. '
        'Trace integrity does not establish original ND2 processing, scientific accuracy, track approval or biological inference.</p>'
        '<p><a href="flowchart_provenance.json">Graphic provenance and missing stages</a></p>' + cards + '</html>')
    return public


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--trace", type=Path)
    parser.add_argument("--raster", action="store_true", help="Also export PNG using Pillow")
    args = parser.parse_args(argv)
    result = render(args.out, trace=args.trace, raster=args.raster)
    print("TMEM_GRAPHICS=" + str(args.out.resolve()))
    print("TMEM_GRAPHICS_EVIDENCE=" + result["evidence_type"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
