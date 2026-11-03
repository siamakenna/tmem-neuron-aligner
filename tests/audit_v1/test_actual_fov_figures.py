"""Constructed software fixtures only: no real images, labels or approvals."""

import copy
import csv
import json
import shutil
import stat
import subprocess
import sys
import xml.etree.ElementTree as ET
from functools import partial
from pathlib import Path

import numpy as np
import pytest
import tifffile
from PIL import Image

from tmem_align.audit_v1 import actual_fov_figures as figures
from tmem_align.audit_v1.display import LUT
from tmem_align.audit_v1.pipeline_diagnostics import DEFAULT_CONFIG
from tmem_align.audit_v1.stage_trace import StageTrace


def write_json(path, value):
    path.write_text(json.dumps(value, allow_nan=False))


@pytest.fixture(scope="module")
def bound_case(tmp_path_factory):
    """Small complete saved execution and explicit live TCYX source binding."""
    tmp_path = tmp_path_factory.mktemp("saved_software_fixture")
    nid = "E05_N001"
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    stack = np.full((9, 3, 256, 256), 100, dtype=np.uint16)
    stack[:, 2, 100:156, 100:156] = 3000
    stack_path = dataset / "well.ome.tif"
    tifffile.imwrite(stack_path, stack, photometric="minisblack", metadata={"axes": "TCYX"})
    master = [
        {
            "neuron_id": nid,
            "well": "E05",
            "day": d,
            "time_index": i,
            "anchor_y": 128,
            "anchor_x": 128,
            "bbox_y0": 64,
            "bbox_y1": 192,
            "bbox_x0": 64,
            "bbox_x1": 192,
        }
        for i, d in enumerate(figures.DAYS)
    ]
    master_path = dataset / "master.csv"
    with master_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(master[0]))
        writer.writeheader()
        writer.writerows(master)
    declaration = {
        "channels": ["405", "561", "488"],
        "days": list(figures.DAYS),
        "master": {"path": "master.csv", "sha256": figures.sha(master_path)},
        "stacks": {"E05": {"path": "well.ome.tif", "sha256": figures.sha(stack_path)}},
    }
    write_json(dataset / "dataset_manifest.json", declaration)
    root = tmp_path / "traces" / nid
    metadata = {
        "mode": "registered-track",
        "neuron_id": nid,
        "expected_days": list(figures.DAYS),
        "input_axes": "TCYX",
        "input_shape": list(stack.shape),
        "input_dtype": "uint16",
        "coordinate_system": "registered common-overlap YX pixels",
        "parameters": copy.deepcopy(DEFAULT_CONFIG),
        "source_file_sha256": {},
        "evidence_type": "SOFTWARE_FIXTURE_ONLY",
    }
    trace = StageTrace(root, metadata=metadata, luts=DEFAULT_CONFIG["luts"])
    trace.capture = partial(trace.capture, why="Constructed SOFTWARE_FIXTURE_ONLY stage purpose")
    mask = np.zeros((128, 128), dtype=bool)
    mask[52:76, 52:76] = True
    geometry, settings, radii = [], [], {str(r): [] for r in (40, 60, 80)}
    for i, day in enumerate(figures.DAYS):
        raw = stack[i, 2, 64:192, 64:192]
        trace.capture(
            f"visit_{i:02d}_registered_488",
            raw,
            why="SOFTWARE_FIXTURE_ONLY raw crop <script> & control",
        )
        prefix = f"primary_segmentation_visit_{i:02d}"
        trace.capture(prefix + "_crop", raw)
        for suffix in ("normalized", "smoothed"):
            trace.capture(
                prefix + "_" + suffix,
                raw.astype(float) / 4095,
                details={"array_role": "normalized_intensity"},
            )
        for suffix in ("segmentation_seed", "allowed_region"):
            trace.capture(prefix + "_" + suffix, mask)
        candidate = prefix + "_candidate_07"
        for suffix in ("threshold", "small_objects_removed", "closed", "holes_filled"):
            trace.capture(candidate + "_" + suffix, mask)
        trace.capture(
            candidate + "_components",
            mask.astype(np.uint8),
            details={"array_role": "component_labels"},
        )
        trace.capture(candidate + "_selection", mask)
        trace.capture(prefix + "_selected_component", mask, parents=(candidate + "_selection",))
        for area in (140, 180, 220):
            p = "primary_segmentation" if area == 180 else f"sensitivity_area_{area:04d}"
            trace.capture(f"{p}_visit_{i:02d}_mask", mask)
        trace.capture(
            prefix + "_qc",
            mask,
            details={"valid_488_mask": i != 0, "tracking_valid_inherited": True},
        )
        geometry.append(
            {
                "day": day,
                "time_index": i,
                "bounds": {"y0": 64, "y1": 192, "x0": 64, "x1": 192},
                "anchor_yx_registered_px": [128, 128],
                "anchor_yx_crop_px": [64, 64],
            }
        )
        for radius in (40, 60, 80):
            p = f"tracking_r{radius:03d}_visit_{i:02d}"
            side = 2 * radius + 41
            origin = 128 - radius - 20
            search = stack[i, 2, origin : origin + side, origin : origin + side]
            surface = np.zeros((2 * radius + 1, 2 * radius + 1), dtype=np.float32)
            surface[radius, radius] = 0.8
            trace.capture(p + "_template", stack[0, 2, 108:149, 108:149])
            trace.capture(
                p + "_raw_search",
                search,
                details={"bounds_y0_y1_x0_x1": [origin, origin + side, origin, origin + side]},
            )
            trace.capture(
                p + "_normalized_search",
                search.astype(float) / 4095,
                details={"array_role": "normalized_intensity"},
            )
            trace.capture(p + "_correlation", surface, details={"array_role": "correlation"})
            detail = {
                "correlation_peak_yx": [radius, radius],
                "candidate_anchor_yx_px": [128, 128],
                "search_origin_yx_px": [origin, origin],
                "template_shape_yx": [41, 41],
            }
            trace.capture(p + "_chosen_peak", surface, details=detail)
            radii[str(radius)].append(
                {
                    "day": day,
                    "diagnostic_match_score": float(surface[radius, radius]),
                    "diagnostic_score_pass": True,
                    "historical_tracking_valid": True,
                    "reference_frozen_visit_day": 8,
                    "candidate_anchor_yx_px": [128, 128],
                    "stored_anchor_yx_px": [128, 128],
                    "displacement_from_stored_anchor_px": 0.0,
                    "nearest_other_stored_anchor": None,
                }
            )
    for name in (
        "primary_identity_vote_count",
        "primary_identity_consensus",
        "primary_identity_core",
        "phenotype_roi_holes_filled",
    ):
        trace.capture(name, mask)
    for area in (140, 180, 220):
        settings.append(
            {
                "segmentation_min_area_px": area,
                "core_constructed": True,
                "core_area_px": int(mask.sum()),
                "core_rejection": None,
                "visits": [
                    {
                        "day": d,
                        "mask_area_px": int(mask.sum()),
                        "mask_IoU_vs_primary": 1.0,
                        "valid_488_mask": (i != 1 if area == 140 else i != 0),
                    }
                    for i, d in enumerate(figures.DAYS)
                ],
            }
        )
    write_json(root / "crop_geometry.json", geometry)
    write_json(root / "parameter_sensitivity.json", {"settings": settings})
    write_json(
        root / "tracking_comparison.json",
        {"results_by_radius": radii, "diagnostic_template_size_px": 41},
    )
    write_json(
        root / "summary.json",
        {
            "diagnostic_status": "diagnostic_rejected",
            "valid_488_visit_count": 8,
            "valid_488_by_day": {str(d): i != 0 for i, d in enumerate(figures.DAYS)},
        },
    )
    trace.finish({"SOFTWARE_FIXTURE_ONLY": True})
    return {
        "root": root,
        "dataset": dataset,
        "declaration": declaration,
        "master": master,
        "stack": stack,
        "stack_path": stack_path,
        "nid": nid,
        "mask": mask,
        "parent": tmp_path,
    }


@pytest.fixture
def mutable_case(bound_case, tmp_path):
    """Fresh private copy only for tests that deliberately corrupt source bytes."""
    destination = tmp_path / "mutable_fixture"
    shutil.copytree(bound_case["parent"], destination)
    result = dict(bound_case)
    result.update(
        parent=destination,
        dataset=destination / "dataset",
        stack_path=destination / "dataset/well.ome.tif",
        root=destination / "traces" / bound_case["nid"],
    )
    return result


def test_trace_and_live_fov_coordinate_binding(bound_case):
    c = bound_case
    case = figures.TraceCase(c["root"])
    stack, records = figures.bind_fov(case, c["dataset"], c["declaration"], c["master"])
    assert stack.shape == (9, 3, 256, 256)
    assert len(records) == 9 and all(r["live_crop_exactly_equal"] for r in records)
    assert all(not r["whole_stack_rehashed_here"] for r in records)
    assert records[0]["anchor_yx_crop_px"] == [64, 64]
    case.finish()


@pytest.mark.parametrize("kind", ["anchor", "bbox", "day", "well", "pixels", "axes", "dtype"])
def test_live_source_mismatch_rejected(mutable_case, kind):
    c = mutable_case
    case = figures.TraceCase(c["root"])
    master = copy.deepcopy(c["master"])
    if kind == "anchor":
        master[0]["anchor_x"] = 129
    elif kind == "bbox":
        master[0]["bbox_x0"] = 65
    elif kind == "day":
        master[0]["day"] = 39
    elif kind == "well":
        master[0]["well"] = "F05"
    else:
        a = c["stack"].copy()
        axes = "TCYX"
        if kind == "pixels":
            a[0, 2, 128, 128] += 1
        elif kind == "axes":
            axes = "ZCYX"
        else:
            a = a.astype(np.float32)
        tifffile.imwrite(c["stack_path"], a, photometric="minisblack", metadata={"axes": axes})
    with pytest.raises((ValueError, KeyError)):
        figures.bind_fov(case, c["dataset"], c["declaration"], master)


@pytest.mark.parametrize("artifact", ["array.npy", "preview.png"])
def test_stale_trace_artifact_fails_before_rendering(mutable_case, artifact):
    path = mutable_case["root"] / "stages/visit_00_registered_488" / artifact
    path.write_bytes(path.read_bytes() + b"ALTERED_SOFTWARE_CONTROL")
    with pytest.raises(ValueError, match="changed"):
        figures.TraceCase(mutable_case["root"])


def test_source_mutation_after_read_is_rejected(mutable_case):
    case = figures.TraceCase(mutable_case["root"])
    case.array("visit_00_registered_488")
    path = mutable_case["root"] / "stages/visit_00_registered_488/array.npy"
    path.write_bytes(path.read_bytes() + b"changed")
    with pytest.raises(ValueError, match="changed"):
        case.finish()


def test_actual_winning_candidate_parent_not_first_threshold():
    stages = {
        "p_selected_component": {"status": "executed", "parents": ["p_candidate_07_selection"]},
        "p_candidate_00_selection": {},
        "p_candidate_07_selection": {},
    }
    assert figures.winning_candidate(stages, "p") == "p_candidate_07"
    assert figures.winning_candidate({}, "p") is None
    stages["p_selected_component"]["parents"] = ["p_candidate_99_selection"]
    with pytest.raises(ValueError, match="actual threshold parent"):
        figures.winning_candidate(stages, "p")


def test_two_sided_view_boundaries_are_exact_and_unadopted():
    image = np.array([[10, 11, 20, 21]], dtype=np.uint16)
    mask = np.ones_like(image, dtype=bool)
    before = image.copy()
    rows = figures.viewing_metrics(image, mask, mask, [0, 1], LUT(10, 20), padding=0, min_area=1)
    visible, within = rows
    assert visible["proposal"]["support_pixels"] == 3
    assert within["proposal"]["support_pixels"] == 2
    assert within["proposal"]["above_high_pixels_excluded_from_support"] == 1
    assert within["ROI_lost_pixels"] == 2
    assert within["interpretation"] == "degradation_frozen_support_lost"
    assert all(not r["adopted"] and not r["measurement_geometry_changed"] for r in rows)
    np.testing.assert_array_equal(image, before)


def test_view_failure_neutral_and_retained_support():
    image = np.full((5, 5), 15, dtype=np.uint16)
    mask = np.ones_like(image, dtype=bool)
    rows = figures.viewing_metrics(image, mask, mask, [2, 2], LUT(10, 20), padding=0, min_area=1)
    assert all(r["interpretation"] == "neutral_same_box" for r in rows)
    image[:] = 0
    image[1:4, 1:4] = 15
    mask = image > 0
    rows = figures.viewing_metrics(image, mask, mask, [2, 2], LUT(10, 20), padding=0, min_area=1)
    assert all(r["interpretation"] == "smaller_view_support_retained_not_accuracy" for r in rows)
    assert rows[0]["ROI_retained_fraction"] == 1
    rows = figures.viewing_metrics(image, mask, mask, [0, 0], LUT(10, 20), padding=0, min_area=1)
    assert all(r["interpretation"] == "failure_no_view" for r in rows)


def test_missing_frozen_support_does_not_claim_retention():
    rows = figures.viewing_metrics(np.ones((4, 4)), None, None, [2, 2], LUT(0, 2), min_area=1)
    assert all(
        r["core_retained_fraction"] is None and "unavailable" in r["interpretation"] for r in rows
    )
    with pytest.raises(ValueError, match="Boolean mask"):
        figures.viewing_metrics(np.ones((4, 4)), np.ones((4, 4)), None, [2, 2], LUT(0, 2))


def test_peak_ties_competitors_and_invalid_surface():
    a = np.zeros((25, 25))
    a[3, 3] = a[20, 20] = 0.9
    result = figures.peak_statistics(a)
    assert result["local_peak_count"] == 2
    assert result["top_tied_locations"] == 2
    assert result["peaks"][0]["y"] == 3
    assert result["ambiguity_not_accuracy"]
    with pytest.raises(ValueError, match="finite"):
        figures.peak_statistics(np.array([[np.nan]]))


def test_area_radius_grids_retain_gain_loss_and_actual_masks(bound_case):
    case = figures.TraceCase(bound_case["root"])
    segmentation, tracking = figures.sensitivity_rows(case)
    assert len(segmentation) == len(tracking) == 27
    assert {r["flag_change"] for r in segmentation} >= {
        "gained_diagnostic_flag_not_acceptance",
        "lost_diagnostic_flag",
        "neutral_flag",
    }
    assert all(r["mask_IoU_vs_primary"] == 1 for r in segmentation)
    assert all(r["interpretation"] == "unchanged_peak" for r in tracking)
    assert all(not r["adopted"] for r in segmentation + tracking)


@pytest.mark.parametrize(
    "kind", ["missing_area", "missing_radius", "duplicate_day", "area_count", "candidate", "score"]
)
def test_bad_grid_scalar_or_peak_binding_rejected(bound_case, kind):
    case = figures.TraceCase(bound_case["root"])
    if kind == "missing_area":
        case.segmentation["settings"].pop()
    elif kind == "missing_radius":
        case.tracking["results_by_radius"].pop("80")
    elif kind == "duplicate_day":
        case.segmentation["settings"][0]["visits"][0]["day"] = 12
    elif kind == "area_count":
        case.segmentation["settings"][0]["visits"][0]["mask_area_px"] = 1
    elif kind == "candidate":
        case.tracking["results_by_radius"]["40"][0]["candidate_anchor_yx_px"] = [130, 130]
    else:
        case.tracking["results_by_radius"]["40"][0]["diagnostic_match_score"] = float("nan")
    with pytest.raises(ValueError):
        figures.sensitivity_rows(case)


def test_failed_stage_cards_are_unavailable_not_fake_masks(bound_case):
    case = figures.TraceCase(bound_case["root"])
    card = case.card("missing_optional_stage")
    assert card["image"] is None and card["status"] == "unavailable"
    cards = figures.processing_cards(
        case,
        0,
        bound_case["stack"][0, 2],
        {
            "bounds": {"y0": 64, "y1": 192, "x0": 64, "x1": 192},
            "anchor_yx_registered_px": [128, 128],
        },
    )
    assert any("False" in c["caption"] for c in cards if c["stage"].endswith("_qc"))
    assert any(c["stage"].endswith("candidate_07_threshold") for c in cards)


def test_render_sheet_enlarges_cells_and_escapes_svg(tmp_path):
    rgb = np.zeros((8, 8, 3), dtype=np.uint8)
    rgb[:, :, 1] = 200
    result = figures.render_sheet(
        tmp_path,
        "fixture",
        "Title <&>",
        [
            {
                "title": "Cell <&>",
                "image": rgb,
                "caption": "SOFTWARE_FIXTURE_ONLY <script>",
                "status": "display_only",
                "provenance": {},
            }
        ],
    )
    png = np.asarray(Image.open(tmp_path / result["PNG"]))
    assert np.count_nonzero(np.all(png == [0, 200, 0], axis=-1)) > 70000
    text = (tmp_path / result["SVG"]).read_text()
    ET.fromstring(text)
    assert "&lt;script&gt;" in text and "data:image/png;base64," in text
    assert "1. Cell" in text


def test_run_outputs_are_source_bound_private_and_no_acceptance(bound_case):
    c = bound_case
    out = c["parent"] / "output"
    before = figures.sha(c["stack_path"])
    result = figures.run(
        c["root"].parent,
        c["dataset"],
        out,
        render_cases=[c["nid"]],
        days=[8],
        lut_low=200,
        lut_high=2000,
    )
    assert result["real_accepted_ids"] == [] and not result["scientific_inference_ready"]
    assert not result["measurement_geometry_changed"] and not result["accepted_export_written"]
    assert len(result["sheets"]) == 3
    assert stat.S_IMODE(out.stat().st_mode) == 0o700
    for name, expected in result["outputs_sha256"].items():
        assert figures.sha(out / name) == expected
        assert stat.S_IMODE((out / name).stat().st_mode) == 0o600
    assert figures.sha(c["stack_path"]) == before
    assert "SOFTWARE_FIXTURE_ONLY" in json.dumps(result)
    page = (out / "index.html").read_text()
    assert "<script" not in page and "http://" not in page and "https://" not in page
    assert len(list(csv.DictReader((out / "segmentation_sensitivity.csv").open()))) == 27
    with pytest.raises(ValueError):
        figures.run(c["root"].parent, c["dataset"], out, render_cases=[c["nid"]])


@pytest.mark.parametrize(
    "options",
    [
        {"render_cases": ["F05_N999"]},
        {"render_cases": ["E05_N001", "E05_N001"]},
        {"render_cases": ["E05_N001"], "days": [8, 8]},
        {"render_cases": ["E05_N001"], "lut_low": 10},
        {"render_cases": ["E05_N001"], "lut_low": 100, "lut_high": 10},
    ],
)
def test_run_bad_config_rejected_before_output(bound_case, options):
    out = bound_case["parent"] / "never-created"
    with pytest.raises(ValueError):
        figures.run(bound_case["root"].parent, bound_case["dataset"], out, **options)
    assert not out.exists()


def test_path_guards_and_cli_invalid_input(tmp_path):
    with pytest.raises(ValueError):
        figures._child(tmp_path, "../escape")
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    link.symlink_to(target, target_is_directory=True)
    with pytest.raises(ValueError, match="Linked"):
        figures._plain(link)
    script = Path(__file__).resolve().parents[2] / "scripts/render_actual_fov_figures.py"
    p = subprocess.run(
        [
            sys.executable,
            str(script),
            "--traces",
            str(tmp_path / "missing"),
            "--dataset",
            str(tmp_path / "missing"),
            "--out",
            str(tmp_path / "out"),
            "--render-case",
            "E05_N001",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert p.returncode == 2 and "ACTUAL_FOV_FIGURES_BLOCKED" in p.stderr


def test_output_inside_inputs_or_repository_is_rejected(tmp_path):
    traces, dataset = tmp_path / "traces", tmp_path / "dataset"
    traces.mkdir()
    dataset.mkdir()
    for out in (traces / "new", dataset / "new", figures.REPO / "must-not-create-test-output"):
        with pytest.raises(ValueError, match="outside inputs and Git"):
            figures.run(traces, dataset, out, render_cases=["E05_N001"])
        assert not out.exists()


@pytest.mark.parametrize(
    "mode,days", [("raw-pair", list(figures.DAYS)), ("registered-track", [8, 12])]
)
def test_non_registered_or_incomplete_metadata_not_relabelled(tmp_path, mode, days):
    root = tmp_path / "E05_N001"
    trace = StageTrace(
        root,
        metadata={
            "mode": mode,
            "neuron_id": "E05_N001",
            "expected_days": days,
            "input_axes": "TCYX",
            "coordinate_system": "registered pixels",
            "evidence_type": "SOFTWARE_FIXTURE_ONLY",
        },
    )
    trace.capture("fixture", np.zeros((2, 2)), why="SOFTWARE_FIXTURE_ONLY metadata rejection")
    trace.finish({})
    with pytest.raises(ValueError, match="nine-visit registered-track"):
        figures.TraceCase(root)
