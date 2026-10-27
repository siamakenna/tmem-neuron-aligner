"""Numeric, source-bound processing stages with display-only previews.

The recorder observes arrays; it never supplies pixels or masks back to the
pipeline. A trace uses a new directory and preserves unavailable/failed stages
explicitly. Every numeric stage is saved as a pickle-free NPY, not only a PNG.
"""
from __future__ import annotations

import hashlib
import html
import json
from pathlib import Path
import re
import shutil
import tempfile

import numpy as np

SCHEMA = "tmem.processing_stage_trace.v1"
STATUSES = frozenset({"executed", "skipped", "unavailable", "failed"})
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,119}\Z")


def _json_safe(value):
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, np.ndarray):
        return _json_safe(value.tolist())
    if isinstance(value, np.generic):
        return _json_safe(value.item())
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, float) and not np.isfinite(value):
        # E.g. the production masked registration error is undefined. The
        # caller's details must describe that condition; JSON stores null.
        return None
    return value


def _write_json(path, value):
    path = Path(path)
    text = json.dumps(_json_safe(value), indent=2, allow_nan=False) + "\n"
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text)
    temporary.replace(path)


def _file_sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024**2), b""):
            digest.update(block)
    return digest.hexdigest()


def array_sha256(array):
    """Bind values, shape and exact dtype/byte order; independent of strides."""
    a = np.asarray(array)
    description = json.dumps({"dtype": a.dtype.str, "shape": list(a.shape)},
                             sort_keys=True, separators=(",", ":")).encode()
    digest = hashlib.sha256(description + b"\n")
    digest.update(np.ascontiguousarray(a).tobytes())
    return digest.hexdigest()


def _validate_array(array, axes):
    a = np.asarray(array)
    if axes not in {"YX", "CYX", "TCYX"} or len(axes) != a.ndim:
        raise ValueError("Stage axes must exactly describe YX, CYX or TCYX")
    if not a.size or min(a.shape) < 1 or a.dtype.kind not in "buif":
        raise ValueError("Stage requires a nonempty real numeric array without objects")
    if not np.isfinite(a).all():
        raise ValueError("Nonfinite quantitative stage pixels are not allowed")
    return a


def _stats(array):
    a = np.asarray(array)
    return _json_safe(dict(shape=list(a.shape), dtype=str(a.dtype),
        size=int(a.size), minimum=float(a.min()), maximum=float(a.max()),
        mean=float(np.mean(a, dtype=np.longdouble)), nonzero=int(np.count_nonzero(a)),
        nonfinite=0))


def _plain_relative(root, relative):
    relative = Path(relative)
    if relative.is_absolute() or ".." in relative.parts or "\\" in str(relative):
        raise ValueError("Unsafe trace artifact path")
    path = root / relative
    for component in [path, *path.parents]:
        if component == root.parent:
            break
        if component.is_symlink():
            raise ValueError("Linked trace artifacts are not allowed")
    if not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("Missing trace artifact: " + str(relative))
    return path


class StageTrace:
    """Observe an execution in a new directory; all files are independently bound.

    ``luts`` is a mapping of channel labels to display.LUT instances or their
    metadata dictionaries. Limits stay fixed for that channel through this run.
    Multichannel stages retain the complete numeric array. Their PNG shows the
    explicitly requested channel and first timepoint, never a projection.
    """

    def __init__(self, root, metadata=None, luts=None):
        self.root = Path(root)
        if self.root.is_symlink():
            raise ValueError("Trace root must not be linked")
        self.metadata = _json_safe(dict(metadata or {}))
        # Validate metadata before creating an output directory.
        json.dumps(self.metadata, allow_nan=False)
        from .display import LUT
        self.luts = {}
        for channel, value in dict(luts or {}).items():
            self.luts[str(channel)] = value if isinstance(value, LUT) else LUT(**dict(value))
        self.root.mkdir(parents=True, exist_ok=False)
        (self.root / "stages").mkdir()
        _write_json(self.root / "provenance.json", self.metadata)
        self.records = []
        self._names = set()
        self._finished = False

    def _plane(self, array, axes, channel):
        selections = {}
        plane = array
        if axes.startswith("T"):
            plane = plane[0]
            selections["time_index"] = 0
        if "C" in axes:
            channels = self.metadata.get("channels", ["405", "561", "488"])
            if isinstance(channels, dict):
                channels = [channels.get(str(i), channels.get(i)) for i in range(plane.shape[0])]
            channels = [str(label) for label in channels]
            if len(channels) != plane.shape[0] or channels.count(channel) != 1:
                raise ValueError("Explicit channel label does not uniquely identify the preview plane")
            index = channels.index(channel)
            plane = plane[index]
            selections.update(channel_index=index, channel_label=channel)
        return plane, selections

    def _preview(self, name, array, axes, channel, details):
        from .display import LUT, apply_lut_for_display
        plane, selection = self._plane(array, axes, channel)
        role = details.get("array_role", "")
        if plane.dtype == bool:
            lut = LUT(0, 1, source="boolean stage; display only")
            rgb = apply_lut_for_display(plane, lut)
            info = dict(mode="boolean-mask", lut=lut.metadata())
        elif role in {"labels", "component_labels"} or name.endswith("labels"):
            if plane.dtype.kind not in "ui" or np.any(plane < 0):
                raise ValueError("Label previews require nonnegative integer labels")
            # Deterministic categorical colors; adjacent label IDs need not
            # encode magnitude. These RGB values never enter calculations.
            labels = plane.astype(np.uint64)
            rgb = np.stack([((labels * factor) % 191 + 64).astype(np.uint8)
                            for factor in (67, 101, 149)], axis=-1)
            rgb[labels == 0] = 0
            info = dict(mode="categorical-label-colors-display-only", lut=None)
        else:
            color = channel if channel in {"488", "561"} else "gray"
            if role == "normalized_intensity":
                lut = LUT(0, 1, color, scope="normalized-diagnostic-stage",
                          source="declared normalized intensity0..1; display only")
            elif role == "correlation":
                lut = LUT(-1, 1, color, scope="correlation-diagnostic-stage",
                          source="declared correlation range-1..1; display only")
            elif role == "signed_response":
                limits = details.get("display_range", [-4, 4])
                if (not isinstance(limits, (list, tuple)) or len(limits) != 2
                        or any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in limits)):
                    raise ValueError("Signed-response display_range requires two finite numeric limits")
                lut = LUT(*limits, color, scope="signed-response-diagnostic-stage",
                    source="explicit signed normalized-response display range; display only")
            elif role == "dog_response":
                lut = self.luts.get("DoG", LUT(-512, 512, "gray", scope="fixed-trace-DoG",
                    source="explicit default signed DoG display-512..512 stored-pixel units; display only"))
            elif role == "support_count":
                limits = details.get("display_range")
                if (not isinstance(limits, (list, tuple)) or len(limits) != 2
                        or any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in limits)
                        or limits[0] != 0 or plane.dtype.kind not in "ui" or np.any(plane < 0)):
                    raise ValueError("Support-count previews require integer counts and explicit display_range=[0,total]")
                lut = LUT(*limits, color, scope="consensus-support-count-stage",
                          source="explicit0..total declared valid-mask count; display only")
            elif role == "illumination_field":
                lut = self.luts.get("IC_field", LUT(.1, 2, "gray", scope="fixed-trace-IC-field",
                    source="explicit default relative flatfield display0.1..2.0; display only"))
            else:
                lut = self.luts.get(channel, LUT(0, 65535, color,
                    scope="fixed-trace-channel", source="explicit default stored-16-bit display range"))
            rgb = apply_lut_for_display(plane, lut)
            info = dict(mode="fixed-channel-LUT-display-only", lut=lut.metadata(),
                display_below_low=int(np.count_nonzero(plane < lut.low)),
                display_above_high=int(np.count_nonzero(plane > lut.high)))
        info.update(axes="YX", selected_from_axes=axes, selection=selection,
                    projection_performed=False, quantitative_array_unchanged=True)
        return rgb, info

    def capture(self, name, array=None, *, axes="YX", channel="488", parents=(),
                why="", parameters=None, status="executed", details=None):
        if self._finished:
            raise ValueError("A finished trace cannot capture additional stages")
        if not isinstance(name, str) or not _NAME.fullmatch(name) or name in self._names:
            raise ValueError("Stage name must be a unique safe filename stem")
        if status not in STATUSES:
            raise ValueError("Unknown processing stage status")
        if isinstance(parents, str) or len(set(parents)) != len(parents):
            raise ValueError("Stage parents must be distinct existing stage names")
        parents = list(parents)
        if any(parent not in self._names for parent in parents):
            raise ValueError("Stage parent is missing or occurs after its child")
        if not isinstance(why, str) or not why.strip():
            raise ValueError("Each stage requires its actual purpose in why")
        if status == "executed" and array is None:
            raise ValueError("An executed stage requires numeric output")
        if status in {"skipped", "unavailable"} and array is not None:
            raise ValueError("Skipped/unavailable stages must not invent numeric output")
        details = _json_safe(dict(details or {}))
        parameters = _json_safe(dict(parameters or {}))
        channel = str(channel)
        record = dict(stage=name, status=status, why=why, parents=parents,
            axes=axes, channel=channel, parameters=parameters, details=details,
            metadata=self.metadata, artifacts={})
        # A defensive snapshot makes later caller mutations unable to rewrite
        # the already observed stage; the original input is never modified.
        a = None if array is None else np.array(_validate_array(array, axes), copy=True)
        temporary = Path(tempfile.mkdtemp(prefix=".capture_", dir=self.root))
        try:
            if a is not None:
                from PIL import Image
                numeric = temporary / "array.npy"
                np.save(numeric, a, allow_pickle=False)
                rgb, preview = self._preview(name, a, axes, channel, details)
                Image.fromarray(rgb).save(temporary / "preview.png")
                record.update(array_sha256=array_sha256(a), statistics=_stats(a),
                              preview=preview)
                for key, filename in [("numeric", "array.npy"), ("preview", "preview.png")]:
                    record["artifacts"][key] = dict(path=f"stages/{name}/{filename}",
                        sha256=_file_sha(temporary / filename), bytes=(temporary / filename).stat().st_size)
            _write_json(temporary / "stage.json", record)
            record["record_file"] = f"stages/{name}/stage.json"
            record["record_sha256"] = _file_sha(temporary / "stage.json")
            temporary.rename(self.root / "stages" / name)
        except Exception:
            shutil.rmtree(temporary, ignore_errors=True)
            raise
        self.records.append(record)
        self._names.add(name)
        # Persist a crash-readable ledger without asserting a finished run.
        # Stage documents are already atomic. Keep this progress index small:
        # repeating every numeric record at each capture creates quadratic I/O
        # for a nine-visit sensitivity trace with hundreds of intermediates.
        _write_json(self.root / "in_progress.json", dict(schema_version=SCHEMA,
            complete=False, stage_count=len(self.records), last_stage=name,
            stage_names=[r["stage"] for r in self.records],
            provenance_file="provenance.json"))
        return record

    def finish(self, summary=None):
        if self._finished:
            raise ValueError("A trace can be finished only once")
        summary = _json_safe(dict(summary or {}))
        graph = ["flowchart TD"]
        ids = {record["stage"]: f"s{index}" for index, record in enumerate(self.records)}
        cards = []
        for record in self.records:
            name = record["stage"]
            label = name.replace('"', "'") + " (" + record["status"] + ")"
            graph.append(f'    {ids[name]}["{label}"]')
            graph.extend(f"    {ids[parent]} --> {ids[name]}" for parent in record["parents"])
            esc = html.escape
            links = [f'<a href="{esc(record["record_file"])}">stage JSON</a>']
            image = ""
            for kind, artifact in record["artifacts"].items():
                links.append(f'<a href="{esc(artifact["path"])}">{esc(kind)}</a>')
                if kind == "preview":
                    image = f'<img loading="lazy" src="{esc(artifact["path"])}" alt="{esc(name)} display preview">'
            description = json.dumps(_json_safe(dict(axes=record["axes"], channel=record["channel"],
                parameters=record["parameters"], statistics=record.get("statistics"),
                details=record["details"], preview=record.get("preview"))), indent=2)
            cards.append(f'<article data-channel="{esc(record["channel"])}" '
                f'data-status="{esc(record["status"])}"><h2>{esc(name)}</h2><p class="status">{esc(record["status"])}</p>'
                f'<p>{esc(record["why"])}</p>{image}<p>{" · ".join(links)}</p>'
                f'<details><summary>Parameters, I/O and numeric change</summary><pre>{esc(description)}</pre></details></article>')
        (self.root / "processing_flow.mmd").write_text("\n".join(graph) + "\n")
        title = html.escape(str(self.metadata.get("title", "TMEM106B processing stages")))
        page = '<!doctype html><html lang="en"><meta charset="utf-8">'
        page += f'<meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title>'
        page += '<style>body{font:16px system-ui;max-width:1100px;margin:32px auto;padding:0 20px;background:#f5f7f9;color:#18212a}article{background:white;border:1px solid #ccd4dc;border-radius:8px;padding:22px;margin:22px 0}img{max-width:100%;max-height:420px;image-rendering:pixelated;background:#111}.status{font-weight:700}pre{white-space:pre-wrap;overflow-wrap:anywhere}a{color:#0759a4}</style>'
        page += f'<header><h1>{title}</h1><p>Numeric arrays are preserved separately from display-only PNGs. '
        page += 'Missing stages stay explicit. Processing completion grants no track approval or biological inference.</p>'
        page += '<p><a href="manifest.json">Verified stage manifest</a> · <a href="provenance.json">Input provenance</a> · '
        page += '<a href="processing_flow.mmd">Recorded processing graph</a></p>'
        page += '<pre>' + html.escape(json.dumps(summary, indent=2)) + '</pre></header>'
        channels = sorted({record["channel"] for record in self.records})
        page += '<nav aria-label="Filter processing steps" style="position:sticky;top:0;background:#f5f7f9;padding:14px 0">'
        page += '<label>Find a step <input id="step-search" type="search" placeholder="visit, threshold, tracking…"></label> '
        page += '<label>Channel <select id="step-channel"><option value="">All</option>'
        page += ''.join(f'<option value="{html.escape(c)}">{html.escape(c)}</option>' for c in channels) + '</select></label> '
        page += '<label>Status <select id="step-status"><option value="">All</option>'
        page += ''.join(f'<option value="{s}">{s}</option>' for s in sorted(STATUSES)) + '</select></label> '
        page += '<output id="step-count" aria-live="polite"></output></nav>'
        script = '''<script>
const cards=Array.from(document.querySelectorAll('article'));
const search=document.getElementById('step-search');
const channel=document.getElementById('step-channel');
const status=document.getElementById('step-status');
function filterSteps(){let count=0;const query=search.value.trim().toLowerCase();
 for(const card of cards){const show=(!query||card.textContent.toLowerCase().includes(query))
  &&(!channel.value||card.dataset.channel===channel.value)
  &&(!status.value||card.dataset.status===status.value);card.hidden=!show;if(show)count++;}
 document.getElementById('step-count').textContent=count+' / '+cards.length+' steps';}
for(const control of [search,channel,status])control.addEventListener('input',filterSteps);
filterSteps();</script>'''
        (self.root / "index.html").write_text(page + "".join(cards) + script + "</html>")
        progress = self.root / "in_progress.json"
        if progress.exists():
            progress.unlink()
        files = {p.relative_to(self.root).as_posix(): _file_sha(p)
                 for p in sorted(self.root.rglob("*")) if p.is_file()}
        manifest = dict(schema_version=SCHEMA, complete=True, metadata=self.metadata,
            stages=self.records, summary=summary, files=files,
            successful_execution=any(r["status"] == "executed" for r in self.records)
                and all(r["status"] != "failed" for r in self.records),
            stage_status_counts={status: sum(r["status"] == status for r in self.records)
                                 for status in sorted(STATUSES)},
            all_declared_stages_executed=bool(self.records)
                and all(r["status"] == "executed" for r in self.records),
            scientific_inference_ready=False, real_accepted_ids=[])
        _write_json(self.root / "manifest.json", manifest)
        verify_trace(self.root)
        self._finished = True
        return manifest


def capture(trace, name, array=None, **kwargs):
    """Optional production observer: disabled recording has no pixel side effects."""
    if trace is None:
        return None
    # Replaceable observers also receive a snapshot. An in-place display
    # normalization in a visualization stub must not modify scientific pixels.
    snapshot = None if array is None else np.array(array, copy=True)
    return trace.capture(name, snapshot, **kwargs)


def verify_trace(root):
    """Verify finalized inventory, stage documents and every saved numeric array."""
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Trace root must be a real directory")
    manifest = json.loads(_plain_relative(root, "manifest.json").read_text())
    if manifest.get("schema_version") != SCHEMA or manifest.get("complete") is not True:
        raise ValueError("Trace is not a finalized known-schema execution")
    if manifest.get("scientific_inference_ready") is not False or manifest.get("real_accepted_ids") != []:
        raise ValueError("A diagnostic trace cannot assert scientific approval or accepted tracks")
    expected = manifest.get("files")
    if not isinstance(expected, dict):
        raise ValueError("Trace file inventory is missing")
    actual = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}
    if any(p.is_symlink() for p in root.rglob("*")) or actual != set(expected) | {"manifest.json"}:
        raise ValueError("Trace inventory changed or contains links")
    for relative, sha in expected.items():
        if _file_sha(_plain_relative(root, relative)) != sha:
            raise ValueError("Trace artifact bytes changed: " + relative)
    seen = set()
    for record in manifest.get("stages", []):
        name = record.get("stage")
        if not isinstance(name, str) or not _NAME.fullmatch(name) or name in seen:
            raise ValueError("Invalid or duplicated stage identity")
        if record.get("status") not in STATUSES or any(p not in seen for p in record.get("parents", [])):
            raise ValueError("Invalid stage state or ancestry")
        expected_record = dict(record)
        record_file = expected_record.pop("record_file")
        record_sha = expected_record.pop("record_sha256")
        saved = _plain_relative(root, record_file)
        if _file_sha(saved) != record_sha or json.loads(saved.read_text()) != expected_record:
            raise ValueError("Stage record binding changed: " + name)
        artifacts = record.get("artifacts", {})
        if record["status"] == "executed" and "numeric" not in artifacts:
            raise ValueError("Executed stage has no quantitative output")
        if record["status"] in {"unavailable", "skipped"} and artifacts:
            raise ValueError("Unavailable stage has fabricated artifacts")
        for artifact in artifacts.values():
            path = _plain_relative(root, artifact["path"])
            if _file_sha(path) != artifact["sha256"] or path.stat().st_size != artifact["bytes"]:
                raise ValueError("Stage artifact binding changed: " + name)
        if "numeric" in artifacts:
            array = np.load(_plain_relative(root, artifacts["numeric"]["path"]), allow_pickle=False)
            _validate_array(array, record["axes"])
            if array_sha256(array) != record["array_sha256"] or _stats(array) != record["statistics"]:
                raise ValueError("Stage numeric values/shape/dtype changed: " + name)
        seen.add(name)
    records = manifest.get("stages", [])
    counts = {status: sum(r["status"] == status for r in records) for status in sorted(STATUSES)}
    if (manifest.get("stage_status_counts") != counts
            or manifest.get("successful_execution") != (bool(counts["executed"]) and counts["failed"] == 0)
            or manifest.get("all_declared_stages_executed") != (bool(records) and counts["executed"] == len(records))):
        raise ValueError("Trace execution summary disagrees with its actual stage states")
    return manifest
