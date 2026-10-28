"""Synthetic software controls/stub contracts only; never biological approvals."""

import json
import os
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from tmem_align.audit_v1 import review_reconciliation as rr


def context(ids=None):
    ids = ids or [w + "_N101" for w in rr.matched.WELLS]
    visits = []
    cases = []
    for nid in ids:
        rows = [
            {
                "neuron_id": nid,
                "day": d,
                "trace_manifest_sha256": "a" * 64,
                "source_sha256": "b" * 64,
                "display_sha256": "c" * 64,
                "automated_valid_488": True,
                "inherited_tracking_valid": True,
                "automated_failure_reasons": [],
            }
            for d in rr.diagnostic.DAYS
        ]
        visits.extend(rows)
        cases.append(
            {
                "neuron_id": nid,
                "visits": rows,
                "diagnostic_status": "diagnostic_complete_pending_review",
            }
        )
    return {"workspace_sha256": "d" * 64, "visits": visits, "cases": cases}


def annotations(c, positive=False):
    doc = rr.diagnostic.blank_annotations(c)
    if positive:
        doc["reviewer"] = "SYNTHETIC SOFTWARE CONTROL"
        for r in doc["observations"]:
            r.update(
                reviewer=doc["reviewer"],
                reviewed_at="2026-10-28T05:00:00Z",
                same_cell_yes_no_uncertain="yes",
                ROI_ownership_clear_uncertain_contaminated="clear",
                notes="SOFTWARE CONTROL, not independent biological evidence",
            )
    return doc


def test_blank_six_well_readiness_no_biological_computation(tmp_path):
    c = context()
    result = rr.build_report(c, annotations(c), tmp_path)
    assert len(result["visit_ledger"]) == 54 and len(result["well_readiness"]) == 6
    assert len(result["matched_pair_readiness"]) == 3
    assert not any(x["ready"] for x in result["matched_pair_readiness"])
    assert result["verified_existing_export_ids"] == []
    assert result["accepted_measurements_created_here"] == 0
    assert not result["treatment_effect_computed"] and not result["survival_analysis_performed"]
    assert all(x["nonaccepted_visits"] == 9 for x in result["well_readiness"])
    assert all("NOT_CLASSIFIED_HERE" in x["cell_fate"] for x in result["visit_ledger"])
    assert result["figure_readiness"]["figures_rendered"] is False


def test_no_final_or_561_evaluation_before_explicit_positive_review(monkeypatch, tmp_path):
    c = context()

    def forbidden(*args):
        raise AssertionError("Must not inspect final/561 evidence before 488 gates")

    monkeypatch.setattr(rr, "evaluate_final", forbidden)
    result = rr.build_report(
        c, annotations(c), tmp_path, final_links={c["cases"][0]["neuron_id"]: {"reviews": "unused"}}
    )
    assert all(
        x["final_evidence"]["state"] == "NOT_EVALUATED_BEFORE_488_REVIEW_AND_QC"
        for x in result["neuron_readiness"]
    )


@pytest.mark.parametrize(
    "nid,status",
    [
        ("F05_N025", "EXCLUDED"),
        ("N05_N011", "EXCLUDED"),
        ("N05_N012", "EXCLUDED"),
        ("E05_N006", "EXCLUDED"),
        ("F05_N007", "EXCLUDED"),
        ("J05_N015", "TECHNICAL_ONLY"),
    ],
)
def test_historical_and_technical_guards_precede_final_links(monkeypatch, tmp_path, nid, status):
    c = context([nid])
    monkeypatch.setattr(
        rr, "evaluate_final", lambda *a: pytest.fail("Excluded case must not promote final links")
    )
    result = rr.build_report(c, annotations(c, True), tmp_path)
    assert result["neuron_readiness"][0]["diagnostic_readiness"] == status
    assert result["verified_existing_export_ids"] == []
    assert result["trusted_policy"]["n012_packet_identity_not_inferred"]


@pytest.mark.parametrize("kind", ["automated", "inherited", "diagnostic"])
def test_human_positive_cannot_clear_qc(monkeypatch, tmp_path, kind):
    c = context(["E05_N101"])
    if kind == "automated":
        c["visits"][0]["automated_valid_488"] = False
    elif kind == "inherited":
        c["visits"][0]["inherited_tracking_valid"] = False
    else:
        c["cases"][0]["diagnostic_status"] = "diagnostic_rejected"
    monkeypatch.setattr(
        rr, "evaluate_final", lambda *a: pytest.fail("QC blocked must not promote final links")
    )
    result = rr.build_report(c, annotations(c, True), tmp_path)
    assert result["neuron_readiness"][0]["diagnostic_readiness"] == "QC_BLOCKED"
    assert result["verified_existing_export_ids"] == []


def test_negative_uncertain_and_notes_preserved(tmp_path):
    c = context(["E05_N101"])
    doc = annotations(c, True)
    doc["observations"][0].update(
        same_cell_yes_no_uncertain="uncertain", notes="Original uncertain observation"
    )
    result = rr.build_report(c, doc, tmp_path)
    assert result["original_human_annotations"] == doc
    assert result["visit_ledger"][0]["notes"] == "Original uncertain observation"
    assert result["neuron_readiness"][0]["unresolved_or_negative_visits"] == [8]
    assert result["verified_existing_export_ids"] == []


def test_final_links_unknown_id_rejected(tmp_path):
    c = context()
    with pytest.raises(ValueError):
        rr.build_report(c, annotations(c), tmp_path, final_links={"E05_N999": {}})


def test_missing_final_evidence_is_explicit_not_acceptance(tmp_path):
    c = context(["E05_N101"])
    result = rr.build_report(c, annotations(c, True), tmp_path)
    track = result["neuron_readiness"][0]
    assert track["diagnostic_readiness"] == "ELIGIBLE_FOR_EXISTING_FINAL_REVIEW"
    assert track["final_evidence"]["state"] == "MISSING_FINAL_EVIDENCE"
    assert "independent_final_561_QC" in track["final_evidence"]["missing"]
    assert result["verified_existing_export_ids"] == []


def test_verified_export_stub_is_not_an_accepted_cohort(monkeypatch, tmp_path):
    """Boundary stub exercises accounting only, not real acceptance verification."""
    c = context()
    monkeypatch.setattr(
        rr,
        "evaluate_final",
        lambda *a: {
            "state": "CONTROL_VERIFIED_EXPORT",
            "existing_export_verified": True,
            "fingerprints": {},
            "missing": [],
        },
    )
    result = rr.build_report(c, annotations(c, True), tmp_path)
    assert len(result["verified_existing_export_ids"]) == 6
    assert all(
        x["verified_existing_export_neurons"] == 1 and x["cohort_eligible_neurons"] == 0
        for x in result["well_readiness"]
    )
    assert not any(x["ready"] for x in result["matched_pair_readiness"])
    assert result["accepted_measurements_created_here"] == 0


def test_synthetic_final_source_cannot_be_relabelled_as_human(tmp_path):
    nid = "E05_N101"
    curated = tmp_path / "curated"
    (curated / nid).mkdir(parents=True)
    (curated / nid / "parameters.json").write_text(
        json.dumps({"evidence_type": "SYNTHETIC_EXAMPLE"})
    )
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"neuron_ids": [nid]}))
    reviews = tmp_path / "reviews.json"
    reviews.write_text(json.dumps({"reviewer": "CONTROL"}))
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    result = rr.evaluate_final(
        {
            k: str(v)
            for k, v in {
                "curated": curated,
                "config": config,
                "reviews": reviews,
                "workspace": workspace,
            }.items()
        },
        tmp_path,
        nid,
        context([nid])["cases"][0],
        tmp_path,
    )
    assert result["state"] == "FINAL_EVIDENCE_STALE_OR_INVALID"
    assert "Synthetic" in result["error"] and not result["existing_export_verified"]


@pytest.fixture
def geometry(tmp_path):
    nid = "E05_N101"
    benchmark = tmp_path / "benchmark"
    trace = benchmark / "tracks" / nid
    trace.mkdir(parents=True)
    curated = tmp_path / "curated"
    folder = curated / nid
    folder.mkdir(parents=True)
    boxes = np.zeros((9, 3, 128, 128), dtype=np.uint16)
    boxes[:, 2] = 23
    core = np.zeros((128, 128), bool)
    core[60:68, 60:68] = True
    roi = core.copy()
    records = []
    files = {}
    arrays = {f"visit_{i:02d}_registered_488": boxes[i, 2] for i in range(9)}
    arrays.update(primary_identity_core=core, phenotype_roi_holes_filled=roi)
    for name, array in arrays.items():
        path = trace / (name + ".npy")
        np.save(path, array)
        files[path.name] = rr.diagnostic.sha(path)
        records.append({"stage": name, "artifacts": {"numeric": {"path": path.name}}})
    manifest = trace / "manifest.json"
    frozen = json.loads((rr.diagnostic.ROOT / "configs/tmem_stage_diagnostics.json").read_text())
    manifest.write_text(
        json.dumps({"stages": records, "files": files, "metadata": {"parameters": frozen}})
    )
    np.savez_compressed(
        folder / "small_fixture.npz", boxes_tcyx=boxes, identity_core=core, phenotype_roi=roi
    )
    return nid, curated, benchmark, rr.diagnostic.sha(manifest), boxes, core, roi


def test_geometry_matches_exact_488_without_using_561(geometry):
    nid, c, b, h, boxes, core, roi = geometry
    assert rr.compare_geometry(c, b, nid, h)
    boxes[:, 1] = 65535  # Changed phenotype values do not select identity/ROI.
    np.savez_compressed(
        c / nid / "small_fixture.npz", boxes_tcyx=boxes, identity_core=core, phenotype_roi=roi
    )
    assert rr.compare_geometry(c, b, nid, h)


@pytest.mark.parametrize("mutation", ["488", "ROI", "dtype", "stale_manifest"])
def test_changed_geometry_never_rebinds_reviews(geometry, mutation):
    nid, c, b, h, boxes, core, roi = geometry
    if mutation == "488":
        boxes[3, 2, 64, 64] += 1
    elif mutation == "ROI":
        roi[0, 0] = True
    elif mutation == "dtype":
        core = core.astype(np.uint8)
    else:
        h = "0" * 64
    np.savez_compressed(
        c / nid / "small_fixture.npz", boxes_tcyx=boxes, identity_core=core, phenotype_roi=roi
    )
    with pytest.raises(ValueError):
        rr.compare_geometry(c, b, nid, h)


def test_synthetic_or_unreconciled_cohort_rejected(monkeypatch, tmp_path):
    path = tmp_path / "inputs.json"
    path.write_text(json.dumps({"evidence_type": "SYNTHETIC_EXAMPLE"}))
    assert rr.verify_cohort(path, set())["state"] == "COHORT_BLOCKED"
    path.write_text(json.dumps({"evidence_type": "REAL_ACCEPTED"}))
    monkeypatch.setattr(
        rr.matched,
        "load_inputs",
        lambda p: (None, None, [{"neuron_id": "E05_N101"}], {}, None, None),
    )
    assert rr.verify_cohort(path, set())["state"] == "COHORT_BLOCKED"


def test_figure_readiness_requires_live_real_cohort_and_never_renders(monkeypatch, tmp_path):
    monkeypatch.setattr(
        rr.matched,
        "verify_analysis",
        lambda p: (None, {"evidence_type": "SYNTHETIC_EXAMPLE"}, None),
    )
    result = rr.figure_readiness(tmp_path, {"state": "MISSING_ACCEPTED_COHORT_INPUTS"})
    assert not result["analysis_verified"] and not result["figures_rendered"]
    assert result["survival"].startswith("BLOCKED")


def test_genuine_verified_analysis_boundary_supports_six_well_plan(monkeypatch, tmp_path):
    """Trusted upstream return is stubbed; no real measurements/figures are produced."""
    path = tmp_path / "inputs.json"
    path.write_text("{}")
    h = rr.diagnostic.sha(path)
    ids = [w + "_N101" for w in rr.matched.WELLS]
    table = pd.DataFrame([{"neuron_id": n, "observation_status": "accepted"} for n in ids])
    metadata = {
        "evidence_type": rr.matched.REAL,
        "manifest_path": str(path),
        "input_sha256": {str(path): h},
    }
    (tmp_path / "analysis_provenance.json").write_text(json.dumps(metadata))
    monkeypatch.setattr(
        rr.matched, "verify_analysis", lambda p: ({"neuron_longitudinal": table}, metadata, None)
    )
    result = rr.figure_readiness(
        tmp_path,
        {
            "state": "VERIFIED_REAL_ACCEPTED_COHORT_INPUTS",
            "verified_ids": ids,
            "fingerprints": {str(path): h},
        },
    )
    assert result["analysis_verified"] and not result["figures_rendered"]
    assert result["matched_well_comparison"] == "READY_FOR_EXISTING_VERIFIED_PLOTTER"
    assert result["survival"].startswith("BLOCKED")


def test_private_report_preserves_inputs_notes_and_censoring_unknown(monkeypatch, tmp_path):
    c = context(["E05_N101"])
    doc = annotations(c, True)
    doc["observations"][0]["notes"] = "=CONTROL original text"
    workspace, benchmark, gallery = (tmp_path / n for n in ("workspace", "benchmark", "gallery"))
    for p in (workspace, benchmark, gallery):
        p.mkdir()
    path = tmp_path / "human.json"
    path.write_text(json.dumps(doc))
    before = path.read_bytes()
    monkeypatch.setattr(rr.diagnostic, "verify_workspace", lambda *a: c)
    out = tmp_path / "report"
    result = rr.run(workspace, benchmark, gallery, path, out)
    assert path.read_bytes() == before and result["original_human_annotations"] == doc
    assert result["accepted_measurements_created_here"] == 0
    assert "=CONTROL original text" in (out / "reconciliation.json").read_text()
    assert "'=CONTROL original text" in (out / "visit_readiness.csv").read_text()
    if os.name == "posix":
        assert out.stat().st_mode & 0o777 == 0o700
        assert (out / "reconciliation.json").stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        rr.run(workspace, benchmark, gallery, path, out)
    with pytest.raises(ValueError):
        rr.run(workspace, benchmark, gallery, path, workspace / "bad")


def test_malformed_links_and_changed_annotation_file_block_outputs(monkeypatch, tmp_path):
    c = context()
    doc = annotations(c)
    paths = [tmp_path / n for n in ("workspace", "benchmark", "gallery")]
    for p in paths:
        p.mkdir()
    human = tmp_path / "human.json"
    human.write_text(json.dumps(doc))
    monkeypatch.setattr(rr.diagnostic, "verify_workspace", lambda *a: c)
    original = rr.build_report

    def changed(*a, **kw):
        result = original(*a, **kw)
        human.write_text("changed")
        return result

    monkeypatch.setattr(rr, "build_report", changed)
    out = tmp_path / "no-output"
    with pytest.raises(ValueError, match="changed"):
        rr.run(*paths, human, out)
    assert not out.exists()


@pytest.mark.parametrize(
    "declaration",
    [
        {"schema_version": "tmem.final_review_links.v1"},
        {"schema_version": "tmem.final_review_links.v1", "tracks": []},
    ],
)
def test_malformed_final_links_schema_is_not_silently_accepted(monkeypatch, tmp_path, declaration):
    c = context()
    doc = annotations(c)
    paths = [tmp_path / n for n in ("workspace", "benchmark", "gallery")]
    for p in paths:
        p.mkdir()
    human = tmp_path / "human.json"
    human.write_text(json.dumps(doc))
    links = tmp_path / "links.json"
    links.write_text(json.dumps(declaration))
    monkeypatch.setattr(rr.diagnostic, "verify_workspace", lambda *a: c)
    out = tmp_path / "no-output"
    with pytest.raises(ValueError, match="links schema"):
        rr.run(*paths, human, out, final_links=links)
    assert not out.exists()


def primary_parameters():
    return {
        "bbox_size": 128,
        "segmentation_min_area": 180,
        "identity_consensus_fraction": 0.6,
        "min_core_area": 80,
        "max_core_area": 2500,
        "phenotype_dilation": 2,
        "background_exclusion": 8,
        "puncta_min_size": 6,
    }


def test_primary_parameters_required_even_when_masks_happen_to_match():
    frozen = json.loads((rr.diagnostic.ROOT / "configs/tmem_stage_diagnostics.json").read_text())
    assert rr.compare_parameters(primary_parameters(), frozen)
    for key, value in [
        ("segmentation_min_area", 220),
        ("phenotype_dilation", 1),
        ("search_radius", 80),
        ("bbox_size", True),
    ]:
        params = primary_parameters()
        params[key] = value
        with pytest.raises(ValueError):
            rr.compare_parameters(params, frozen)
    with pytest.raises(ValueError):
        rr.compare_parameters({}, frozen)


def test_analysis_not_opened_before_488_and_export_gates(monkeypatch, tmp_path):
    path = tmp_path / "inputs.json"
    path.write_text(json.dumps({"evidence_type": "REAL_ACCEPTED"}))
    monkeypatch.setattr(
        rr.matched, "load_inputs", lambda *a: pytest.fail("Premature phenotype read")
    )
    monkeypatch.setattr(
        rr.matched, "verify_analysis", lambda *a: pytest.fail("Premature phenotype figure read")
    )
    cohort = rr.verify_cohort(path, set())
    assert cohort["state"] == "COHORT_BLOCKED"
    assert not rr.figure_readiness(tmp_path, cohort)["analysis_verified"]


@pytest.mark.parametrize(
    "mode", ["pass", "review_pending", "qc_failed", "export_stale", "no_export", "shared_export"]
)
def test_existing_v6_adapter_delegation_contract(geometry, monkeypatch, tmp_path, mode):
    """Upstream human/export checks are explicit stubs, not genuine approvals."""
    from types import SimpleNamespace

    nid, curated, benchmark, h, *_ = geometry
    folder = curated / nid
    (folder / "parameters.json").write_text(
        json.dumps({**primary_parameters(), "_SOFTWARE_FIXTURE_ONLY": True})
    )
    (folder / "metrics.csv").write_text("SOFTWARE_FIXTURE_ONLY\n")
    config = tmp_path / "config.json"
    cfg = {"neuron_ids": [nid], "known_exclusions": {}}
    config.write_text(json.dumps(cfg))
    reviews = tmp_path / "reviews.json"
    reviews.write_text(json.dumps({"reviewer": "contract_test_fixture_only"}))
    workspace = tmp_path / "final-workspace"
    workspace.mkdir()
    (workspace / "config.json").write_text(json.dumps(cfg))
    (workspace / "render_manifest.json").write_text("{}")
    export = tmp_path / "export"
    export.mkdir()
    (export / "analysis_scope.json").write_text(json.dumps({"accepted_ids": [nid]}))
    if mode == "shared_export":
        (export / "analysis_scope.json").write_text(json.dumps({"accepted_ids": [nid, "I05_N002"]}))
    source = [
        {
            "neuron_id": nid,
            "files": {"parameters.json": {"sha256": rr.diagnostic.sha(folder / "parameters.json")}},
        }
    ]
    monkeypatch.setattr(rr, "evidence_manifest", lambda *a: source)
    monkeypatch.setattr(
        rr, "verify_review_workspace", lambda *a: {"workspace_sha256": "f" * 64, "files": {}}
    )
    monkeypatch.setattr(
        rr,
        "evaluate_review",
        lambda *a, **kw: {
            "tracks": [{"neuron_id": nid, "eligible": mode != "review_pending", "reasons": []}]
        },
    )
    monkeypatch.setattr(
        rr,
        "_exporter",
        lambda: SimpleNamespace(
            automated_failures=lambda p: ["CONTROL global QC failed"] if mode == "qc_failed" else []
        ),
    )

    def bundle(*args):
        if mode == "shared_export":
            pytest.fail("Shared export measurements must not open")
        if mode == "export_stale":
            raise ValueError("CONTROL stale export")
        return [{"neuron_id": nid, "day": d} for d in rr.diagnostic.DAYS]

    monkeypatch.setattr(rr.matched, "load_bundle", bundle)
    entry = {
        k: str(v)
        for k, v in {
            "curated": curated,
            "workspace": workspace,
            "config": config,
            "reviews": reviews,
        }.items()
    }
    if mode != "no_export":
        entry["export"] = str(export)
    case = context([nid])["cases"][0]
    for r in case["visits"]:
        r["trace_manifest_sha256"] = h
    result = rr.evaluate_final(entry, tmp_path, nid, case, benchmark)
    assert result["existing_export_verified"] == (mode == "pass")
    assert result["accepted_measurements_created_here"] is False
    expected = {
        "pass": "VERIFIED_EXISTING_EXPORT",
        "review_pending": "FINAL_REVIEW_PENDING",
        "qc_failed": "FINAL_QC_BLOCKED",
        "export_stale": "FINAL_EVIDENCE_STALE_OR_INVALID",
        "no_export": "EXISTING_EXPORT_MISSING",
        "shared_export": "FINAL_EVIDENCE_STALE_OR_INVALID",
    }
    assert result["state"] == expected[mode]


def test_shared_final_config_blocked_before_measurements(tmp_path, monkeypatch):
    nid = "I05_N001"
    curated = tmp_path / "curated"
    workspace = tmp_path / "workspace"
    curated.mkdir()
    workspace.mkdir()
    config = tmp_path / "config.json"
    reviews = tmp_path / "reviews.json"
    config.write_text(json.dumps({"neuron_ids": [nid, "I05_N002"]}))
    reviews.write_text("{}")
    monkeypatch.setattr(rr, "evidence_manifest", lambda *a: pytest.fail("No measurement reads"))
    result = rr.evaluate_final(
        {
            "curated": str(curated),
            "workspace": str(workspace),
            "config": str(config),
            "reviews": str(reviews),
        },
        tmp_path,
        nid,
        {},
        tmp_path,
    )
    assert result["state"] == "FINAL_EVIDENCE_STALE_OR_INVALID"
    assert "target-only" in result["error"]


@pytest.mark.parametrize("changed", ["substitution", "fingerprint", "unchanged"])
def test_cohort_exact_binding_before_measurements(tmp_path, monkeypatch, changed):
    nid = "I05_N001"
    paths = {}
    for name in ("curated", "workspace", "export"):
        path = tmp_path / name
        path.mkdir()
        paths[name] = str(path)
    for name in ("config", "reviews"):
        path = tmp_path / (name + ".json")
        path.write_text("{}")
        paths[name] = str(path)
    (Path(paths["export"]) / "analysis_scope.json").write_text(json.dumps({"accepted_ids": [nid]}))
    manifest = tmp_path / "inputs.json"
    manifest.write_text(json.dumps({"evidence_type": rr.matched.REAL, "bundles": [paths]}))
    binding = dict(paths)
    if changed == "substitution":
        binding["curated"] = str(tmp_path / "different-488-geometry")
    fingerprints = {
        paths["config"]: "changed"
        if changed == "fingerprint"
        else rr.diagnostic.sha(Path(paths["config"]))
    }

    def load(*args):
        assert changed == "unchanged", "No phenotype reads before exact binding"
        return None, None, [{"neuron_id": nid}], {}, None, None

    monkeypatch.setattr(rr.matched, "load_inputs", load)
    result = rr.verify_cohort(
        manifest, {nid: {"bundle_paths": binding, "fingerprints": fingerprints}}
    )
    assert result["state"] == (
        "VERIFIED_REAL_ACCEPTED_COHORT_INPUTS" if changed == "unchanged" else "COHORT_BLOCKED"
    )
