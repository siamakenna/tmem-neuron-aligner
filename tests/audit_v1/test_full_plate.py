"""SOFTWARE_FIXTURE_ONLY contracts and receipt controls, no microscopy."""

import csv
from copy import deepcopy
from pathlib import Path

import pytest

from tmem_align.audit_v1.full_plate import (
    audit_run,
    private_output,
    validate_contract,
    validate_curation,
)


@pytest.fixture
def contract():
    return {
        "schema_version": "tmem.dataset_contract.v2",
        "experiment_id": "SOFTWARE_FIXTURE_ONLY",
        "plate_id": "constructed",
        "plate_shape": [2, 3],
        "wells": ["A01", "B02"],
        "visits": [1, 4],
        "sites": ["s1", "s2"],
        "channels": {"alignment": "structural", "phenotype": "reporter"},
        "expected_axes": "CYX",
        "expected_dtype": "uint16",
        "expected_shape": [2, 8, 9],
        "reporter_wells": ["A01"],
        "missing_visit_policy": "record_missing",
        "coordinate_frame": "fixture",
        "calibration_refs": None,
        "geometry_status": "COVERAGE_UNRESOLVED",
    }


def table(root, key, fields, rows):
    with (root / ("all_wells_" + key + ".csv")).open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def selection(root, c):
    from tests.audit_v1.test_plate_preflight import valid_tables

    table(
        root,
        "selected_files",
        ["well", "day", "condition", "path", "file_name", "mcherry_analysis_valid"],
        valid_tables(c)["selected_files"],
    )


def test_second_constructed_dataset(contract):
    assert validate_contract(contract)["sites"] == ["s1", "s2"]


@pytest.mark.parametrize(
    "key,value",
    [
        ("visits", [True, 4]),
        ("visits", [4, 1]),
        ("wells", ["A01", "A01"]),
        ("wells", ["C01"]),
        ("sites", []),
        ("expected_shape", [True, 8, 9]),
        ("missing_visit_policy", "ignore"),
        ("channels", {"alignment": "561", "phenotype": "561"}),
        ("expected_axes", "CCX"),
    ],
)
def test_invalid_contract(contract, key, value):
    contract[key] = value
    with pytest.raises(ValueError):
        validate_contract(contract)


def test_pending_not_zero_and_source_bound(tmp_path, contract):
    selection(tmp_path, contract)
    r = audit_run(tmp_path, contract, "RUNNING")
    assert r["status"] == "PENDING" and r["qc_rows"] == 0
    assert all(w["pass_fraction"] is None for w in r["by_well"])
    assert r["expected_visits"] == 4 and len(r["source_sha256"]) == 1
    assert r["accepted_ids"] == [] and not r["scientific_inference_ready"]


def test_complete_failure_mixture_and_firewall(tmp_path, contract):
    from tests.audit_v1.test_plate_preflight import valid_tables
    from tmem_align.audit_v1.full_plate import TABLE_COLUMNS

    for key, rows in valid_tables(contract, ["B02"]).items():
        table(tmp_path, key, TABLE_COLUMNS[key], rows)
    r = audit_run(tmp_path, contract)
    assert r["status"] == "FINAL_TABLES_PRESENT" and r["by_well"][0]["pass_fraction"] == 0.5
    assert r["by_well"][1]["status"] == "FAILED"
    table(tmp_path, "mcherry_measurements", TABLE_COLUMNS["mcherry_measurements"], [])
    assert audit_run(tmp_path, contract)["status"] == "INCONSISTENT"
    table(
        tmp_path,
        "mcherry_measurements",
        TABLE_COLUMNS["mcherry_measurements"],
        [{**valid_tables(contract)["mcherry_measurements"][0], "well": "B02"}],
    )
    assert audit_run(tmp_path, contract)["status"] == "INCONSISTENT"


def test_selection_duplicates_and_symlink(tmp_path, contract):
    selection(tmp_path, contract)
    p = tmp_path / "all_wells_selected_files.csv"
    with p.open("a") as f:
        f.write("A01,1,True\n")
    assert audit_run(tmp_path, contract)["issues"]
    alias = tmp_path / "alias"
    alias.symlink_to(p)
    from tmem_align.audit_v1.full_plate import plain

    with pytest.raises(ValueError):
        plain(alias)
    with pytest.raises(ValueError):
        private_output(Path(__file__).resolve().parents[2] / "NEVER_CREATED")


def curation():
    roles = ["longitudinal", "segmentation", "tracking", "ownership_ambiguous"]
    m = {"sources": [{"neuron_id": r, "trace_manifest_sha256": r} for r in roles]}
    v = {
        "schema_version": "tmem.example_curation.v1",
        "figure_manifest_sha256": "fixture",
        "selections": {
            r: {
                "neuron_id": r,
                "trace_manifest_sha256": r,
                "channel": "488",
                "status": "AMBIGUOUS",
                "rationale": "Constructed",
                "source_refs": ["SOFTWARE_FIXTURE_ONLY"],
            }
            for r in roles
        },
    }
    return v, m


@pytest.mark.parametrize("kind", ["stale", "confirmed", "561", "duplicate", "missing"])
def test_curation_fail_closed(kind):
    v, m = curation()
    assert validate_curation(deepcopy(v), m, "fixture")
    if kind == "stale":
        v["figure_manifest_sha256"] = "changed"
    elif kind == "missing":
        del v["selections"]["tracking"]
    elif kind == "duplicate":
        v["selections"]["tracking"] = v["selections"]["longitudinal"]
    else:
        v["selections"]["tracking"]["status" if kind == "confirmed" else "channel"] = (
            "REVIEW_CONFIRMED" if kind == "confirmed" else "561"
        )
    with pytest.raises(ValueError):
        validate_curation(v, m, "fixture")
