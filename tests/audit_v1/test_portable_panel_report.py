"""Tiny reporting fixtures validate controls, not experimental cell identity."""

import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "panel_report", ROOT / "scripts/report_portable_panel.py"
)
reporter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(reporter)


def tracking():
    return {
        "primary_search_radius_px": 60,
        "all_proposals_unadopted": True,
        "results_by_radius": {
            str(radius): [
                {
                    "day": day,
                    "adopted": False,
                    "candidate_anchor_yx_px": [radius, i],
                    "displacement_from_stored_anchor_px": radius,
                }
                for i, day in enumerate(reporter.DAYS)
            ]
            for radius in (40, 60, 80)
        },
    }


def test_tracking_agreement_is_not_accuracy():
    result = reporter.tracking_agreement(tracking())
    assert result["60"]["departure_from_primary_proposal_px"]["max"] == 0
    assert result["40"]["departure_from_primary_proposal_px"]["median"] == 20
    assert result["40"]["visits_differing_from_primary_over_20px"] == 0
    assert result["80"]["descriptive_threshold_not_an_acceptance_gate"]


@pytest.mark.parametrize("mutation", ["adopted", "missing_visit", "wrong_day", "missing_primary"])
def test_tracking_requires_unadopted_nine_visits(mutation):
    value = tracking()
    if mutation == "adopted":
        value["results_by_radius"]["40"][0]["adopted"] = True
    elif mutation == "missing_visit":
        value["results_by_radius"]["40"].pop()
    elif mutation == "wrong_day":
        value["results_by_radius"]["40"][0]["day"] = 9
    else:
        del value["results_by_radius"]["60"]
    with pytest.raises(ValueError):
        reporter.tracking_agreement(value)


def test_mask_overlap_has_explicit_empty_support():
    empty = np.zeros((2, 2), dtype=bool)
    assert reporter.mask_overlap(empty, empty)["roi_mask_IoU"] is None
    roi = np.array([[1, 1], [0, 0]], dtype=bool)
    mask = np.array([[1, 0], [1, 0]], dtype=bool)
    result = reporter.mask_overlap(roi, mask)
    assert result["roi_mask_IoU"] == pytest.approx(1 / 3)
    assert result["roi_supported_by_primary_488_mask_fraction"] == 0.5
    assert result["agreement_only_not_ROI_ownership"]
    with pytest.raises(ValueError):
        reporter.mask_overlap(roi, np.zeros((3, 2)))


def test_artifact_hashes_and_safe_paths(tmp_path):
    path = tmp_path / "array.npy"
    path.write_bytes(b"CONTROL FIXTURE ONLY")
    hashes = {"array.npy": hashlib.sha256(path.read_bytes()).hexdigest()}
    assert reporter.bound_file(tmp_path, "array.npy", hashes) == path
    with pytest.raises(ValueError):
        reporter.bound_file(tmp_path, "../escape", hashes)
    path.write_bytes(b"mutated")
    with pytest.raises(ValueError, match="checksum"):
        reporter.bound_file(tmp_path, "array.npy", hashes)


def test_symlink_artifacts_rejected(tmp_path):
    path = tmp_path / "source"
    path.write_bytes(b"fixture")
    (tmp_path / "link").symlink_to(path)
    with pytest.raises(ValueError, match="Linked"):
        reporter.bound_file(tmp_path, "link", {"link": reporter.digest(path)})


def test_distribution_rejects_nonfinite_and_empty():
    for values in ([], [float("nan")], [float("inf")]):
        with pytest.raises(ValueError):
            reporter.distribution(values)


def test_running_benchmark_cannot_be_misreported(tmp_path):
    benchmark = tmp_path / "benchmark"
    benchmark.mkdir()
    (benchmark / "benchmark_summary.json").write_text(json.dumps({"status": "running"}))
    with pytest.raises(ValueError, match="checkpointed"):
        reporter.report(benchmark, tmp_path / "review")
    assert not (tmp_path / "review").exists()


def test_report_cannot_write_into_benchmark(tmp_path):
    with pytest.raises(ValueError, match="outside"):
        reporter.report(tmp_path, tmp_path / "review")


def test_failed_and_deferred_cases_remain_explicit(tmp_path):
    benchmark = tmp_path / "benchmark"
    benchmark.mkdir()
    value = {
        "status": "partial_or_blocked",
        "master_and_configuration_unchanged": True,
        "real_accepted_ids": [],
        "scientific_inference_ready": False,
        "selected_neuron_ids": ["E05_N100", "F05_N100"],
        "results": {"E05_N100": {"status": "failed"}, "F05_N100": {"status": "deferred_budget"}},
        "input_files": {"master": {"sha256": "a" * 64}},
        "configuration": {"sha256": "b" * 64},
    }
    (benchmark / "benchmark_summary.json").write_text(json.dumps(value))
    result = reporter.report(benchmark, tmp_path / "review")
    assert result["execution_counts"] == {"failed": 1, "deferred_budget": 1}
    assert result["real_accepted_ids"] == []
    assert result["cases"] == []
    assert "not evaluated" in (tmp_path / "review/index.html").read_text()
    assert "Release blocked" in (tmp_path / "review/index.html").read_text()
    assert (tmp_path / "review/review_template.csv").read_text().count("\n") == 1
    assert "never adopted" in (tmp_path / "review/processing_flow.mmd").read_text()


def test_report_never_overwrites_existing_output(tmp_path):
    benchmark = tmp_path / "benchmark"
    benchmark.mkdir()
    (benchmark / "benchmark_summary.json").write_text(
        json.dumps(
            {
                "status": "partial_or_blocked",
                "master_and_configuration_unchanged": True,
                "real_accepted_ids": [],
                "scientific_inference_ready": False,
            }
        )
    )
    out = tmp_path / "review"
    out.mkdir()
    with pytest.raises(FileExistsError):
        reporter.report(benchmark, out)


def test_changed_source_checkpoint_is_unusable(tmp_path):
    benchmark = tmp_path / "benchmark"
    benchmark.mkdir()
    (benchmark / "benchmark_summary.json").write_text(
        json.dumps(
            {"status": "unusable_source_changed", "master_and_configuration_unchanged": False}
        )
    )
    with pytest.raises(ValueError, match="unchanged source"):
        reporter.report(benchmark, tmp_path / "review")
    assert not (tmp_path / "review").exists()


def test_complete_case_contact_sheet_is_source_read_only(tmp_path):
    """Minimal image fixture tests reporting, not microscopy or biological validity."""
    from PIL import Image

    trace, out = tmp_path / "trace", tmp_path / "out"
    trace.mkdir()
    out.mkdir()
    files, stages = {}, []

    def save_json(name, value):
        path = trace / name
        path.write_text(json.dumps(value))
        files[name] = reporter.digest(path)

    def stage(name, array, preview=False):
        path = trace / (name + ".npy")
        np.save(path, array)
        files[path.name] = reporter.digest(path)
        artifacts = {"numeric": {"path": path.name}}
        if preview:
            png = trace / (name + ".png")
            Image.new("RGB", (128, 128), "#002000").save(png)
            files[png.name] = reporter.digest(png)
            artifacts["preview"] = {"path": png.name}
        stages.append({"stage": name, "artifacts": artifacts})

    mask = np.zeros((128, 128), dtype=bool)
    mask[60:68, 60:68] = True
    for i in range(9):
        stage(f"visit_{i:02d}_registered_488", mask.astype("uint16"), preview=True)
        stage(f"primary_identity_input_{i:02d}", mask)
        stage(f"tracking_r080_visit_{i:02d}_raw_search", mask.astype("uint16"), preview=True)
        stages[-1]["details"] = {"bounds_y0_y1_x0_x1": [0, 128, 0, 128]}
    stage("phenotype_roi_holes_filled", mask)
    stage("primary_identity_core", mask)
    save_json(
        "summary.json",
        {
            "software_execution_complete": True,
            "real_accepted_ids": [],
            "scientific_inference_ready": False,
            "production_eligible": False,
            "diagnostic_status": "diagnostic_complete_pending_review",
            "valid_488_visit_count": 9,
            "valid_488_by_day": {str(d): True for d in reporter.DAYS},
            "core_area_px": 64,
            "automated_secondary_soma_single_pass": True,
        },
    )
    save_json("tracking_comparison.json", tracking())
    save_json("parameter_sensitivity.json", {"all_settings_unadopted": True, "settings": []})
    save_json(
        "crop_geometry.json",
        [
            {
                "anchor_yx_crop_px": [64, 64],
                "anchor_yx_registered_px": [64, 64],
                "bounds": {"y0": 0, "x0": 0, "y1": 128, "x1": 128},
            }
        ]
        * 9,
    )
    (trace / "manifest.json").write_text(
        json.dumps(
            {
                "complete": True,
                "real_accepted_ids": [],
                "scientific_inference_ready": False,
                "files": files,
                "stages": stages,
                "stage_status_counts": {"executed": 20},
            }
        )
    )
    before = {p.name: reporter.digest(p) for p in trace.iterdir()}
    result = reporter.inspect_case(trace, out, "E05_N100")
    assert result["accuracy_established"] is False
    assert len(result["roi_mask_agreement"]) == 9
    assert Image.open(out / "E05_N100_488.png").size == (1152, 1296)
    assert result["larger_registered_search_context_available"]
    assert Image.open(out / "E05_N100_488_search_context.png").size == (1206, 1350)
    assert before == {p.name: reporter.digest(p) for p in trace.iterdir()}
