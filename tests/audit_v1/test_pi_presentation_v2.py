"""SOFTWARE_FIXTURE_ONLY editable V2, no real image acceptance."""

import json
import sys
from pathlib import Path

import pytest

pytest.importorskip("pptx")
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import create_pi_presentation_v2 as v2

from tests.audit_v1.test_final_pi_presentation import explicit_curation, pi, private_project  # noqa: F401


def test_constructed_v2_native_plate_and_notes(private_project, tmp_path):  # noqa: F811
    c = json.loads(
        (Path(__file__).resolve().parents[2] / "configs/tmem_full_plate_20261104.json").read_text()
    )
    audit = {
        "status": "PENDING",
        "selection_rows": 1728,
        "qc_rows": 0,
        "missing_tables": ["registration_qc"],
        "by_well": [{"well": w, "pass_fraction": None, "status": "PENDING"} for w in c["wells"]],
        "by_day": [
            {"day": d, "expected_wells": 192, "qc_observations": 0, "missing": 192}
            for d in c["visits"]
        ],
    }
    out = tmp_path / "V2"
    result = pi.generate(
        private_project,
        out,
        explicit_curation(private_project),
        lambda d, e: v2.revise(d, e, audit, c),
        name="V2",
    )
    from pptx import Presentation

    prs = Presentation(out / "V2.pptx")
    assert len(prs.slides) == 20 and result["accepted_ids"] == []
    chart_labels = [s.text for s in prs.slides[10].shapes if s.has_text_frame]
    assert chart_labels.count("Minimum-area preference (px)") == 2
    assert any(
        "Nov 3 branch controls" in cell.text
        for s in prs.slides[18].shapes
        if s.has_table
        for row in s.table.rows
        for cell in row.cells
    )
    texts = [s.text for s in prs.slides[12].shapes if s.has_text_frame]
    assert sum(w in texts for w in c["wells"]) == 192
    assert all(
        "unconfirmed" in " ".join(s.text for s in prs.slides[i].shapes if s.has_text_frame)
        for i in [0, 1, 9]
    )
    for i in [4, 12, 13, 14]:
        notes = prs.slides[i].notes_slide.notes_text_frame.text
        assert all(label in notes for label in ["WHAT", "WHY", "HOW", "RESULT", "LIMIT", "NEXT"])


@pytest.mark.parametrize("damage", [None, "day", "index", "channel", "prefix", "parent", "hash"])
def test_visit_index_source_guard(damage):
    from copy import deepcopy
    from types import SimpleNamespace

    prefix = "primary_segmentation_visit_08"
    raw = {
        "stage": "visit_08_registered_488",
        "channel": "488",
        "array_sha256": "raw",
        "details": {"day": 39, "time_index": 8},
    }
    threshold = {
        "stage": prefix + "_candidate_09_threshold",
        "array_sha256": "threshold",
        "parents": [prefix + "_smoothed", prefix + "_allowed_region"],
    }
    selected = {
        "stage": prefix + "_selected_component",
        "array_sha256": "selected",
        "parents": [prefix + "_candidate_09_selection"],
    }
    crop = {"stage": prefix + "_crop", "array_sha256": "raw"}
    trace = {
        "metadata": {"expected_days": [8, 12, 16, 20, 25, 29, 32, 36, 39]},
        "stages": deepcopy([raw, threshold, selected]),
    }
    cards = [{} for _ in range(13)]
    for i, record in [(1, crop), (6, threshold), (12, selected)]:
        cards[i] = {"provenance": {"record": record}}
    evidence = SimpleNamespace(
        sources={"fixture": {"trace": "SOFTWARE_FIXTURE_ONLY"}},
        load=lambda _path: trace,
        sheets={"fixture_day39_flow": {"cards": cards}},
    )
    if damage == "day":
        trace["stages"][0]["details"]["day"] = 8
    elif damage == "index":
        trace["stages"][0]["details"]["time_index"] = 0
    elif damage == "channel":
        trace["stages"][0]["channel"] = "561"
    elif damage == "prefix":
        threshold["stage"] = "primary_segmentation_visit_00_candidate_09_threshold"
    elif damage == "parent":
        selected["parents"] = ["wrong_visit_selection"]
    elif damage == "hash":
        crop["array_sha256"] = "substituted"
    if damage is None:
        assert v2.validate_segmentation_source(evidence, "fixture", 39)["time_index"] == 8
    else:
        with pytest.raises((ValueError, KeyError)):
            v2.validate_segmentation_source(evidence, "fixture", 39)


def test_v3_opening_layout_with_separately_tested_guard(private_project, tmp_path, monkeypatch):  # noqa: F811
    # Layout isolation only. Guard corruption is exercised independently above,
    # and the actual private V3 build executes the production guard on saved sources.
    monkeypatch.setattr(v2, "validate_segmentation_source", lambda *_: {"day": 39, "time_index": 8})
    c = json.loads(
        (Path(__file__).resolve().parents[2] / "configs/tmem_full_plate_20261104.json").read_text()
    )
    audit = {
        "status": "PENDING",
        "selection_rows": 1728,
        "qc_rows": 0,
        "missing_tables": ["registration_qc"],
        "process_status_observation": "RUNNING",
        "by_well": [{"well": w, "pass_fraction": None, "status": "PENDING"} for w in c["wells"]],
        "by_day": [
            {"day": d, "expected_wells": 192, "qc_observations": 0, "missing": 192}
            for d in c["visits"]
        ],
    }
    out = tmp_path / "V3"
    result = pi.generate(
        private_project,
        out,
        explicit_curation(private_project),
        lambda d, e: v2.revise(d, e, audit, c, "V3"),
        name="V3",
    )
    from pptx import Presentation

    prs = Presentation(out / "V3.pptx")
    assert len(prs.slides) == 20 and not result["accepted_ids"]
    for slide in list(prs.slides)[:2]:
        text = " ".join(s.text for s in slide.shapes if s.has_text_frame)
        assert "N05_N010" not in text and "Context only" in text
    assert "filename-identified well IDs" in " ".join(
        s.text for s in prs.slides[4].shapes if s.has_text_frame
    )
