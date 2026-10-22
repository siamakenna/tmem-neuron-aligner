"""Compact stage artifacts, explicit provenance and an incremental HTML slideshow."""
import hashlib
import html
import json
import re
from pathlib import Path

import numpy as np
from PIL import Image

from .display import apply_lut_for_display


def json_safe(value):
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    if isinstance(value, np.ndarray):
        return json_safe(value.tolist())
    if isinstance(value, np.generic):
        return json_safe(value.item())
    if isinstance(value, float) and not np.isfinite(value):
        return None
    if isinstance(value, Path):
        return str(value)
    return value


def write_json(path, value):
    Path(path).write_text(json.dumps(json_safe(value), indent=2, allow_nan=False) + "\n")


def array_stats(image, lut):
    a = np.asarray(image)
    finite = np.isfinite(a)
    v = a[finite].astype(float)
    return dict(
        shape=list(a.shape), dtype=str(a.dtype), finite=int(finite.sum()),
        nonfinite=int((~finite).sum()), minimum=float(v.min()) if v.size else None,
        maximum=float(v.max()) if v.size else None, mean=float(v.mean()) if v.size else None,
        percentiles=np.percentile(v, [1, 50, 99.6]) if v.size else [],
        display_below_low=int(np.count_nonzero(v < lut.low)),
        display_above_high=int(np.count_nonzero(v > lut.high)),
        quantitative_uint16_overflow=int(np.count_nonzero(v > 65535)),
        quantitative_negative=int(np.count_nonzero(v < 0)),
        sha256=hashlib.sha256(np.ascontiguousarray(a).tobytes()).hexdigest(),
    )


class Evidence:
    """One new directory per invocation; no overwrite of historical results."""
    def __init__(self, root, context):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=False)
        self.context = dict(context)
        self.records = []
        write_json(self.root / "provenance.json", self.context)

    def stage(self, name, image, lut, *, channel, parameters=None):
        if not re.fullmatch(r"[A-Za-z0-9_-]+", name):
            raise ValueError("Stage name must be a plain filename stem")
        if any(r["stage"] == name for r in self.records):
            raise ValueError(f"Duplicate stage: {name}")
        a = np.asarray(image)
        rgb = Image.fromarray(apply_lut_for_display(a, lut))
        rgb.thumbnail((384, 384), Image.Resampling.NEAREST)
        rgb.save(self.root / f"{name}.png")
        record = dict(stage=name, channel=channel, lut=lut.metadata(),
                      parameters=parameters or {}, statistics=array_stats(a, lut),
                      context=self.context)
        write_json(self.root / f"{name}.json", record)
        self.records.append(record)
        return record

    def finish(self, diagnostics):
        write_json(self.root / "diagnostics.json", diagnostics)
        write_json(self.root / "stages.json", self.records)
        slides = []
        for record in self.records:
            name = record["stage"]
            caption = f"Channel: {record['channel']} | LUT: {record['lut']}"
            slides.append(f'<section><h2>{html.escape(name)}</h2>'
                          f'<img src="{name}.png"><p>{html.escape(caption)}</p></section>')
        title = html.escape(str(self.context.get("title", "TMEM106B stage evidence")))
        status = html.escape(str(self.context.get("evidence_type", "unclassified")))
        page = '''<!doctype html><meta charset="utf-8"><title>TMEM106B evidence</title>
<style>body{background:#102127;color:#f7faf8;font:20px system-ui;margin:0}
section{box-sizing:border-box;min-height:100vh;padding:4vw;scroll-snap-align:start}
html{scroll-snap-type:y proximity}img{height:65vh;max-width:90vw;object-fit:contain;image-rendering:pixelated}
pre{font-size:14px;white-space:pre-wrap}p{max-width:70em}</style>'''
        page += f"<section><h1>{title}</h1><p>{status}</p>"
        page += "<p>Scroll for stage images. PNGs are display artifacts; JSON contains numeric QC. "
        page += "No biological conclusion is established by this audit.</p><pre>"
        page += html.escape(json.dumps(json_safe(diagnostics), indent=2)) + "</pre></section>"
        page += "".join(slides)
        (self.root / "slides.html").write_text(page)
