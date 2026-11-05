"""Observed calls into the supplied checkout; never an alternate science engine."""
from __future__ import annotations

import base64
from contextlib import contextmanager
import html
import importlib
import inspect
import json
import math
from pathlib import Path
import sys

import numpy as np


def clean(value):
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [clean(v) for v in value]
    if isinstance(value, np.ndarray):
        return clean(value.tolist())
    if isinstance(value, np.generic):
        return clean(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, Path):
        return str(value)
    return value


def save(path, value):
    Path(path).write_text(json.dumps(clean(value), sort_keys=True, indent=2, allow_nan=False) + "\n")


def read_selection(observation, channels, max_read_bytes, *, nd2_module=None):
    """Choose explicit P/T/Z and remap C from each file's own metadata."""
    if nd2_module is None:
        import nd2 as nd2_module
    with nd2_module.ND2File(observation["path"]) as image:
        sizes = {str(k): int(v) for k, v in image.sizes.items()}
        names = [str(getattr(getattr(c, "channel", c), "name", "UNKNOWN"))
                 for c in image.metadata.channels]
        h = observation["header"]
        if sizes != h["sizes"] or list(sizes) != h["axis_order"] or names != h["channels"] or str(image.dtype) != h["dtype"]:
            raise ValueError("ND2 header changed after inventory")
        rgb = getattr(image, "is_rgb", None)
        if rgb is None or bool(rgb) or h.get("is_rgb") is not False:
            raise ValueError("RGB/unknown color encoding cannot enter this adapter")
        if set(sizes) - set("PTZCYX"):
            raise ValueError("Unsupported ND2 axis: " + repr(sizes))
        if len(channels) != sizes.get("C", 1):
            raise ValueError("Declare every source channel; no implicit channel dropping")
        indices = {"P": observation["position"], "T": observation["time"], "Z": observation["z"]}
        selection, remaining = [], []
        for axis, length in sizes.items():
            if axis in indices:
                index = indices[axis]
                if not 0 <= index < length:
                    raise ValueError("Selection outside declared ND2 axis")
                selection.append(index)
            else:
                selection.append(slice(None))
                remaining.append(axis)
        estimated = sizes.get("C", 1) * sizes["Y"] * sizes["X"] * np.dtype(image.dtype).itemsize
        if estimated > max_read_bytes:
            raise ValueError("Selected original ND2 field exceeds max_read_bytes")
        a = np.asarray(image.to_dask()[tuple(selection)].compute())
        if a.shape != tuple(sizes[c] for c in remaining) or a.dtype != np.dtype(image.dtype):
            raise ValueError("Decoded pixels disagree with source-bound shape/dtype")
    if "C" not in remaining:
        a = np.expand_dims(a, 0)
        remaining.insert(0, "C")
    a = np.transpose(a, [remaining.index(c) for c in "CYX"])
    order = []
    for role in channels:
        label = observation["channel_map"][role]
        if names.count(label) != 1:
            raise ValueError("Ambiguous per-visit channel label")
        order.append(names.index(label))
    if a.dtype.kind not in "buif" or not np.isfinite(a).all():
        raise ValueError("Selected detector pixels must be finite real values")
    return a[order].copy(), {"source_channel_names": names, "canonical_channels": channels,
                             "canonical_to_source_indices": order, "selection": indices,
                             "pixel_interpretation": "no projection, no rescale, exact selected detector pixels"}


class Observer:
    """Production observer. Compact previews plus optional exact stage arrays.

    Scientific arrays never come from a LUT. The same channel LUT is fixed at
    every visit. Large-array omission is explicit in each record, never hidden.
    """
    def __init__(self, root, channels, luts, identity, arrays=False):
        self.root = Path(root)
        self.root.mkdir()
        self.channels, self.luts, self.identity = channels, luts, identity
        self.arrays = arrays
        self.records = []
        self.names = set()

    def capture(self, name, array=None, **metadata):
        import re
        from PIL import Image
        from full_dataset import object_sha
        if not re.fullmatch(r"[A-Za-z0-9_-]+", name) or name in self.names:
            raise ValueError("Unsafe/duplicate stage name: " + name)
        self.names.add(name)
        ci = (metadata.get("details") or {}).get("channel_index")
        if ci is not None:
            metadata = dict(metadata, channel=self.channels[int(ci)],
                            details=dict(metadata["details"], production_observer_channel_label=metadata.get("channel"),
                                         canonical_channel_from_per_visit_metadata=self.channels[int(ci)]))
        record = {"id": name, **clean(metadata), "preview": None, "numeric_array": None}
        if array is not None:
            a = np.asarray(array)
            if a.size == 0:
                raise ValueError("Empty executed stage")
            record.update(shape=list(a.shape), dtype=str(a.dtype),
                          array_sha256=object_sha({"shape": list(a.shape), "dtype": str(a.dtype),
                          "bytes_sha256": __import__("hashlib").sha256(np.ascontiguousarray(a).tobytes()).hexdigest()}))
            if self.arrays:
                p = self.root / (name + ".npy")
                np.save(p, a, allow_pickle=False)
                record["numeric_array"] = p.name
            else:
                record["numeric_array_omission"] = "compact stage policy; original pixels, final preprocessed and registered arrays retained separately"
            plane = a
            while plane.ndim > 2:
                channel = metadata.get("channel", self.identity)
                ci = self.channels.index(channel) if plane.ndim == 3 and plane.shape[0] == len(self.channels) and channel in self.channels else 0
                plane = plane[ci]
            role = (metadata.get("details") or {}).get("array_role", "")
            channel = metadata.get("channel", self.identity)
            if a.dtype == bool:
                limits = [0, 1]
            elif role == "normalized_intensity":
                limits = [0, 1]
            elif role in {"correlation", "signed_response"}:
                limits = [-1, 1] if role == "correlation" else [-4, 4]
            elif role == "illumination_field":
                limits = [0.1, 2]
            else:
                limits = self.luts.get(channel, self.luts[self.identity])
            low, high = limits
            display = np.nan_to_num(plane.astype(float), nan=low, neginf=low, posinf=high)
            display = np.rint(np.clip((display - low) / (high - low), 0, 1) * 255).astype(np.uint8)
            if role in {"labels", "component_labels"}:
                labels = plane.astype(np.uint64)
                rgb = np.stack([((labels * factor) % 191 + 64).astype(np.uint8) for factor in [67, 101, 149]], axis=-1)
                rgb[labels == 0] = 0
                preview = Image.fromarray(rgb)
                record["preview_mode"] = "categorical label colors; display only"
            else:
                preview = Image.fromarray(display)
            preview.thumbnail((640, 640))
            p = self.root / (name + ".png")
            preview.save(p)
            record.update(preview=p.name, preview_lut=limits, preview_display_only=True)
        self.records.append(record)
        return record

    def finish(self):
        save(self.root / "STAGES.json", self.records)
        # Each node embeds its own real image. No synthetic stand-ins and no external paths.
        cards = [r for r in self.records if r.get("preview")]
        width, cardw, cardh = 1260, 400, 270
        height = 80 + math.ceil(len(cards) / 3) * cardh
        svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
               '<rect width="100%" height="100%" fill="#101826"/>',
               '<text x="24" y="32" fill="white" font-family="sans-serif" font-size="20">Actual source pixels: ordered processing intermediates</text>',
               '<text x="24" y="57" fill="#b9c7df" font-family="sans-serif" font-size="13">Fixed display limits; masks and LUT boxes are diagnostic candidates; skipped stages listed in STAGES.json.</text>']
        for i, r in enumerate(cards):
            x, y = 20 + (i % 3) * 415, 80 + (i // 3) * cardh
            data = base64.b64encode((self.root / r["preview"]).read_bytes()).decode()
            svg.append(f'<g><rect x="{x}" y="{y}" width="{cardw}" height="250" rx="8" fill="#213048"/>')
            svg.append(f'<text x="{x+10}" y="{y+21}" fill="white" font-family="sans-serif" font-size="11">{html.escape(r["id"])}</text>')
            svg.append(f'<image x="{x+8}" y="{y+32}" width="384" height="190" href="data:image/png;base64,{data}"/>')
            svg.append(f'<text x="{x+10}" y="{y+239}" fill="#c4d6ef" font-family="sans-serif" font-size="10">array {r["array_sha256"][:16]} | LUT {html.escape(str(r["preview_lut"]))}</text></g>')
            if i + 1 < len(cards) and i % 3 != 2:
                svg.append(f'<path d="M{x+cardw} {y+130}h12m-4 -4l4 4 -4 4" fill="none" stroke="#a0b3cc" stroke-width="2"/>')
        svg.append("</svg>")
        (self.root / "ACTUAL_IMAGE_FLOWCHART.svg").write_text("\n".join(svg))

    def capture_display(self, name, image, source_array, why):
        from full_dataset import digest
        if name in self.names:
            raise ValueError("Duplicate rendered stage")
        self.names.add(name)
        path = self.root / (name + ".png")
        image.save(path)
        self.records.append({"id": name, "preview": path.name, "numeric_array": None,
                             "array_sha256": __import__("hashlib").sha256(np.ascontiguousarray(source_array).tobytes()).hexdigest(),
                             "preview_lut": self.luts[self.identity], "preview_sha256": digest(path),
                             "display_only": True, "why": why})


def attach_repo(repo):
    repo = Path(repo).resolve()
    for p in [repo / "src", repo / "scripts", repo]:
        sys.path.insert(0, str(p))
    import tmem_align
    if not Path(tmem_align.__file__).resolve().is_relative_to(repo):
        raise ValueError("Imported tmem_align does not come from bound checkout")
    pilot = importlib.import_module("run_260213_longitudinal_pilot")
    tracker = importlib.import_module("make_soma_anchored_bbox_movies_v2")
    from tmem_align import preprocess
    for function, names in [(preprocess.preprocess_image, {"trace", "trace_prefix"}),
                            (pilot.register_stack, {"well", "rows", "alignment_channel_index", "alignment_channel_label"}),
                            (tracker.segment_neuron_in_box, {"trace", "trace_prefix"})]:
        if not names.issubset(inspect.signature(function).parameters):
            raise ValueError("Current checkout's observed science API changed; adapter review required")
    for module in [pilot, tracker, preprocess]:
        if not Path(module.__file__).resolve().is_relative_to(repo):
            raise ValueError("Science module imported outside bound checkout")
    return pilot, tracker, preprocess


def _calibration(obs, profile, channels):
    fields = {}
    calibration = obs.get("calibration", {})
    for key in ["flatfield", "darkfield"]:
        spec = calibration.get(key)
        if spec is None:
            fields[key] = None
            continue
        from full_dataset import digest
        if not spec.get("provenance") or not spec.get("sha256") or spec.get("channels") != channels:
            raise ValueError("Calibration requires exact source hash, provenance and canonical channel order")
        path = Path(spec["path"]).expanduser().resolve(strict=True)
        if digest(path) != spec["sha256"]:
            raise ValueError("Calibration bytes changed")
        a = np.load(path, allow_pickle=False)
        if not np.isfinite(a).all() or (key == "flatfield" and np.any(a <= 0)):
            raise ValueError("Invalid physical calibration")
        fields[key] = a
    return fields


def _candidate_tracks(registered, tracker, observer, profile, qc, out):
    """One automated exemplar per series: candidate, not an accepted identity."""
    identity = profile["channels"].index(profile["identity_channel"])
    if profile["identity_channel"] != "488" or profile["name"] != "february_neuron":
        observer.capture("soma_tracking_not_applicable", status="unavailable",
                         why="The neuronal segmentation model is not validated for this assay.")
        return {"status": "not_applicable", "accepted": False}
    if min(registered.shape[-2:]) < 128:
        observer.capture("soma_tracking_unavailable", status="unavailable", why="Frame smaller than required 128-pixel production box")
        return {"status": "unavailable_small_frame", "accepted": False}
    from tmem_align.audit_v1.display import LUT
    from tmem_align.audit_v1.visualization import propose_lut_bbox
    day8 = registered[0, identity]
    tuning = profile["processing"].get("tracking", {})
    bbox_size = tuning.get("bbox_size", 128)
    min_area = tuning.get("min_area", 180)
    search_radius = tuning.get("search_radius", 60)
    anchor = tracker.auto_day8_anchor(day8, radius=tuning.get("initial_search_radius", 45))
    y, x = map(float, anchor)
    template = tracker.make_template(day8, y, x, tuning.get("template_size", 41), trace=observer, trace_prefix="template")
    rows = []
    for i, day in enumerate(profile["days"]):
        image = registered[i, identity]
        cy, cx, score = (y, x, 1.0) if i == 0 else tracker.track_anchor(image, template, y, x, search_radius, trace=observer, trace_prefix=f"d{day}_tracking")
        # Keep reference coordinates fixed. The matcher is a proposal only.
        try:
            segmented = tracker.segment_neuron_in_box(image, cy, cx, bbox_size, min_area,
                                                      trace=observer, trace_prefix=f"d{day}_segmentation")
            segmentation_ok = True
        except RuntimeError as exc:
            if isinstance(exc, tracker.SegmentationTraceError):
                raise
            segmented = (None, {"status": "failed", "reason": str(exc)})
            segmentation_ok = False
        low, high = profile["luts"]["488"]
        # Restrict LUT component search to the same production spatial box.
        from tmem_align.audit_v1.contracts import Bounds
        search = Bounds(*tracker.square_bounds(cy, cx, bbox_size, *image.shape))
        bbox = propose_lut_bbox(image, LUT(low, high, "488"), anchor_yx=(cy, cx), search_bounds=search,
                                range_policy="within_range", min_area=1)
        # Same actual spatial viewport before/after box display. The box never
        # clips the segmentation or changes any measurement pixel.
        from PIL import Image, ImageDraw
        limits = np.clip((image[search.y0:search.y1, search.x0:search.x1].astype(float) - low) / (high-low), 0, 1)
        before = Image.fromarray(np.rint(limits * 255).astype(np.uint8)).convert("RGB")
        after = before.copy()
        if bbox["bounds"]:
            b = bbox["bounds"]
            ImageDraw.Draw(after).rectangle((b["x0"]-search.x0, b["y0"]-search.y0,
                                             b["x1"]-search.x0-1, b["y1"]-search.y0-1), outline="#ffb340", width=2)
            full_area = (search.y1-search.y0) * (search.x1-search.x0)
            box_area = (b["y1"]-b["y0"]) * (b["x1"]-b["x0"])
            bbox["display_area_reduction_fraction"] = 1 - box_area / full_area
            bbox["benefit_interpretation"] = "smaller inspection area only; segmentation accuracy benefit unmeasured"
        panel = Image.new("RGB", (before.width * 2, before.height))
        panel.paste(before, (0, 0)); panel.paste(after, (before.width, 0))
        panel.save(out / f"day{day:02}_LUT_BOX_BEFORE_AFTER.png")
        observer.capture_display(f"d{day}_LUT_box_before_after", panel, image,
            "Same actual crop, fixed LUT, before/after displaying within-range component bounds; measurement geometry unchanged")
        # A bounded diagnostic sensitivity check calls the same production model.
        # Alternatives are retained, never automatically selected as a rescue.
        sensitivity = []
        for area in sorted({max(20, min_area-40), min_area, min(1000, min_area+40)}):
            try:
                mask, metadata = tracker.segment_neuron_in_box(image, cy, cx, bbox_size, area)
                baseline = segmented[0]
                union = int(np.count_nonzero(mask | baseline)) if baseline is not None else 0
                intersection = int(np.count_nonzero(mask & baseline)) if baseline is not None else 0
                sensitivity.append({"min_area": area, "status": "executed", "area_px": int(mask.sum()),
                                    "jaccard_to_primary": intersection / union if union else None,
                                    "adopted": area == min_area, "alternative_accepted": False})
            except RuntimeError as exc:
                sensitivity.append({"min_area": area, "status": "failed", "reason": str(exc), "adopted": False})
        record = {"day": day, "anchor_yx": [cy, cx], "tracking_score": score,
                  "registration_qc_pass": bool(qc[i]["qc_pass"]),
                  "candidate_tracking_valid": bool(np.isfinite(score) and score >= .25 and qc[i]["qc_pass"]
                       and qc[i].get("well_registration_qc_pass", True) and segmentation_ok),
                  "segmentation_return_type": type(segmented).__name__, "segmentation_ok": segmentation_ok,
                  "segmentation_metadata": clean(segmented[1]), "lut_box": bbox,
                  "segmentation_sensitivity": sensitivity,
                  "resolved_candidate_parameters": {"bbox_size": bbox_size, "min_area": min_area,
                       "search_radius": search_radius, "template_size": tuning.get("template_size", 41)},
                  "accepted_identity": False, "phenotype_exported": False}
        alternatives = []
        if i:
            for radius in sorted({max(10, search_radius-20), search_radius, min(100, search_radius+20)}):
                if radius == search_radius:
                    ry, rx, rs = cy, cx, score
                else:
                    ry, rx, rs = tracker.track_anchor(image, template, y, x, radius, trace=observer,
                                                      trace_prefix=f"d{day}_tracking_sensitivity_r{radius}")
                alternatives.append({"search_radius": radius, "anchor_yx": [ry, rx], "score": rs,
                                     "distance_from_primary_px": float(np.hypot(ry-cy, rx-cx)),
                                     "primary": radius == search_radius, "alternative_adopted": False})
        record["tracking_sensitivity"] = alternatives
        rows.append(record)
    save(out / "AUTOMATED_CANDIDATE_TRACK_PRIVATE.json", rows)
    return {"status": "diagnostic_candidate", "candidate_count": 1, "accepted": False,
            "scope": "one automatic exemplar per authentic site; not a census of neurons",
            "tracking_valid_visits": sum(r["candidate_tracking_valid"] for r in rows),
            "segmentation_failed_days": [r["day"] for r in rows if not r["segmentation_ok"]],
            "tracking_failed_days": [r["day"] for r in rows if not np.isfinite(r["tracking_score"]) or r["tracking_score"] < .25]}


def assemble_visit(frames, observations, canvas_yx, out, day, observer):
    from tmem_align.audit_v1.stitching import Tile, assemble_well
    tiles = [Tile(o["site"], a, *o["placement_yx"]) for a, o in zip(frames, observations)]
    mosaic, coverage, seams = assemble_well(tiles, canvas_yx)
    np.save(out / f"day{day:02}_mosaic.npy", mosaic, allow_pickle=False)
    np.save(out / f"day{day:02}_coverage.npy", coverage, allow_pickle=False)
    save(out / f"day{day:02}_SEAMS.json", seams)
    observer.capture(f"d{day}_assembled_well", mosaic, axes="CYX", why="Actual fields placed with authenticated integer detector offsets")
    if not np.isfinite(mosaic).all():
        raise ValueError("Well mosaic contains unobserved gaps; arrays/coverage retained, registration requires a validated support-aware adapter")
    return mosaic


@contextmanager
def observe_registration(pilot, observer):
    """Observe actual helper calls through the production optional trace hook.

    Science arguments/returns are unchanged. No masks are reconstructed and
    claimed to be historical estimation inputs. One worker has one process.
    """
    original = getattr(pilot, "register_translation", None)
    if original is None or not {"trace", "trace_prefix"}.issubset(inspect.signature(original).parameters):
        observer.capture("registration_estimation_trace_unavailable", status="unavailable",
                         why="Current checkout does not expose a compatible production registration observer hook")
        yield
        return
    counter = 0
    def observed(*args, **kwargs):
        nonlocal counter
        if kwargs.get("trace") is not None:
            raise ValueError("Production helper already has a trace observer; reconcile observers instead of replacing it")
        kwargs = dict(kwargs, trace=observer, trace_prefix=f"actual_alignment_estimation_{counter:03}")
        counter += 1
        return original(*args, **kwargs)
    pilot.register_translation = observed
    try:
        yield
    finally:
        pilot.register_translation = original


def resolve_registration_parameters(profile, *, frozen=None):
    if profile["name"] != "february_neuron":
        return {}
    if frozen is None:
        from tmem_align.audit_v1.plate_preflight import PARAMETERS
        frozen = PARAMETERS
    return {k: frozen[k] for k in ["ref_mode", "anchor_corr_thresh", "min_post_correlation", "plate_offsets"]}


def process(manifest, task, out):
    pilot, tracker, preprocessing = attach_repo(manifest["repo"])
    profile = manifest["profile"]
    channels = profile["channels"]
    settings = profile["processing"]
    observer = Observer(out / "stages", channels, profile["luts"], profile["identity_channel"],
                        arrays=settings.get("trace_arrays", False))
    frames, remaps = [], []
    try:
        for day in profile["days"]:
            observations = [o for o in task["observations"] if o["day"] == day]
            fields_this_visit = []
            for obs in observations:
                raw, mapping = read_selection(obs, channels, settings.get("max_read_bytes", 512 * 1024**2))
                remaps.append({"day": obs["day"], "site": obs["site"], **mapping})
                fields = _calibration(obs, profile, channels)
                frame = preprocessing.preprocess_image(raw, ic_field=fields["flatfield"], darkfield=fields["darkfield"],
                    background_radius=settings.get("background_radius"), trace=observer,
                    trace_prefix=f"d{day}_{obs['site']}_preprocess")
                fields_this_visit.append(frame)
            if task["scope"] == "well_mosaic_series":
                frame = assemble_visit(fields_this_visit, observations, task["canvas_yx"], out, day, observer)
            else:
                if len(fields_this_visit) != 1:
                    raise ValueError("Field-series task must read exactly one authentic site per visit")
                frame = fields_this_visit[0]
            # Durable bite-sized result for every visit; not all-or-nothing RAM aggregation.
            p = out / f"day{day:02}_preprocessed.npy"
            np.save(p, frame, allow_pickle=False)
            frames.append(frame)
        shape = frames[0].shape
        if any(f.shape != shape for f in frames):
            raise ValueError("Shapes changed across visits; no implicit resize allowed")
        stack = np.stack(frames)
        del frames
        identity_index = channels.index(profile["identity_channel"])
        rows = [{"day": day} for day in profile["days"]]
        registration_parameters = resolve_registration_parameters(profile)
        for i, day in enumerate(profile["days"]):
            observer.capture(f"d{day}_before_alignment", stack[i, identity_index], channel=profile["identity_channel"],
                             why="Same visit before the production longitudinal transform")
        with observe_registration(pilot, observer):
            registered, qc, crop = pilot.register_stack(stack, well=task["well"], rows=rows,
                alignment_channel_index=identity_index, alignment_channel_label=profile["identity_channel"],
                **registration_parameters)
        # Frozen QC defaults come from the live source. No threshold overrides.
        for i, day in enumerate(profile["days"]):
            observer.capture(f"d{day}_after_alignment", registered[i, identity_index], channel=profile["identity_channel"],
                             why="Same visit after transform; geometric QC remains in REGISTRATION_QC_PRIVATE.json")
            np.save(out / f"day{day:02}_registered.npy", registered[i], allow_pickle=False)
        del stack
        save(out / "CHANNEL_REMAPS_PRIVATE.json", remaps)
        save(out / "REGISTRATION_QC_PRIVATE.json", {"visits": qc, "common_crop": crop,
             "policy": "bound plate_preflight.PARAMETERS for February; helper defaults for unvalidated external assays",
             "resolved_parameters": registration_parameters})
        if settings.get("candidate_tracking", False):
            tracking = _candidate_tracks(registered, tracker, observer, profile, qc, out)
        else:
            observer.capture("soma_tracking_not_requested", status="unavailable",
                             why="Enable candidate_tracking in the bound profile for neuronal diagnostic exemplars")
            tracking = {"status": "not_requested", "accepted": False}
        failed = [profile["days"][i] for i, row in enumerate(qc) if not row["qc_pass"]]
        neuronal = profile["name"] == "february_neuron"
        nonreporter = task["well"][0] in "CDGHKL" and neuronal
        result = {"days": profile["days"], "qc_failed_days": failed, "scope": task["scope"],
                  "well_registration_qc_pass": all(r.get("well_registration_qc_pass", r["qc_pass"]) for r in qc),
                  "channels_checked_every_visit": True, "soma_tracking": tracking,
                  "optical_identity": "metadata labels only; independent optical authentication unresolved",
                  "mcherry_analysis_valid": None if nonreporter or not neuronal else False,
                  "mcherry_status": "N/A: assay does not declare mCherry" if not neuronal else
                       ("N/A: nonreporter row" if nonreporter else "unaccepted diagnostic; no phenotype export"),
                  "source_original_nd2": True, "whole_well_coverage_verified": False,
                  "ic_applied_days": sorted({o["day"] for o in task["observations"] if o.get("calibration", {}).get("flatfield")}),
                  "accepted_identities": 0}
        save(out / "RESULT_PRIVATE.json", result)
        return result
    finally:
        observer.finish()
