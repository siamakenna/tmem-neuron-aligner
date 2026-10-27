"""Source-bound diagnostics using the production processing functions.

Registered-track mode observes the existing registered coordinate frame. It does
not recreate historical IC/alignment, alter stored anchors, adopt a LUT box, or
release measurements. Raw-pair mode is a separate, explicitly supplied execution
of IC/background correction and 488-derived multichannel registration.
"""
from __future__ import annotations

import copy
import hashlib
import importlib
import json
import math
from pathlib import Path

import numpy as np

from .contracts import Bounds, require_cyx, strict_overlap
from .display import LUT
from .stage_trace import StageTrace, array_sha256, verify_trace
from .visualization import propose_lut_bbox, render_preview

DAYS = [8, 12, 16, 20, 25, 29, 32, 36, 39]
SOURCE_BASE = "cbed28cef77826cd8a5b45b6520fa81b127b3bfa"
DEFAULT_CONFIG = {
    "schema_version": "tmem.stage_diagnostics.v1",
    "bbox_size": 128,
    "segmentation": {"min_area": 180, "consensus_fraction": 0.60,
        "min_core_area": 80, "max_core_area": 2500, "phenotype_dilation": 2,
        "background_exclusion": 8, "puncta_min_size": 6},
    "tracking": {"template_size": 41, "search_radius": 60, "min_score": 0.25},
    "secondary_soma": {"search_radius": 52.0, "min_distance": 14,
        "peak_ratio_threshold": 0.55, "area_ratio_threshold": 0.30,
        "score_threshold": 0.40},
    "registration": {"upsample_factor": 10, "max_shift_pixels": 256.0,
        "robust_preprocess": False, "mask_percentile": 20.0},
    "sensitivity": {"segmentation_min_area": [140, 180, 220],
        "tracking_search_radius": [40, 60, 80]},
    "luts": {"488": {"low": 0, "high": 4095, "color": "488"},
        "561": {"low": 0, "high": 4095, "color": "561"},
        "IC_field": {"low": 0.1, "high": 2.0, "color": "gray"}},
    "lut_box": {"padding": 2, "min_area": 20, "range_policy": "visible"},
}
_KNOWN_SEGMENTATION_FAILURES = {
    "Empty 488 search region around soma anchor",
    "Insufficient local 488 signal at tracked soma anchor",
    "Insufficient 488 foreground in soma prior",
    "No plausible 488 component near tracked soma anchor after adaptive fallback",
}


def _safe(value):
    if isinstance(value, dict):
        return {str(k): _safe(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_safe(v) for v in value]
    if isinstance(value, np.ndarray):
        return _safe(value.tolist())
    if isinstance(value, np.generic):
        return _safe(value.item())
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def _write(path, value):
    Path(path).write_text(json.dumps(_safe(value), indent=2, allow_nan=False) + "\n")


def _finish(trace, summary):
    summary = dict(summary, software_execution_status="completed", real_accepted_ids=[],
                   scientific_inference_ready=False, production_eligible=False)
    _write(trace.root / "summary.json", summary)
    return trace.finish(summary)


def file_record(path):
    """Hash an exact regular input file; reject changes during the read."""
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError("Input must be a regular, unlinked file: " + str(path))
    before = path.stat()
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024**2), b""):
            digest.update(block)
    sha = digest.hexdigest()
    after = path.stat()
    if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
        raise ValueError("Input file changed while hashing: " + str(path))
    return dict(path=str(path.resolve()), sha256=sha, bytes=after.st_size,
                mtime_ns=after.st_mtime_ns)


def _merge(default, supplied, prefix="config"):
    if not isinstance(supplied, dict):
        raise ValueError(prefix + " must be an object")
    unknown = set(supplied) - set(default)
    if unknown:
        raise ValueError(prefix + " has unknown keys: " + ", ".join(sorted(unknown)))
    result = copy.deepcopy(default)
    for key, value in supplied.items():
        result[key] = _merge(default[key], value, prefix + "." + key) if isinstance(default[key], dict) else value
    return result


def _number(value, name, low, high, *, integer=False):
    kind = (int, np.integer) if integer else (int, float, np.integer, np.floating)
    if (isinstance(value, (bool, np.bool_)) or not isinstance(value, kind)
            or not np.isfinite(value) or not low <= value <= high):
        raise ValueError(f"{name} must be {'an integer' if integer else 'a finite number'} in [{low},{high}]")


def load_config(value=None):
    """Load bounded diagnostic parameters; unknown keys fail instead of guessing."""
    if isinstance(value, (str, Path)):
        value = json.loads(Path(value).read_text())
    cfg = _merge(DEFAULT_CONFIG, {} if value is None else value)
    _number(cfg["bbox_size"], "bbox_size", 128, 128, integer=True)
    if cfg["schema_version"] != DEFAULT_CONFIG["schema_version"] or cfg["bbox_size"] != 128:
        raise ValueError("Require the known schema and existing128-pixel crop contract")
    s, t, a = cfg["segmentation"], cfg["tracking"], cfg["registration"]
    for key, low, high in [("min_area", 1, 4096), ("min_core_area", 1, 4096),
            ("max_core_area", 1, 16384), ("phenotype_dilation", 0, 8),
            ("background_exclusion", 1, 32), ("puncta_min_size", 1, 128)]:
        _number(s[key], "segmentation." + key, low, high, integer=True)
    _number(s["consensus_fraction"], "consensus_fraction", 0.1, 1.0)
    if s["min_core_area"] > s["max_core_area"]:
        raise ValueError("Minimum core area exceeds maximum")
    _number(t["template_size"], "template_size", 9, 127, integer=True)
    if t["template_size"] % 2 != 1:
        raise ValueError("Diagnostic tracking template size must be odd")
    _number(t["search_radius"], "search_radius", 1, 256, integer=True)
    _number(t["min_score"], "min_score", -1, 1)
    secondary = cfg["secondary_soma"]
    _number(secondary["search_radius"], "secondary_soma.search_radius", 1, 64)
    _number(secondary["min_distance"], "secondary_soma.min_distance", 1, 64, integer=True)
    if secondary["min_distance"] >= secondary["search_radius"]:
        raise ValueError("Secondary-soma minimum distance must be less than its search radius")
    for key in ["peak_ratio_threshold", "area_ratio_threshold"]:
        _number(secondary[key], "secondary_soma." + key, 0, 2)
    _number(secondary["score_threshold"], "secondary_soma.score_threshold", 0, 4)
    _number(a["upsample_factor"], "upsample_factor", 1, 100, integer=True)
    _number(a["max_shift_pixels"], "max_shift_pixels", 0.1, 2048)
    if not isinstance(a["robust_preprocess"], bool):
        raise ValueError("robust_preprocess must be boolean")
    if a["mask_percentile"] is not None:
        _number(a["mask_percentile"], "mask_percentile", 0, 100)
        if a["mask_percentile"] == 100 or a["robust_preprocess"]:
            raise ValueError("Masked registration requires percentile<100 and robust_preprocess=false")
    count = 0
    for key, maximum in [("segmentation_min_area", 4096), ("tracking_search_radius", 256)]:
        grid = cfg["sensitivity"][key]
        if not isinstance(grid, list) or not 1 <= len(grid) <= 9:
            raise ValueError("Each declared sensitivity grid requires1..9 values")
        for item in grid:
            _number(item, key, 1, maximum, integer=True)
        if len(set(grid)) != len(grid) or sorted(grid) != grid:
            raise ValueError("Sensitivity grids must be distinct and sorted")
        count += len(grid)
    if count > 9:
        raise ValueError("At most9 total one-parameter sensitivity settings are allowed")
    for channel, values in cfg["luts"].items():
        lut = LUT(**values)
        if channel != "IC_field" and (lut.low < 0 or lut.high > 65535):
            raise ValueError("Raw display limits must be within the stored16-bit range")
    box = cfg["lut_box"]
    _number(box["padding"], "lut_box.padding", 0, 32, integer=True)
    _number(box["min_area"], "lut_box.min_area", 1, 16384, integer=True)
    if box["range_policy"] not in {"visible", "within_range"}:
        raise ValueError("Unknown LUT box range policy")
    return cfg


def _code_hashes():
    root = Path(__file__).resolve().parents[3]
    names = ["src/tmem_align/audit_v1/pipeline_diagnostics.py",
        "src/tmem_align/audit_v1/stage_trace.py", "src/tmem_align/audit_v1/visualization.py",
        "src/tmem_align/audit_v1/display.py", "src/tmem_align/preprocess.py",
        "src/tmem_align/register.py", "scripts/render_curated_neuron_phenotypes.py",
        "scripts/make_soma_anchored_bbox_movies_v2.py"]
    return {name: file_record(root / name)["sha256"] for name in names}


def _metadata(mode, cfg, supplied):
    return dict(title="TMEM106B " + mode + " processing diagnostics", mode=mode,
        channels=["405", "561", "488"], source_snapshot_base_commit=SOURCE_BASE,
        source_file_sha256=_code_hashes(), parameters=cfg,
        supplied_input_provenance=_safe(supplied or {}),
        measurement_release_authorized=False, all_proposals_unadopted=True,
        scientific_inference_ready=False)


class _InputLinkedTrace:
    """Connect production-observed function inputs to their actual caller inputs."""
    def __init__(self, trace, inputs):
        self.trace, self.inputs = trace, inputs

    def capture(self, name, array=None, **kwargs):
        explicit = tuple(kwargs.get("parents", ()))
        extra = tuple(self.inputs.get(name, ()))
        kwargs["parents"] = tuple(dict.fromkeys((*explicit, *extra)))
        return self.trace.capture(name, array, **kwargs)


def _segmentation_trace_inputs(trace, prefix):
    return _InputLinkedTrace(trace, {f"{prefix}_visit_{i:02d}_raw_488":
        (f"visit_{i:02d}_registered_488",) for i in range(9)})


def _production():
    from .reference import renderer
    r = renderer()
    return r, importlib.import_module("make_soma_anchored_bbox_movies_v2")


def _boolean(value, name):
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, str) and value.strip().lower() in {"true", "false"}:
        return value.strip().lower() == "true"
    if isinstance(value, (int, np.integer)) and value in (0, 1):
        return bool(value)
    raise ValueError("Require explicit true/false for " + name)


def _track_inputs(stack, master, neuron_id, renderer):
    import pandas as pd
    a = np.asarray(stack)
    if (a.ndim != 4 or a.shape[:2] != (9, 3) or min(a.shape[-2:]) < 128
            or a.dtype.kind not in "buif" or not np.isfinite(a).all()):
        raise ValueError("Require nine finite TCYX visits, C0=405/C1=561/C2=488, spatial dimensions>=128")
    required = {"neuron_id", "well", "day", "time_index", "anchor_y", "anchor_x", "tracking_valid"}
    if not isinstance(master, pd.DataFrame) or not required.issubset(master.columns):
        raise ValueError("Master requires explicit IDs, visits, anchors and tracking_valid")
    track = master[master.neuron_id == neuron_id].copy(deep=True).sort_values("time_index")
    if (len(track) != 9 or track.day.tolist() != DAYS or track.time_index.tolist() != list(range(9))
            or track.well.nunique() != 1 or str(track.iloc[0].well) != neuron_id.split("_")[0]):
        raise ValueError("Track must contain exactly the nine expected visits and unique time indices0..8")
    boxes, geometry = [], []
    for idx, row in track.iterrows():
        ay, ax = float(row.anchor_y), float(row.anchor_x)
        if not np.isfinite([ay, ax]).all() or not (0 <= ay < a.shape[-2] and 0 <= ax < a.shape[-1]):
            raise ValueError("Stored anchor is outside the registered frame")
        bounds = Bounds(*renderer.square_bounds(ay, ax, 128, *a.shape[-2:]))
        original = {}
        for key, v in zip(["bbox_y0", "bbox_y1", "bbox_x0", "bbox_x1"], vars(bounds).values()):
            if key in track.columns and not pd.isna(row[key]):
                _number(row[key], key, 0, max(a.shape[-2:]))
                if float(row[key]) != int(row[key]) or int(row[key]) != v:
                    raise ValueError("Stored bounding box differs from the existing128-pixel frozen-anchor crop: " + key)
                original[key] = int(row[key])
            track.loc[idx, key] = v
        track.loc[idx, "tracking_valid"] = _boolean(row.tracking_valid, "tracking_valid")
        box = bounds.crop(a[int(row.time_index)])
        require_cyx(box)
        boxes.append(box)
        geometry.append(dict(day=int(row.day), time_index=int(row.time_index), bounds=vars(bounds),
            anchor_yx_registered_px=[ay, ax], anchor_yx_crop_px=[ay-bounds.y0, ax-bounds.x0],
            stored_bbox=original, coordinate_system="already registered common-overlap YX; no transform reapplied"))
    return a, track, np.stack(boxes), geometry


def _check_reconstruction_errors(seg_meta):
    # The historical production reconstruction catches segmentation exceptions.
    # Preserve recognized scientific rejections, but do not hide software faults
    # such as an incompatible dependency or a misspelled function behind a mask.
    for value in seg_meta["adaptive_method"]:
        if str(value).startswith("failed: ") and str(value)[8:] not in _KNOWN_SEGMENTATION_FAILURES:
            raise RuntimeError("Unexpected production segmentation error: " + str(value)[8:])


def _core(renderer, masks, valid, cfg, trace, prefix, mask_prefix=None):
    s = cfg["segmentation"]
    observer = trace
    if mask_prefix is not None:
        names = {record["stage"] for record in trace.records}
        links = {}
        for i in range(len(masks)):
            parent = f"{mask_prefix}_visit_{i:02d}_qc"
            if parent not in names:
                parent = f"{mask_prefix}_visit_{i:02d}_qc_failure"
            if parent not in names:
                raise RuntimeError("Missing source segmentation-QC record for identity consensus")
            links[f"{prefix}_input_{i:02d}"] = (parent,)
        observer = _InputLinkedTrace(trace, links)
    try:
        return renderer.build_tight_identity_core(masks, valid, s["consensus_fraction"],
            s["min_core_area"], s["max_core_area"], trace=observer, trace_prefix=prefix), None
    except RuntimeError as error:
        if isinstance(error, renderer.CuratedTraceError) or not str(error).startswith(("Need >=3 valid 488 masks", "Tight identity-core area")):
            raise
        return None, str(error)


def _nearest(master, nid, well, time_index, anchor):
    candidates = master[(master.well == well) & (master.time_index == time_index) & (master.neuron_id != nid)]
    records = []
    for _, row in candidates.iterrows():
        point = np.asarray([row.anchor_y, row.anchor_x], dtype=float)
        if np.isfinite(point).all():
            records.append((float(np.linalg.norm(point - anchor)), str(row.neuron_id)))
    if not records:
        return dict(neuron_id=None, distance_px=None)
    distance, other = min(records)
    return dict(neuron_id=other, distance_px=distance,
                meaning="proximity to another stored anchor only; not proof of identity or switching")


def _tracking(stack, master, track, neuron_id, tracker, cfg, trace):
    t = cfg["tracking"]
    first = track.iloc[0]
    template = tracker.make_template(stack[0, 2], float(first.anchor_y), float(first.anchor_x),
        t["template_size"], trace=trace, trace_prefix="tracking_day8_template")
    radii = sorted(set([t["search_radius"], *cfg["sensitivity"]["tracking_search_radius"]]))
    results = {}
    for radius in radii:
        rows, previous_valid = [], 0
        for i, (_, row) in enumerate(track.iterrows()):
            reference = track.iloc[previous_valid]
            cy, cx, score = tracker.track_anchor(stack[i, 2], template,
                float(reference.anchor_y), float(reference.anchor_x), radius,
                trace=trace, trace_prefix=f"tracking_r{radius:03d}_visit_{i:02d}")
            frozen = np.asarray([row.anchor_y, row.anchor_x], dtype=float)
            candidate = np.asarray([cy, cx])
            rows.append(dict(day=int(row.day), time_index=i, search_radius_px=radius,
                fixed_day8_template=True, reference_frozen_visit_day=int(reference.day),
                reference_frozen_anchor_yx_px=[float(reference.anchor_y), float(reference.anchor_x)],
                stored_anchor_yx_px=frozen.tolist(), candidate_anchor_yx_px=candidate.tolist(),
                displacement_from_stored_anchor_px=float(np.linalg.norm(candidate - frozen)),
                diagnostic_match_score=score, diagnostic_min_score=t["min_score"],
                diagnostic_score_pass=bool(np.isfinite(score) and score >= t["min_score"]),
                historical_template_match_score=row.get("template_match_score", None),
                historical_tracking_valid=bool(row.tracking_valid),
                nearest_other_stored_anchor=_nearest(master, neuron_id, str(row.well), i, candidate),
                adopted=False, stored_anchor_overwritten=False,
                interpretation="Recomputed proposal only; the diagnostic template/search settings do not reproduce or approve historical tracking."))
            # Reference positions remain the original master, even when a newly
            # proposed peak is stronger. This never constructs a rescued track.
            if bool(row.tracking_valid):
                previous_valid = i
        results[str(radius)] = rows
    return dict(primary_search_radius_px=t["search_radius"], diagnostic_template_size_px=t["template_size"],
        declared_search_radius_grid=cfg["sensitivity"]["tracking_search_radius"],
        all_proposals_unadopted=True, results_by_radius=results)


def _segmentation_sensitivity(renderer, boxes, track, masks, valid, cfg, trace):
    base = cfg["segmentation"]["min_area"]
    result = []
    for minimum in cfg["sensitivity"]["segmentation_min_area"]:
        prefix = f"sensitivity_area_{minimum:04d}"
        if minimum == base:
            m, v = masks, valid
            reused = True
        else:
            m, v, meta = renderer.reconstruct_masks(boxes, track, 2, 128, minimum,
                trace=_segmentation_trace_inputs(trace, prefix), trace_prefix=prefix)
            _check_reconstruction_errors(meta)
            reused = False
        core, rejection = _core(renderer, m, v, cfg, trace, prefix + "_core",
                                "primary_segmentation" if reused else prefix)
        visits = []
        for i in range(9):
            union = int(np.count_nonzero(m[i] | masks[i]))
            intersection = int(np.count_nonzero(m[i] & masks[i]))
            visits.append(dict(day=DAYS[i], mask_area_px=int(m[i].sum()),
                baseline_mask_area_px=int(masks[i].sum()), valid_488_mask=bool(v[i]),
                mask_IoU_vs_primary=intersection / union if union else None,
                both_supports_empty=bool(union == 0)))
        result.append(dict(segmentation_min_area_px=minimum, primary_execution_reused=reused,
            valid_visit_count=int(v.sum()), core_constructed=core is not None,
            core_area_px=int(core[0].sum()) if core is not None else None,
            core_rejection=rejection, visits=visits, adopted=False,
            phenotype_used_to_select_setting=False))
    return dict(primary_segmentation_min_area_px=base,
        declared_grid=cfg["sensitivity"]["segmentation_min_area"], settings=result,
        all_settings_unadopted=True, no_best_setting_selected=True)


def trace_registered_track(stack, master, neuron_id, out, *, config=None, metadata=None):
    """Trace fixed crops, production masks/core/phenotype and unadopted sensitivity.

    ``master`` is the complete pandas atlas table, so nearby-ID distances can be
    checked without treating labels as biological ground truth. No input is
    written, no review is changed, and no accepted-metrics CSV is produced.
    """
    from scipy.ndimage import binary_fill_holes
    from skimage import morphology
    cfg = load_config(config)
    renderer, tracker = _production()
    a, track, boxes, geometry = _track_inputs(stack, master, neuron_id, renderer)
    source_sha = array_sha256(a)
    original_master = master.to_csv(index=False)
    meta = _metadata("registered-track", cfg, metadata)
    meta.update(neuron_id=neuron_id, expected_days=DAYS, input_axes="TCYX",
        input_shape=list(a.shape), input_dtype=str(a.dtype), source_array_sha256=source_sha,
        coordinate_system="registered common-overlap pixels; anchors are already transformed")
    trace = StageTrace(out, metadata=meta, luts=cfg["luts"])
    for name, parent, why in [
        ("historical_raw_input", (), "Historical raw detector pixels are not supplied by a registered stack."),
        ("historical_ic_before_after", ("historical_raw_input",), "The original IC field and exact historical pre/post-correction arrays are unavailable; no reconstruction is asserted."),
        ("historical_stitching", ("historical_ic_before_after",), "The original tile placement and stitching intermediates are not supplied."),
        ("historical_registration", ("historical_stitching",), "Registration was already applied upstream; its historical before image/transform is not re-created or applied twice.")]:
        trace.capture(name, status="unavailable", parents=parent, why=why,
            details={"historical_validation_granted": False})
    _write(trace.root / "crop_geometry.json", geometry)
    proposals = []
    for i in range(9):
        prefix = f"visit_{i:02d}"
        for ci, label in [(2, "488"), (1, "561"), (0, "405")]:
            trace.capture(prefix + "_registered_" + label, boxes[i, ci], channel=label,
                parents=("historical_registration",), why="Preserve the actual unchanged128-pixel crop in the registered coordinate frame.",
                details=geometry[i])
        proposals.append(dict(day=DAYS[i], **propose_lut_bbox(boxes[i, 2], LUT(**cfg["luts"]["488"]),
            anchor_yx=geometry[i]["anchor_yx_crop_px"], channel="488", **cfg["lut_box"])))
    _write(trace.root / "display_only_lut_bbox_proposals.json", proposals)
    masks, valid, seg_meta = renderer.reconstruct_masks(boxes, track, 2, 128,
        cfg["segmentation"]["min_area"], trace=_segmentation_trace_inputs(trace, "primary_segmentation"),
        trace_prefix="primary_segmentation")
    _check_reconstruction_errors(seg_meta)
    core_result, core_rejection = _core(renderer, masks, valid, cfg, trace,
                                       "primary_identity", "primary_segmentation")
    diagnostic_metrics = []
    screen = None
    if core_result is not None:
        core, required, nvalid, method = core_result
        reference488 = renderer.build_reference_488(boxes, 2, valid)
        trace.capture("secondary_soma_reference_488", reference488,
            parents=tuple(f"visit_{i:02d}_registered_488" for i in range(9) if valid[i]),
            why="Build the production longitudinal median of normalized488 crops from the actual QC-valid visits.",
            details={"array_role": "normalized_intensity", "valid_visit_indices": np.flatnonzero(valid).tolist(),
                     "reference_is_not_a_physical_illumination_correction": True})
        observed_screen = _InputLinkedTrace(trace, {
            "secondary_soma_screen_reference": ("secondary_soma_reference_488",),
            "secondary_soma_screen_reference_488": ("secondary_soma_reference_488",)})
        screen = renderer.screen_secondary_soma(reference488, **cfg["secondary_soma"],
            trace=observed_screen, trace_prefix="secondary_soma_screen")
        _write(trace.root / "secondary_soma_screen.json", dict(status="executed", **vars(screen),
            automated_flag_only=True, identity_or_ROI_ownership_approval_granted=False,
            parameters=cfg["secondary_soma"]))
        dilated = morphology.dilation(core, morphology.disk(cfg["segmentation"]["phenotype_dilation"]))
        trace.capture("phenotype_roi_dilated", dilated.astype(bool), parents=("primary_identity_core",),
            why="Apply the declared unchanged488-core dilation; display LUTs and561 do not define this support.",
            parameters={"dilation_disk_radius_px": cfg["segmentation"]["phenotype_dilation"]})
        roi = binary_fill_holes(dilated).astype(bool)
        trace.capture("phenotype_roi_holes_filled", roi, parents=("phenotype_roi_dilated",),
            why="Fill enclosed holes to obtain the fixed diagnostic phenotype ROI.",
            details={"roi_area_px": int(roi.sum()), "accepted_export_allowed": False})
        from PIL import Image
        overlay_folder = trace.root / "display_only_overlays"
        overlay_folder.mkdir()
        for i in range(9):
            preview = render_preview(boxes[i, 2], LUT(**cfg["luts"]["488"]), overlays=[
                {"mask": core, "color": (255, 255, 0)},
                {"mask": roi, "color": (255, 80, 80)}])
            Image.fromarray(preview).save(overlay_folder / f"day_{DAYS[i]:02d}_488_core_roi.png")
        for i in range(9):
            phenotype_prefix = f"primary_phenotype_visit_{i:02d}"
            observed = _InputLinkedTrace(trace, {
                phenotype_prefix + "_raw_561": (f"visit_{i:02d}_registered_561",),
                phenotype_prefix + "_fixed_roi": ("phenotype_roi_holes_filled",)})
            metrics, puncta, diffuse, corrected = renderer.quantify_phenotype(boxes[i, 1], roi,
                cfg["segmentation"]["background_exclusion"], cfg["segmentation"]["puncta_min_size"],
                trace=observed, trace_prefix=phenotype_prefix)
            if np.any(puncta & diffuse) or not np.array_equal(puncta | diffuse, roi):
                raise AssertionError("Production phenotype partition does not cover the fixed ROI exactly")
            if not np.isclose(metrics["total_mcherry_intensity"],
                    metrics["punctate_mcherry_integrated_intensity"] + metrics["diffuse_mcherry_integrated_intensity"], rtol=1e-12):
                raise AssertionError("Production phenotype intensity partition failed")
            diagnostic_metrics.append(dict(day=DAYS[i], adaptive_valid_recomputed=bool(valid[i]),
                diagnostic_only=True, review_approved=False, **metrics))
    else:
        trace.capture("secondary_soma_screen_skipped", status="skipped", parents=("primary_identity_failure",),
            why="The failed primary488 identity core prevents this diagnostic from supplying a secondary-soma screening result.",
            details={"core_rejection": core_rejection, "screen_score_invented": False})
        _write(trace.root / "secondary_soma_screen.json", dict(status="skipped", reason=core_rejection,
            automated_flag_only=True, screen_score_invented=False))
        trace.capture("phenotype_blocked", status="skipped", parents=("primary_identity_failure",),
            why="An invalid488 consensus core cannot supply phenotype geometry; no phenotype calculations or export are attempted.",
            details={"core_rejection": core_rejection})
    _write(trace.root / "diagnostic_phenotype_metrics.json", diagnostic_metrics)
    tracking = _tracking(a, master, track, neuron_id, tracker, cfg, trace)
    segmentation = _segmentation_sensitivity(renderer, boxes, track, masks, valid, cfg, trace)
    _write(trace.root / "tracking_comparison.json", tracking)
    _write(trace.root / "parameter_sensitivity.json", segmentation)
    if array_sha256(a) != source_sha or master.to_csv(index=False) != original_master:
        raise AssertionError("Diagnostic execution modified its source stack or master table")
    if _code_hashes() != meta["source_file_sha256"]:
        raise RuntimeError("Production source files changed during the diagnostic execution")
    rejected = core_result is None or not bool(np.all(valid)) or (screen is not None and not screen.single_soma_pass)
    summary = dict(diagnostic_status="diagnostic_rejected" if rejected else "diagnostic_complete_pending_review",
        software_execution_complete=True, neuron_id=neuron_id, reviewed_or_accepted=False,
        original_anchors_and_master_unchanged=True, registration_reapplied=False,
        valid_488_visit_count=int(valid.sum()), valid_488_by_day=dict(zip(map(str, DAYS), map(bool, valid))),
        core_constructed=core_result is not None, core_rejection=core_rejection,
        core_area_px=int(core_result[0].sum()) if core_result is not None else None,
        secondary_soma_screen_performed=screen is not None,
        automated_secondary_soma_single_pass=bool(screen.single_soma_pass) if screen is not None else None,
        secondary_soma_screen_is_informational_only=True,
        secondary_soma_screen_does_not_establish_ROI_ownership=True,
        phenotype_calculations_are_diagnostic_only=True, accepted_metrics_csv_written=False,
        real_accepted_ids=[], historical_ic_and_stitching_validated=False,
        tracking_diagnostics_recomputed=True, tracking_proposals_adopted=False,
        LUT_box_proposals_adopted=False, parameter_changes_adopted=False,
        what="Expose the executed488 segmentation/core/ROI and561 phenotype calculations, plus independent tracking/parameter diagnostics.",
        why="Locate the exact stage of wrong-object, boundary-ownership or unstable-mask failures before claiming an improvement.",
        finding="Core construction, all-nine adaptiveQC or the automated secondary-soma screen rejected this diagnostic geometry; inspect the bound stage records." if rejected else
            "The declared production calculations executed; identity, ROI ownership and scientific validity remain unapproved.",
        required_next_evidence="Compare these source-bound outputs with the independently reviewed identity/boundary findings; never equate a stronger match or smaller ROI with acceptance.")
    return _finish(trace, summary)


def trace_raw_pair(reference, moving, out, *, flatfield=None, flatfield_coordinate_system=None,
                   darkfield=None, background_radius=None, config=None, metadata=None):
    """Execute supplied rawCYX correction then488 registration; preserve all stages."""
    from tmem_align.preprocess import preprocess_image
    from tmem_align.register import register_translation
    from tmem_align.registration_qc import correlation, overlap_fraction
    cfg = load_config(config)
    ref, mov = require_cyx(reference), require_cyx(moving)
    if ref.shape != mov.shape:
        raise ValueError("Raw-pair CYX shapes differ")
    if np.std(ref[2]) == 0 or np.std(mov[2]) == 0:
        raise ValueError("Raw-pair registration requires nonconstant488 morphology;561 cannot rescue identity alignment")
    if flatfield is not None and flatfield_coordinate_system != "detector":
        raise ValueError("A supplied flatfield must be explicitly declared in matching detector coordinates")
    if flatfield is not None:
        field = np.asarray(flatfield)
        if (field.shape not in {ref.shape, ref.shape[-2:]} or field.dtype.kind not in "buif"
                or not np.isfinite(field).all() or np.any(field <= 0)):
            raise ValueError("Flatfield requires a finite positive matchingYX/CYX detector-coordinate divisor")
    if darkfield is not None:
        _number(darkfield, "darkfield", 0, 65535)
    if background_radius is not None:
        _number(background_radius, "background_radius", 1, 512, integer=True)
    source_sha = [array_sha256(ref), array_sha256(mov)]
    meta = _metadata("raw-pair", cfg, metadata)
    meta.update(input_axes="CYX", input_shape=list(ref.shape), input_dtype=[str(ref.dtype), str(mov.dtype)],
        source_array_sha256=source_sha, coordinate_system="supplied matching detector pixel coordinates",
        flatfield_coordinate_system=flatfield_coordinate_system if flatfield is not None else None,
        flatfield_array_sha256=array_sha256(flatfield) if flatfield is not None else None,
        flatfield_physical_calibration_independently_verified=False)
    trace = StageTrace(out, metadata=meta, luts=cfg["luts"])
    ref_out = preprocess_image(ref, ic_field=flatfield, darkfield=darkfield,
        background_radius=background_radius, trace=trace, trace_prefix="reference_preprocess")
    mov_out = preprocess_image(mov, ic_field=flatfield, darkfield=darkfield,
        background_radius=background_radius, trace=trace, trace_prefix="moving_preprocess")
    trace.capture("preprocessed_reference_cyx", ref_out, axes="CYX", channel="488",
        why="Preserve all channels handed to the488-derived registration estimate.")
    trace.capture("preprocessed_moving_cyx", mov_out, axes="CYX", channel="488",
        why="Preserve all moving channels before applying the one shared spatial transform.")
    registered, shift, error = register_translation(ref_out, mov_out,
        upsample_factor=cfg["registration"]["upsample_factor"],
        max_shift_pixels=cfg["registration"]["max_shift_pixels"],
        robust_preprocess=cfg["registration"]["robust_preprocess"],
        mask_percentile=cfg["registration"]["mask_percentile"],
        channel_index=2, trace=trace, trace_prefix="alignment")
    trace.capture("registered_moving_cyx", registered, axes="CYX", channel="488",
        parents=("preprocessed_reference_cyx", "preprocessed_moving_cyx"),
        why="Apply the shift estimated from488 exactly once to each original moving channel.",
        details={"shift_dy_dx_px": list(shift), "channel_coupling": False,
                 "transform_convention": "moving-to-reference; positive dy/dx shifts down/right"})
    overlap = strict_overlap(ref.shape[-2:], [(0, 0), shift])
    before_corr = correlation(overlap.crop(ref_out[2]), overlap.crop(mov_out[2]))
    after_corr = correlation(overlap.crop(ref_out[2]), overlap.crop(registered[2]))
    trace.capture("registered_overlap_488", overlap.crop(registered[2]), channel="488",
        parents=("registered_moving_cyx",), why="Compare registration over geometric shared support instead of its zero-filled outside border.",
        details={"overlap_bounds": vars(overlap), "interpolation_edge_quality_independently_verified": False})
    overlap_reference = overlap.crop(ref_out[2]).astype(np.float64)
    difference_before = np.abs(overlap_reference - overlap.crop(mov_out[2]).astype(np.float64))
    difference_after = np.abs(overlap_reference - overlap.crop(registered[2]).astype(np.float64))
    trace.capture("alignment_absolute_difference_before", difference_before, channel="488",
        parents=("preprocessed_reference_cyx", "preprocessed_moving_cyx"),
        why="Measure the unaligned488 pixel disagreement on the same overlap used for the after comparison.",
        details={"overlap_bounds": vars(overlap), "units": "stored intensity units", "identity_validated": False})
    trace.capture("alignment_absolute_difference_after", difference_after, channel="488",
        parents=("preprocessed_reference_cyx", "registered_moving_cyx"),
        why="Expose residual488 disagreement after the recorded transform; intensity changes can also affect this statistic.",
        details={"overlap_bounds": vars(overlap), "units": "stored intensity units", "identity_validated": False})
    if source_sha != [array_sha256(ref), array_sha256(mov)]:
        raise AssertionError("Raw-pair diagnostics modified its input arrays")
    if _code_hashes() != meta["source_file_sha256"]:
        raise RuntimeError("Production source files changed during the diagnostic execution")
    summary = dict(diagnostic_status="diagnostic_complete_pending_review", software_execution_complete=True,
        correction_order=["supplied_darkfield", "supplied_flatfield_in_detector_coordinates", "optional_rolling_ball_background", "single_uint16_quantization", "488_estimate_then_shared_CYX_translation"],
        flatfield_applied=flatfield is not None, darkfield_applied=darkfield is not None,
        background_radius_px=background_radius, input_arrays_unchanged=True,
        shift_dy_dx_px=list(shift), registration_error=error,
        common_overlap_fraction=overlap_fraction(ref.shape[-2:], shift),
        common_overlap_bounds=vars(overlap), correlation_488_before=before_corr,
        correlation_488_after=after_corr,
        mean_absolute_difference_488_before=float(difference_before.mean()),
        mean_absolute_difference_488_after=float(difference_after.mean()),
        accepted_metrics_csv_written=False, real_accepted_ids=[],
        historical_pipeline_reproduced=False, scientific_validation_granted=False,
        what="Capture actual supplied-pair IC/background processing and488-derived multichannel alignment.",
        why="Test detector-coordinate correction and transform direction with reproducible numeric intermediates.",
        finding="The supplied pair executed. Correlation change describes this pair only; it cannot establish soma identity or validate a historical correction field.")
    return _finish(trace, summary)
