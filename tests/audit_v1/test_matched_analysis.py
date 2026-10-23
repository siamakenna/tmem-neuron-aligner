"""New analysis tests only; synthetic review assignments are not human decisions."""

import csv
import shutil

import numpy as np
import pytest

from tmem_align.audit_v1.analysis_example import (
    create_example,
    source_script,
    write_csv,
    write_json,
)
from tmem_align.audit_v1.matched_analysis import (
    DAYS,
    analyze,
    build_tables,
    quantity_values,
    read_json,
    verify_analysis,
)


@pytest.fixture(scope="module")
def example(tmp_path_factory):
    root = tmp_path_factory.mktemp("synthetic-bundle") / "source"
    create_example(root)
    return root


@pytest.fixture
def bundle(example, tmp_path):
    root = tmp_path / "inputs"
    shutil.copytree(example, root)
    return root


def csv_rows(path):
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def test_valid_analysis_keeps_replication_at_well_level(example):
    tables, metadata, warnings = build_tables(example / "analysis_inputs.json")
    wells, pairs, conditions = (
        tables[key] for key in ("well_day_summary", "matched_pair_day", "condition_day_summary")
    )
    assert len(wells) == 54 and len(pairs) == 27
    e05 = wells[(wells.well == "E05") & (wells.day == 8)].iloc[0]
    assert e05.n_accepted_neurons == 2
    row = conditions[(conditions.condition == "reporter_control") & (conditions.day == 8)].iloc[0]
    control = wells[(wells.condition == "reporter_control") & (wells.day == 8)]
    assert row.mean_mcherry_intensity_equal_well_mean == pytest.approx(
        control.mean_mcherry_intensity_mean.mean()
    )
    pooled = np.average(control.mean_mcherry_intensity_mean, weights=control.n_accepted_neurons)
    assert row.mean_mcherry_intensity_equal_well_mean != pytest.approx(pooled)
    p = pairs[(pairs.pair == "E05/F05") & (pairs.day == 8)].iloc[0]
    assert p.mean_mcherry_intensity_difference == pytest.approx(
        p.mean_mcherry_intensity_experimental - p.mean_mcherry_intensity_control
    )
    assert row.n_wells == 3 and row.n_pairs == 3 and row.n_neurons == 4
    assert metadata["neurons_are_independent_replicates"] is False
    assert metadata["survival_analysis_performed"] is False
    assert warnings


def test_missing_statuses_stay_distinct_and_do_not_become_death(example):
    tables, _, warnings = build_tables(example / "analysis_inputs.json")
    track = tables["neuron_longitudinal"].query("neuron_id == 'I05_N099'")
    assert len(track) == 9
    assert track.total_mcherry_intensity.isna().all()
    assert set(track.cell_fate) == {"not_classified"}
    last = track[track.day == 39].iloc[0]
    assert last.reason == "expected_visit_not_supplied"
    assert "confirmed_death" not in track.cell_fate.values
    assert len(set(track.observation_status)) == 6
    assert any("Day 39" in item for item in warnings)
    assert tables["qc_summary"].n_observations.sum() == len(tables["neuron_longitudinal"])


def test_day8_baseline_is_same_neuron_and_percent_is_explicit(example):
    tables, _, _ = build_tables(example / "analysis_inputs.json")
    track = tables["neuron_longitudinal"].query("neuron_id == 'E05_N001'").set_index("day")
    baseline = track.loc[8, "mean_mcherry_intensity"]
    assert track.loc[12, "mean_mcherry_intensity_change_from_day8"] == pytest.approx(
        track.loc[12, "mean_mcherry_intensity"] - baseline
    )
    assert track.loc[8, "mean_mcherry_intensity_pct_change_from_day8"] == 0


@pytest.mark.parametrize(
    "file",
    [
        "export/accepted_neuron_metrics.csv",
        "workspace/review/ui.js",
        "workspace/review/config.json",
        "curated/E05_N001/parameters.json",
        "curated/E05_N001/small_fixture.npz",
        "synthetic_test_review.json",
        "export/analysis_scope.json",
        "export/review_verdicts.json",
    ],
)
def test_stale_inputs_rejected_without_analysis_outputs(bundle, tmp_path, file):
    path = bundle / file
    path.write_bytes(path.read_bytes() + b" altered")
    out = tmp_path / "must-not-exist"
    with pytest.raises((ValueError, OSError, KeyError)):
        analyze(bundle / "analysis_inputs.json", out)
    assert not out.exists()


@pytest.mark.parametrize(
    "mutation", ["condition", "duplicate", "accepted_pending", "fate", "source", "missing_accepted"]
)
def test_invalid_cohort_rejected(bundle, mutation):
    path = bundle / "cohort_status.csv"
    rows = csv_rows(path)
    if mutation == "condition":
        rows[0]["condition"] = "TMEM106B"
    elif mutation == "duplicate":
        rows.append(rows[0].copy())
    elif mutation == "accepted_pending":
        rows[0]["observation_status"] = "pending_review"
        rows[0]["reason"] = "not approved"
    elif mutation == "fate":
        rows[0]["cell_fate"] = "lost_to_followup"
    elif mutation == "source":
        rows[0]["source_reference"] = ""
    else:
        rows.pop(0)
    write_csv(path, rows)
    with pytest.raises(ValueError):
        build_tables(bundle / "analysis_inputs.json")


def test_duplicate_export_bundles_rejected(bundle):
    path = bundle / "analysis_inputs.json"
    manifest = read_json(path)
    manifest["bundles"] *= 2
    write_json(path, manifest)
    with pytest.raises(ValueError, match="Duplicate observation"):
        build_tables(path)


def test_synthetic_cannot_be_relabelled_as_real(bundle):
    path = bundle / "analysis_inputs.json"
    manifest = read_json(path)
    manifest["evidence_type"] = "REAL_ACCEPTED"
    manifest["measurement_units"]["intensity"] = "ADU"
    write_json(path, manifest)
    with pytest.raises(ValueError, match="Synthetic reviewer"):
        build_tables(path)


def test_known_exclusion_cannot_be_promoted(bundle):
    path = bundle / "decision_policy.json"
    policy = read_json(path)
    policy["excluded_neuron_ids"]["E05_N001"] = "Synthetic known exclusion"
    write_json(path, policy)
    with pytest.raises(ValueError, match="Known exclusion"):
        build_tables(bundle / "analysis_inputs.json")


def test_technical_measurements_rejected_even_when_csv_has_plausible_values(bundle):
    path = bundle / "export/accepted_neuron_metrics.csv"
    rows = csv_rows(path)
    rows[0]["review"] = "TECHNICAL_RETAINED"
    write_csv(path, rows)
    with pytest.raises(ValueError, match="Technical/unreviewed"):
        build_tables(bundle / "analysis_inputs.json")


@pytest.mark.parametrize(
    "field,value",
    [
        ("total_mcherry_intensity", "nan"),
        ("puncta_count", "1.5"),
        ("phenotype_roi_area", "0"),
        ("diffuse_mcherry_integrated_intensity", "-1"),
        ("punctate_mcherry_integrated_intensity", "inf"),
        ("total_mcherry_intensity", "5"),
    ],
)
def test_invalid_quantities_rejected(field, value):
    row = {
        "phenotype_roi_area": "20",
        "total_mcherry_intensity": "100",
        "punctate_mcherry_integrated_intensity": "30",
        "diffuse_mcherry_integrated_intensity": "70",
        "puncta_count": "1",
    }
    row[field] = value
    with pytest.raises(ValueError):
        quantity_values(row)


def test_failed_qc_cannot_be_overridden_by_unchanged_export(bundle):
    # Rebuild evidence to make a consistent, reviewed synthetic source with False QC.
    path = bundle / "curated/E05_N001/fixture_tracks.csv"
    rows = csv_rows(path)
    rows[0]["tracking_valid"] = "False"
    write_csv(path, rows)
    builder = source_script("build_review_workspace.py")
    builder.build(bundle / "curated", bundle / "config.json", bundle / "workspace-new")
    review_path = bundle / "synthetic_test_review.json"
    old = read_json(review_path)
    fresh = read_json(bundle / "workspace-new/review/manual_review_template.json")
    old["workspace_sha256"] = fresh["workspace_sha256"]
    for track, fresh_track in zip(old["tracks"], fresh["tracks"], strict=True):
        track["evidence_sha256"] = fresh_track["evidence_sha256"]
    write_json(review_path, old)
    # Actual exporter should refuse this source, and the loader cannot use old bytes.
    status = source_script("export_reviewed_metrics.py").export(
        bundle / "curated",
        review_path,
        bundle / "config.json",
        bundle / "blocked-export",
        workspace=bundle / "workspace-new",
    )
    assert status == 2
    assert not (bundle / "blocked-export/accepted_neuron_metrics.csv").exists()
    with pytest.raises(ValueError):
        build_tables(bundle / "analysis_inputs.json")


def test_analysis_output_hashes_and_nonoverwrite(bundle, tmp_path):
    out = tmp_path / "analysis"
    analyze(bundle / "analysis_inputs.json", out)
    tables, _, _ = verify_analysis(out)
    assert len(tables["matched_pair_day"]) == 27
    with pytest.raises(FileExistsError):
        analyze(bundle / "analysis_inputs.json", out)
    file = out / "well_day_summary.csv"
    file.write_text(file.read_text().replace("E05", "F05", 1))
    with pytest.raises(ValueError, match="fingerprint"):
        verify_analysis(out)


def test_one_neuron_sd_is_undefined(example):
    tables, _, _ = build_tables(example / "analysis_inputs.json")
    rows = tables["well_day_summary"].query("well == 'F05'")
    assert rows.mean_mcherry_intensity_within_well_sd.isna().all()


def test_empty_bundles_fail_before_graphs(bundle):
    path = bundle / "analysis_inputs.json"
    manifest = read_json(path)
    manifest["bundles"] = []
    write_json(path, manifest)
    with pytest.raises(ValueError, match="No accepted"):
        build_tables(path)


def test_example_declares_all_nine_expected_visits(example):
    data = read_json(example / "analysis_inputs.json")
    assert data["evidence_type"] == "SYNTHETIC_EXAMPLE"
    assert len(DAYS) == 9
    assert "AUTOMATED" in read_json(example / "synthetic_test_review.json")["reviewer"]


def rebind_export(root, excluded=()):
    source_script("build_review_workspace.py").build(
        root / "curated", root / "config.json", root / "fresh-workspace"
    )
    fresh = read_json(root / "fresh-workspace/review/manual_review_template.json")
    review = read_json(root / "synthetic_test_review.json")
    fresh.update(reviewer=review["reviewer"], reviewed_at=review["reviewed_at"])
    for track in fresh["tracks"]:
        track["track_decision"] = "exclude" if track["neuron_id"] in excluded else "accept"
        for visit in track["visits"]:
            for field in ("identity_488", "roi_purity_488", "phenotype_qc_561"):
                visit[field] = "pass"
    write_json(root / "fresh-review.json", fresh)
    assert (
        source_script("export_reviewed_metrics.py").export(
            root / "curated",
            root / "fresh-review.json",
            root / "config.json",
            root / "fresh-export",
            workspace=root / "fresh-workspace",
        )
        == 0
    )
    manifest = read_json(root / "analysis_inputs.json")
    manifest["bundles"][0].update(
        export="fresh-export", reviews="fresh-review.json", workspace="fresh-workspace"
    )
    write_json(root / "analysis_inputs.json", manifest)
    roster = csv_rows(root / "cohort_status.csv")
    for row in roster:
        if row["neuron_id"] in excluded:
            row.update(observation_status="excluded_qc", reason="synthetic exclusion")
    write_csv(root / "cohort_status.csv", roster)


def test_zero_denominators_are_missing_not_infinite(bundle):
    folder = bundle / "curated/E05_N001"
    path = folder / "metrics.csv"
    rows = csv_rows(path)
    for row in rows:
        for field in (
            "total_mcherry_intensity",
            "punctate_mcherry_integrated_intensity",
            "diffuse_mcherry_integrated_intensity",
            "puncta_count",
        ):
            row[field] = "0"
    write_csv(path, rows)
    rebind_export(bundle)
    tables, _, _ = build_tables(bundle / "analysis_inputs.json")
    track = tables["neuron_longitudinal"].query("neuron_id == 'E05_N001'")
    assert track.diffuse_fraction.isna().all()
    assert track.total_mcherry_intensity_pct_change_from_day8.isna().all()


def test_partial_matched_cohort_retains_blanks_and_warnings(bundle):
    rebind_export(bundle, excluded=("I05_N001", "J05_N001", "M05_N001", "N05_N001"))
    tables, _, warnings = build_tables(bundle / "analysis_inputs.json")
    pairs = tables["matched_pair_day"]
    assert pairs.pair_available.sum() == 9
    assert pairs[~pairs.pair_available].mean_mcherry_intensity_difference.isna().all()
    assert all(tables["condition_day_summary"].n_pairs == 1)
    assert any("1/3" in message for message in warnings)


def test_unpaired_only_input_is_rejected(bundle):
    rebind_export(bundle, excluded=("F05_N001", "J05_N001", "N05_N001"))
    with pytest.raises(ValueError, match="no paired visit"):
        build_tables(bundle / "analysis_inputs.json")


@pytest.mark.parametrize(
    "mutation", ["empty_core", "wrong_area", "core_outside_roi", "adaptive_empty"]
)
def test_invalid_geometry_rejected_before_analysis(bundle, mutation):
    from tmem_align.audit_v1.matched_analysis import check_geometry

    folder = bundle / "curated/E05_N001"
    with np.load(folder / "small_fixture.npz", allow_pickle=False) as loaded:
        data = {key: loaded[key] for key in loaded.files}
    if mutation == "empty_core":
        data["identity_core"][:] = False
    elif mutation == "wrong_area":
        data["phenotype_roi"][0, 0] = True
    elif mutation == "core_outside_roi":
        data["identity_core"][0, 0] = True
    else:
        data["adaptive_masks"][0] = False
    np.savez_compressed(folder / "small_fixture.npz", **data)
    with pytest.raises(ValueError):
        check_geometry(folder, csv_rows(folder / "metrics.csv"))


@pytest.mark.parametrize(
    "mutation", ["unresolved", "missing_n012", "technical", "pending", "missing_evidence"]
)
def test_real_policy_rejects_unresolved_or_nonbiological_candidates(bundle, monkeypatch, mutation):
    # Unit-test the real policy branch with a stubbed bundle loader. No real review is created.
    from tmem_align.audit_v1 import matched_analysis as module

    released = csv_rows(bundle / "export/accepted_neuron_metrics.csv")
    monkeypatch.setattr(module, "load_bundle", lambda *args: released)
    manifest = read_json(bundle / "analysis_inputs.json")
    manifest.update(
        evidence_type="REAL_ACCEPTED", measurement_units={"intensity": "ADU", "area": "px2"}
    )
    write_json(bundle / "analysis_inputs.json", manifest)
    policy = {
        "schema_version": "tmem.analysis_decisions.v1",
        "evidence_type": "REAL_ACCEPTED",
        "excluded_neuron_ids": {
            "F05_N025": "unit test",
            "N05_N011": "unit test",
            "N05_N012": "unit test",
        },
        "pending_identity_resolution": [],
        "technical_only_neuron_ids": ["J05_N015"],
        "pending_neuron_ids": [],
        "packet_exclusions": {
            "N012": {"neuron_id": "N05_N012", "source_reference": "UNIT TEST ONLY"}
        },
        "evidence_files": [],
    }
    if mutation == "unresolved":
        policy["pending_identity_resolution"] = ["exact packet ID"]
    elif mutation == "missing_n012":
        policy["packet_exclusions"] = {}
    elif mutation == "technical":
        policy["technical_only_neuron_ids"].append("J05_N001")
    elif mutation == "pending":
        policy["pending_neuron_ids"].append("N05_N001")
    write_json(bundle / "decision_policy.json", policy)
    with pytest.raises(ValueError):
        module.load_inputs(bundle / "analysis_inputs.json")
