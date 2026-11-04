"""Publication controls use invented identifiers, never genuine private artifacts."""

import importlib.util
import json
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "publication_audit", Path(__file__).resolve().parents[2] / "scripts/audit_publication.py"
)
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


@pytest.mark.parametrize(
    "name",
    [
        "data/image.tif",
        "diagnostic.npy",
        "archive.zip",
        "run.log",
        "review-local/index.html",
        ".venv-local/config.txt",
        "private-review/evidence.json",
        "review-workspace/index.html",
    ],
)
def test_generated_private_paths_rejected(name):
    assert audit.inspect_blob(name, b"control text")


def test_annotations_not_public_just_because_small():
    assert audit.inspect_blob(
        "docs/review.json",
        json.dumps({"schema_version": "tmem.diagnostic_review.v1", "reviewer": ""}).encode(),
    )
    assert audit.inspect_blob("docs/review.csv", b"reviewer,trace_manifest_sha256\n,\n")


def test_absolute_private_paths_detected():
    path = "/" + "Users" + "/" + "control_researcher" + "/experiment"
    assert audit.inspect_blob("docs/guide.md", path.encode())


def test_secret_pattern_and_binary_rejected():
    token = "gh" + "p_" + "X" * 30
    assert audit.inspect_blob("config.txt", token.encode())
    assert audit.inspect_blob("plain.txt", b"control\0binary")


def test_safe_source_template_and_aggregate_receipt_allowed():
    assert not audit.inspect_blob("scripts/tool.py", b'print("488 only; no automatic approval")\n')
    assert not audit.inspect_blob(
        "docs/aggregate.json", json.dumps({"accepted": 0, "valid_visits": 91}).encode()
    )


def test_nested_final_reviewer_records_and_duplicate_keys_blocked():
    assert audit.inspect_blob(
        "docs/record.json", json.dumps({"nested": [{"reviewer": "CONTROL"}]}).encode()
    )
    assert audit.inspect_blob(
        "docs/record.json", json.dumps({"schema_version": "tmem.manual_review.v2"}).encode()
    )
    assert audit.inspect_blob("docs/record.json", b'{"reviewer":"CONTROL","reviewer":""}')
    assert audit.inspect_blob(
        "docs/readiness.json",
        json.dumps({"schema_version": "tmem.review_reconciliation.v1"}).encode(),
    )


@pytest.mark.parametrize(
    "schema", ["tmem.acquisition_inventory.v1", "tmem.acquisition_declarations.v1"]
)
def test_private_acquisition_records_not_publishable(schema):
    assert audit.inspect_blob(
        "docs/inventory.json", json.dumps({"schema_version": schema}).encode()
    )


def test_path_free_acquisition_summary_publishable():
    assert not audit.inspect_blob(
        "docs/coverage.json",
        json.dumps(
            {"schema_version": "tmem.source_coverage_summary.v1", "assemblies_verified_here": 0}
        ).encode(),
    )


def test_actual_fov_private_manifest_not_publishable():
    assert audit.inspect_blob(
        "docs/figures.json",
        json.dumps(
            {"schema_version": "tmem.actual_fov_figures.v1", "real_accepted_ids": []}
        ).encode(),
    )


def test_private_pi_presentation_manifest_not_publishable():
    assert audit.inspect_blob(
        "docs/presentation.json",
        json.dumps({"schema_version": "tmem.pi_presentation.v1", "accepted_ids": []}).encode(),
    )


@pytest.mark.parametrize(
    "schema",
    [
        "tmem.full_plate_audit.v1",
        "tmem.well_checkpoint.v1",
        "tmem.well_checkpoint.aggregate.v1",
        "tmem.example_curation.v1",
        "tmem.pi_presentation.v2",
    ],
)
def test_new_private_receipts_not_publishable(schema):
    assert audit.inspect_blob("docs/record.json", json.dumps({"schema_version": schema}).encode())
