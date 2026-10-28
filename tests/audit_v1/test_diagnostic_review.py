"""Software controls only. Reviewer names/decisions here are not biological labels."""

import copy
import json

import pytest
from PIL import Image

from tmem_align.audit_v1 import diagnostic_review as review


@pytest.fixture
def workspace(tmp_path):
    benchmark, gallery, out = (tmp_path / n for n in ("benchmark", "gallery", "workspace"))
    benchmark.mkdir()
    gallery.mkdir()
    nid = "E05_N101"
    trace = benchmark / "tracks" / nid
    trace.mkdir(parents=True)
    files, records = {}, []

    def save(name, value):
        path = trace / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value))
        files[name] = review.sha(path)
        return files[name]

    def stage(name, details=None):
        array = "stages/" + name + "/array.npy"
        path = trace / array
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"SOFTWARE CONTROL ONLY, not experimental pixels")
        files[array] = review.sha(path)
        record = {
            "stage": name,
            "artifacts": {"numeric": {"path": array}},
            "details": details or {},
            "record_file": "stages/" + name + "/stage.json",
        }
        record["record_sha256"] = save(record["record_file"], {"details": details or {}})
        records.append(record)

    for i in range(9):
        stage(f"visit_{i:02d}_registered_488")
        stage(f"primary_segmentation_visit_{i:02d}_qc", {"tracking_valid_inherited": True})
    stage("primary_identity_core")
    stage("phenotype_roi_holes_filled")
    save(
        "summary.json",
        {
            "real_accepted_ids": [],
            "scientific_inference_ready": False,
            "diagnostic_status": "diagnostic_complete_pending_review",
            "core_area_px": 100,
            "automated_secondary_soma_single_pass": True,
            "valid_488_by_day": {str(d): True for d in review.DAYS},
        },
    )
    save(
        "crop_geometry.json",
        [{"day": d, "bounds": {"y0": 0, "x0": 0, "y1": 128, "x1": 128}} for d in review.DAYS],
    )
    save(
        "tracking_comparison.json",
        {
            "all_proposals_unadopted": True,
            "results_by_radius": {"60": [{"historical_tracking_valid": True} for _ in review.DAYS]},
        },
    )
    save("parameter_sensitivity.json", {"all_settings_unadopted": True, "settings": []})
    (trace / "manifest.json").write_text(json.dumps({"files": files, "stages": records}))
    state = {
        "status": "completed_pending_scientific_review",
        "master_and_configuration_unchanged": True,
        "scientific_inference_ready": False,
        "real_accepted_ids": [],
        "days": list(review.DAYS),
        "selected_neuron_ids": [nid],
        "input_files": {"master": {"sha256": "a" * 64}},
        "configuration": {"sha256": "b" * 64},
    }
    (benchmark / "benchmark_summary.json").write_text(json.dumps(state))
    (gallery / "panel_summary.json").write_text(
        json.dumps(
            {
                "benchmark_summary_sha256": review.sha(benchmark / "benchmark_summary.json"),
                "cases": [
                    {"neuron_id": nid, "trace_manifest_sha256": review.sha(trace / "manifest.json")}
                ],
            }
        )
    )
    for suffix, shape in [("_488.png", (1152, 1296)), ("_488_search_context.png", (1206, 1350))]:
        Image.new("RGB", shape, "black").save(gallery / (nid + suffix))
    source_before = {
        str(p): review.sha(p)
        for root in (benchmark, gallery)
        for p in root.rglob("*")
        if p.is_file()
    }
    context = review.prepare(benchmark, gallery, out)
    assert source_before == {p: review.sha(p) for p in source_before}
    return benchmark, gallery, out, context


def decided(context, identity="yes", ownership="clear"):
    doc = review.blank_annotations(context)
    doc["reviewer"] = "SOFTWARE CONTROL REVIEWER"
    for r in doc["observations"]:
        r.update(
            reviewer=doc["reviewer"],
            reviewed_at="2026-10-27T20:00:00-04:00",
            same_cell_yes_no_uncertain=identity,
            ROI_ownership_clear_uncertain_contaminated=ownership,
            notes="Software control, not actual human review",
        )
    return doc


def test_blank_private_workspace_source_read_only(workspace):
    b, g, w, c = workspace
    before = {str(p): review.sha(p) for root in (b, g) for p in root.rglob("*") if p.is_file()}
    assert review.verify_workspace(w, b, g) == c
    doc = review.load_annotations(w / "blank_annotations.json")
    result = review.validate(doc, c)
    assert result["complete_decisions"] == 0 and result["unreviewed_or_partial"] == 9
    assert result["real_accepted_ids"] == []
    assert result["tracks"][0]["status"] == "REVIEW_PENDING"
    assert before == {p: review.sha(p) for p in before}
    assert review.validate(review.load_annotations(w / "blank_annotations.csv"), c) == result
    assert "connect-src 'none'" in (w / "index.html").read_text()


def test_complete_identity_sheet_is_not_export_acceptance(workspace):
    _, _, _, c = workspace
    result = review.validate(decided(c), c)
    assert result["tracks"][0]["status"] == "ELIGIBLE_FOR_EXISTING_FINAL_REVIEW"
    assert result["real_accepted_ids"] == [] and not result["tracks"][0]["accepted"]
    assert result["tracks"][0]["existing_final_export_requirements"]


@pytest.mark.parametrize(
    "identity,ownership", [("uncertain", "clear"), ("yes", "uncertain"), ("no", "contaminated")]
)
def test_explicit_uncertainty_never_becomes_eligible(workspace, identity, ownership):
    c = workspace[3]
    result = review.validate(decided(c, identity, ownership), c)
    assert result["unresolved_decisions"] == 9
    assert result["tracks"][0]["status"] == "REVIEW_PENDING"


@pytest.mark.parametrize(
    "field,value",
    [
        ("same_cell_yes_no_uncertain", "accept"),
        ("ROI_ownership_clear_uncertain_contaminated", "pass"),
        ("source_channel", "561"),
        ("reviewer", "another reviewer"),
        ("reviewed_at", "2026-10-27"),
        ("reviewed_at", "nonsense"),
        ("day", True),
        ("trace_manifest_sha256", "0" * 64),
        ("source_sha256", "0" * 64),
        ("display_sha256", "0" * 64),
    ],
)
def test_invalid_attribution_categories_and_hashes(workspace, field, value):
    c = workspace[3]
    doc = decided(c)
    doc["observations"][0][field] = value
    with pytest.raises(ValueError):
        review.validate(doc, c)


def test_duplicates_missing_unknown_fields_and_timestamp(workspace):
    c = workspace[3]
    for mutate in (
        lambda d: d["observations"].append(copy.deepcopy(d["observations"][0])),
        lambda d: d["observations"].pop(),
        lambda d: d["observations"][0].update(accepted=True),
        lambda d: d["observations"][0].update(phenotype_qc_561="pass"),
        lambda d: d["observations"][0].update(reviewed_at=""),
    ):
        doc = decided(c)
        mutate(doc)
        with pytest.raises(ValueError):
            review.validate(doc, c)


def test_uncertainty_requires_note_and_partial_stays_partial(workspace):
    c = workspace[3]
    doc = decided(c, "uncertain", "clear")
    doc["observations"][0]["notes"] = ""
    with pytest.raises(ValueError, match="Explain"):
        review.validate(doc, c)
    doc = decided(c)
    doc["observations"][0][review.DECISIONS[1]] = ""
    assert review.validate(doc, c)["unreviewed_or_partial"] == 1


@pytest.mark.parametrize("target", ["gallery", "array", "html", "manifest"])
def test_changed_source_or_display_is_stale(workspace, target):
    b, g, w, _ = workspace
    paths = {
        "gallery": g / "E05_N101_488.png",
        "array": b / "tracks/E05_N101/stages/visit_00_registered_488/array.npy",
        "html": w / "index.html",
        "manifest": b / "tracks/E05_N101/manifest.json",
    }
    with paths[target].open("ab") as stream:
        stream.write(b"changed")
    with pytest.raises(ValueError):
        review.verify_workspace(w, b, g)


@pytest.mark.parametrize(
    "nid,status",
    [
        ("J05_N015", "TECHNICAL_ONLY"),
        ("F05_N025", "EXCLUDED"),
        ("N05_N011", "EXCLUDED"),
        ("N05_N012", "EXCLUDED"),
        ("E05_N006", "EXCLUDED"),
        ("F05_N007", "EXCLUDED"),
    ],
)
def test_known_exclusion_and_technical_policy_not_overridden(workspace, nid, status):
    c = copy.deepcopy(workspace[3])
    c["cases"][0]["neuron_id"] = nid
    for r in c["visits"]:
        r["neuron_id"] = nid
    assert review.validate(decided(c), c)["tracks"][0]["status"] == status


def test_failed_qc_cannot_be_cleared_by_human_yes(workspace):
    c = copy.deepcopy(workspace[3])
    c["cases"][0]["visits"][0]["automated_valid_488"] = False
    assert review.validate(decided(c), c)["tracks"][0]["status"] == "QC_BLOCKED"
    assert review.validate(decided(c), c)["real_accepted_ids"] == []


def test_csv_roundtrip_formula_rejection_and_no_overwrite(workspace, tmp_path):
    c = workspace[3]
    doc = decided(c)
    path = tmp_path / "annotations.csv"
    review.write_csv(path, doc)
    assert review.validate(review.load_annotations(path), c) == review.validate(doc, c)
    with pytest.raises(FileExistsError):
        review.write_csv(path, doc)
    doc["observations"][0]["notes"] = '=HYPERLINK("evil")'
    with pytest.raises(ValueError):
        review.write_csv(tmp_path / "unsafe.csv", doc)
    assert not (tmp_path / "unsafe.csv").exists()


def test_private_outputs_cannot_target_source_or_repo(workspace):
    b, g, w, _ = workspace
    for path in (b / "bad", g / "bad", review.ROOT / "bad"):
        with pytest.raises(ValueError):
            review.output_path(path, [b, g])
    with pytest.raises(FileExistsError):
        review.prepare(b, g, w)


def test_duplicate_json_keys_rejected(tmp_path):
    path = tmp_path / "review.json"
    path.write_text('{"reviewer":"a","reviewer":"b"}')
    with pytest.raises(ValueError, match="Duplicate"):
        review.load_annotations(path)


def test_document_cannot_carry_acceptance_or_561_decisions(workspace):
    c = workspace[3]
    doc = decided(c)
    doc["accepted_ids"] = ["E05_N101"]
    with pytest.raises(ValueError):
        review.validate(doc, c)
    with pytest.raises(ValueError):
        review.validate([], c)
    doc = decided(c)
    doc["observations"][0][review.DECISIONS[0]] = []
    with pytest.raises(ValueError):
        review.validate(doc, c)


def test_validator_cli_stale_report_and_private_output(workspace, tmp_path):
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "diagnostic_cli", review.ROOT / "scripts/diagnostic_review.py"
    )
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    b, g, w, _c = workspace
    annotations = w / "blank_annotations.json"
    out = tmp_path / "validation.json"
    args = [
        "validate",
        "--benchmark",
        str(b),
        "--gallery",
        str(g),
        "--workspace",
        str(w),
        "--annotations",
        str(annotations),
        "--out",
        str(out),
    ]
    assert cli.main(args) == 0
    assert json.loads(out.read_text())["real_accepted_ids"] == []
    with (w / "index.html").open("a") as f:
        f.write("changed display")
    stale = tmp_path / "stale.json"
    args[-1] = str(stale)
    assert cli.main(args) == 2
    verdict = json.loads(stale.read_text())
    assert verdict["tracks"][0]["status"] == "EVIDENCE_STALE"
    assert verdict["real_accepted_ids"] == []


def test_inherited_qc_and_diagnostic_rejection_cannot_be_overridden(workspace):
    for mode in ("inherited", "diagnostic"):
        context = copy.deepcopy(workspace[3])
        if mode == "inherited":
            context["cases"][0]["visits"][0]["inherited_tracking_valid"] = False
        else:
            context["cases"][0]["diagnostic_status"] = "diagnostic_rejected"
        assert review.validate(decided(context), context)["tracks"][0]["status"] == "QC_BLOCKED"


@pytest.mark.parametrize(
    "field,value,status",
    [
        ("same_cell_yes_no_uncertain", "accept", "ANNOTATION_INVALID"),
        ("source_sha256", "0" * 64, "EVIDENCE_STALE"),
    ],
)
def test_invalid_annotation_cli_produces_private_blocking_report(
    workspace, tmp_path, field, value, status
):
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "diagnostic_cli_invalid", review.ROOT / "scripts/diagnostic_review.py"
    )
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    b, g, w, c = workspace
    doc = decided(c)
    doc["observations"][0][field] = value
    path = tmp_path / "invalid-review.json"
    path.write_text(json.dumps(doc))
    out = tmp_path / "invalid-report.json"
    assert (
        cli.main(
            [
                "validate",
                "--benchmark",
                str(b),
                "--gallery",
                str(g),
                "--workspace",
                str(w),
                "--annotations",
                str(path),
                "--out",
                str(out),
            ]
        )
        == 2
    )
    result = json.loads(out.read_text())
    assert result["status"] == status and result["real_accepted_ids"] == []
