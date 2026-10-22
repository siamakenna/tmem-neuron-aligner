"""Bind manual review to exact curated evidence and block unreviewed exports.

The gate records human decisions. It does not infer identity, choose an ROI from
561, or treat an automated soma-screen PASS as manual approval. Identity and ROI
purity are reviewed using 488; phenotype QC is a separate 561 assessment.
"""
from __future__ import annotations

import csv
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
from typing import Any

SCHEMA_VERSION = "tmem.manual_review.v1"
RENDERED_SCHEMA_VERSION = "tmem.manual_review.v2"
MANIFEST_VERSION = "tmem.review_evidence.v1"
RENDER_MANIFEST_VERSION = "tmem.rendered_review.v1"
RENDER_BINDING_FILES = frozenset({
    "render_manifest.json", "review_binding.js", "manual_review_template.json",
    "pending_review_verdicts.json", "manual_review.json",
})
FAILURE_CATEGORIES = frozenset({
    "", "expected_handled", "new_bug", "new_QC_condition", "scientific_limitation",
    "visualization_only_issue",
})
DAYS = (8, 12, 16, 20, 25, 29, 32, 36, 39)
EVIDENCE_FILES = (
    "small_fixture.npz", "metrics.csv", "parameters.json", "luts.json", "fixture_tracks.csv",
)
CRITERIA = ("identity_488", "roi_purity_488", "phenotype_qc_561")
CRITERION_STATES = {"pass", "fail", "not_reviewed"}
TRACK_DECISIONS = {"accept", "exclude", "not_reviewed"}


def _neuron_id(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-P]\d{2}_N\d+", value):
        raise ValueError("neuron_id must use the project WELL_Nnumber convention")
    return value


def _day(value: Any) -> int:
    if type(value) is int:
        return value
    if isinstance(value, str) and value.isdecimal():
        return int(value)
    raise ValueError("Review day must be an integer or decimal integer string")


def _digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024**2), b""):
            result.update(block)
    return result.hexdigest()


def _check_csv(path: Path, neuron_id: str, well: str) -> None:
    with path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        fields = set(reader.fieldnames or [])
        if not {"neuron_id", "well", "day"}.issubset(fields):
            raise ValueError(f"{path.name}: require neuron_id, well and day columns")
        rows = list(reader)
    if [_day(row["day"]) for row in rows] != list(DAYS):
        raise ValueError(f"{path.name}: require exactly the nine chronological visits")
    if any(row["neuron_id"] != neuron_id or row["well"] != well for row in rows):
        raise ValueError(f"{path.name}: contains another neuron or well")


def evidence_manifest(curated_root: str | Path, neuron_ids: list[str]) -> list[dict[str, Any]]:
    """Hash the exact fixture, metrics, geometry/parameters and display evidence.

    File paths within the manifest are relative, so copying unchanged evidence
    does not invalidate it. Any changed evidence bytes do invalidate old review.
    The caller must recompute this manifest immediately before accepted export.
    """
    root = Path(curated_root).resolve()
    ids = [_neuron_id(value) for value in neuron_ids]
    if not ids or len(ids) != len(set(ids)):
        raise ValueError("Supply one or more distinct neuron IDs")
    output = []
    for neuron_id in ids:
        folder = root / neuron_id
        well = neuron_id.split("_", 1)[0]
        files = {}
        for filename in EVIDENCE_FILES:
            path = folder / filename
            if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root):
                raise ValueError(f"Missing or nonlocal regular evidence file: {neuron_id}/{filename}")
            files[filename] = {"sha256": _digest(path), "size_bytes": path.stat().st_size}
        panels=[folder/f'day_{day:02d}'/'four_panel.png' for day in DAYS]
        if any(path.exists() for path in panels):
            for path in panels:
                if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root):
                    raise ValueError('Existing phenotype-panel evidence must contain all nine regular files')
                files[str(path.relative_to(folder))]={"sha256":_digest(path),"size_bytes":path.stat().st_size}
        _check_csv(folder / "metrics.csv", neuron_id, well)
        _check_csv(folder / "fixture_tracks.csv", neuron_id, well)
        record = dict(manifest_version=MANIFEST_VERSION, neuron_id=neuron_id, well=well,
                      days=list(DAYS), files=files,
                      identity_source="488_only", phenotype_source="561_after_identity_and_roi")
        canonical = json.dumps(record, sort_keys=True, separators=(",", ":")).encode("utf-8")
        record["evidence_sha256"] = hashlib.sha256(canonical).hexdigest()
        output.append(record)
    return output


def _manifest_records(manifest: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    if not isinstance(manifest, list) or not manifest:
        raise ValueError("Evidence manifest must be a nonempty list")
    output = {}
    for record in manifest:
        if not isinstance(record, dict):
            raise ValueError("Every evidence manifest record must be an object")
        neuron_id = _neuron_id(record.get("neuron_id"))
        if neuron_id in output:
            raise ValueError("Duplicate track in evidence manifest")
        if record.get("well") != neuron_id.split("_", 1)[0]:
            raise ValueError("Evidence well and neuron ID disagree")
        if record.get("days") != list(DAYS):
            raise ValueError("Evidence manifest must contain the nine expected visits")
        if not isinstance(record.get("evidence_sha256"), str) or not re.fullmatch(
            r"[0-9a-f]{64}", record["evidence_sha256"]
        ):
            raise ValueError("Evidence fingerprint must be a SHA256 hex string")
        output[neuron_id] = record
    return output


def make_review_template(
    manifest: list[dict[str, Any]], *, workspace_sha256: str | None = None,
) -> dict[str, Any]:
    """Create an explicitly unreviewed document; never manufacture approval."""
    records = _manifest_records(manifest)
    if workspace_sha256 is not None and not re.fullmatch(r"[0-9a-f]{64}", workspace_sha256):
        raise ValueError("Rendered workspace fingerprint must be a SHA256 hex string")
    document = dict(schema_version=RENDERED_SCHEMA_VERSION if workspace_sha256 else SCHEMA_VERSION,
                reviewer="", reviewed_at="",
                tracks=[dict(neuron_id=record["neuron_id"],
                             evidence_sha256=record["evidence_sha256"],
                             track_decision="not_reviewed", notes="",
                             visits=[dict(day=day, **{criterion: "not_reviewed" for criterion in CRITERIA})
                                     for day in DAYS]) for record in records.values()])
    if workspace_sha256 is not None:
        document["workspace_sha256"] = workspace_sha256
        for track in document["tracks"]:
            for visit in track["visits"]:
                visit.update(notes="", failure_category="")
    return document


def review_directory(workspace: str | Path) -> Path:
    """Accept either a direct portable review folder or its workspace parent."""
    supplied = Path(workspace)
    if supplied.is_symlink():
        raise ValueError("Review workspace must be a regular local directory")
    if (supplied / "review").is_dir():
        supplied = supplied / "review"
    if supplied.is_symlink() or not supplied.is_dir():
        raise ValueError("Review workspace directory is missing or nonlocal")
    return supplied.resolve()


def _local_regular(root: Path, path: Path) -> None:
    if not path.is_file() or not path.resolve().is_relative_to(root):
        raise ValueError(f"Missing or nonlocal review asset: {path.name}")
    relative = path.relative_to(root)
    if any((root / Path(*relative.parts[:i])).is_symlink()
           for i in range(1, len(relative.parts) + 1)):
        raise ValueError(f"Review assets cannot use symlinks: {relative}")


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, allow_nan=False) + "\n").encode("utf-8")


def review_binding_javascript(template: dict[str, Any]) -> bytes:
    """The one unhashed script is checked against these deterministic bytes."""
    encoded = json.dumps(template, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return ("window.TMEM_REVIEW_BINDING = " + encoded.replace("<", "\\u003c") + ";\n").encode("utf-8")


def rendered_manifest(
    workspace: str | Path, source_manifest: list[dict[str, Any]],
) -> dict[str, Any]:
    """Bind every displayed asset and its renderer, without a self-referential hash.

    index.html, ui.js and review_data.js contain no binding fingerprint. The
    generated review_binding.js carries the template and is independently
    re-derived during verification. Its bytes cannot silently diverge from the
    manifest. All other regular files in the review tree form the render digest.
    """
    root = review_directory(workspace)
    records = _manifest_records(source_manifest)
    required = {"index.html", "ui.js", "review_data.js", "config.json", "lut_clipping.csv"}
    for neuron_id in records:
        required.add(f"{neuron_id}/luts.json")
        for day in DAYS:
            for kind in ("identity", "display", "phenotype"):
                required.add(f"{neuron_id}/day_{day:02d}_{kind}.png")
    for filename in required:
        _local_regular(root, root / filename)
    files = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"Review tree cannot contain symlinks: {path.relative_to(root)}")
        if not path.is_file():
            continue
        name = path.relative_to(root).as_posix()
        if name in RENDER_BINDING_FILES or path.name == '.DS_Store':
            continue
        _local_regular(root, path)
        files[name] = {"sha256": _digest(path), "size_bytes": path.stat().st_size}
    record = dict(
        schema_version=RENDER_MANIFEST_VERSION,
        review_schema_version=RENDERED_SCHEMA_VERSION,
        source_evidence=[{"neuron_id": item["neuron_id"], "evidence_sha256": item["evidence_sha256"]}
                         for item in records.values()],
        files=files,
    )
    canonical = json.dumps(record, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    record["workspace_sha256"] = hashlib.sha256(canonical).hexdigest()
    return record


def finalize_review_workspace(
    workspace: str | Path, source_manifest: list[dict[str, Any]],
    known_exclusions: dict[str, str],
) -> dict[str, Any]:
    """Finalize a newly rendered workspace and write a blank, v2-bound review."""
    root = review_directory(workspace)
    outputs = ("render_manifest.json", "review_binding.js", "manual_review_template.json",
               "pending_review_verdicts.json")
    if any((root / name).exists() for name in outputs):
        raise FileExistsError("Finalize only a new workspace; existing review evidence is preserved")
    render = rendered_manifest(root, source_manifest)
    template = make_review_template(source_manifest, workspace_sha256=render["workspace_sha256"])
    verdict = evaluate_review(template, source_manifest, known_exclusions,
                              workspace_sha256=render["workspace_sha256"])
    (root / "render_manifest.json").write_bytes(_json_bytes(render))
    (root / "manual_review_template.json").write_bytes(_json_bytes(template))
    (root / "pending_review_verdicts.json").write_bytes(_json_bytes(verdict))
    (root / "review_binding.js").write_bytes(review_binding_javascript(template))
    return dict(render_manifest=render, template=template, verdict=verdict)


def verify_review_workspace(
    workspace: str | Path, source_manifest: list[dict[str, Any]],
    known_exclusions: dict[str, str],
) -> dict[str, Any]:
    """Recompute the exact shown evidence immediately before metric export."""
    root = review_directory(workspace)
    for name in ("render_manifest.json", "review_binding.js", "manual_review_template.json",
                 "pending_review_verdicts.json"):
        _local_regular(root, root / name)
    recorded = json.loads((root / "render_manifest.json").read_text())
    actual = rendered_manifest(root, source_manifest)
    if recorded != actual:
        raise ValueError("Rendered review evidence is missing, changed or stale")
    template = make_review_template(source_manifest, workspace_sha256=actual["workspace_sha256"])
    if (root / "review_binding.js").read_bytes() != review_binding_javascript(template):
        raise ValueError("Rendered review binding script is changed or stale")
    if (root / "manual_review_template.json").read_bytes() != _json_bytes(template):
        raise ValueError("Rendered review template is changed or stale")
    verdict = evaluate_review(template, source_manifest, known_exclusions,
                              workspace_sha256=actual["workspace_sha256"])
    if (root / "pending_review_verdicts.json").read_bytes() != _json_bytes(verdict):
        raise ValueError("Pending review verdicts are changed or stale")
    return actual


def _review_identity_reasons(review: dict[str, Any]) -> list[str]:
    reasons = []
    reviewer = review.get("reviewer", "")
    if not isinstance(reviewer, str) or not reviewer.strip():
        reasons.append("reviewer_missing")
    timestamp = review.get("reviewed_at", "")
    try:
        if not isinstance(timestamp, str) or not timestamp.strip():
            raise ValueError("Missing timestamp")
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("Timestamp must include timezone")
    except (ValueError, TypeError, OverflowError):
        reasons.append("review_timestamp_missing_invalid_or_timezone_naive")
    return reasons


def evaluate_review(
    review: dict[str, Any] | None,
    manifest: list[dict[str, Any]],
    known_exclusions: dict[str, str],
    *, workspace_sha256: str | None = None,
) -> dict[str, Any]:
    """Return eligibility only when the exact evidence has nine explicit passes.

    Missing decisions are ordinary blocked verdicts. Malformed documents,
    duplicate visits/tracks, unknown tracks/days or invalid state strings raise
    ValueError. Exclusions come from trusted caller policy and cannot be removed
    or overridden by fields in a review document.
    """
    records = _manifest_records(manifest)
    if not isinstance(known_exclusions, dict) or any(
        not isinstance(key, str) or not isinstance(value, str) or not value.strip()
        for key, value in known_exclusions.items()
    ):
        raise ValueError("known_exclusions must map neuron IDs to nonempty reasons")
    if review is None:
        review = {}
    if not isinstance(review, dict):
        raise ValueError("Review document must be an object")
    expected_schema = RENDERED_SCHEMA_VERSION if workspace_sha256 is not None else SCHEMA_VERSION
    if workspace_sha256 is not None and not re.fullmatch(r"[0-9a-f]{64}", workspace_sha256):
        raise ValueError("Rendered workspace fingerprint must be a SHA256 hex string")
    if review.get("schema_version", expected_schema) != expected_schema:
        raise ValueError("Unsupported review schema version")
    tracks = review.get("tracks", [])
    if not isinstance(tracks, list):
        raise ValueError("Review tracks must be a list")
    submitted = {}
    for track in tracks:
        if not isinstance(track, dict):
            raise ValueError("Every reviewed track must be an object")
        neuron_id = _neuron_id(track.get("neuron_id"))
        if neuron_id not in records:
            raise ValueError(f"Review contains unknown track: {neuron_id}")
        if neuron_id in submitted:
            raise ValueError(f"Duplicate reviewed track: {neuron_id}")
        submitted[neuron_id] = track
    common_reasons = _review_identity_reasons(review)
    if workspace_sha256 is not None and review.get("workspace_sha256") != workspace_sha256:
        common_reasons.append("rendered_workspace_fingerprint_missing_or_stale")
    if "schema_version" not in review:
        common_reasons.append("review_schema_version_missing")
    verdicts = []
    for neuron_id, evidence in records.items():
        reasons = list(common_reasons)
        if neuron_id in known_exclusions:
            reasons.append("known_exclusion: " + known_exclusions[neuron_id])
        track = submitted.get(neuron_id)
        if track is None:
            reasons.append("track_review_missing")
        else:
            if track.get("evidence_sha256") != evidence["evidence_sha256"]:
                reasons.append("evidence_fingerprint_missing_or_stale")
            decision = track.get("track_decision", "not_reviewed")
            if not isinstance(decision, str) or decision not in TRACK_DECISIONS:
                raise ValueError(f"Invalid track decision for {neuron_id}")
            if decision != "accept":
                reasons.append("track_decision_" + decision)
            if not isinstance(track.get("notes", ""), str):
                raise ValueError("Track notes must be text")
            visits = track.get("visits", [])
            if not isinstance(visits, list):
                raise ValueError("Track visits must be a list")
            by_day = {}
            for visit in visits:
                if not isinstance(visit, dict):
                    raise ValueError("Every review visit must be an object")
                day = _day(visit.get("day"))
                if day not in DAYS:
                    raise ValueError(f"Unexpected review day: {day}")
                if day in by_day:
                    raise ValueError(f"Duplicate review day for {neuron_id}: {day}")
                by_day[day] = visit
            for day in DAYS:
                visit = by_day.get(day)
                if visit is None:
                    reasons.append(f"day_{day}_review_missing")
                    continue
                for criterion in CRITERIA:
                    state = visit.get(criterion, "not_reviewed")
                    if not isinstance(state, str) or state not in CRITERION_STATES:
                        raise ValueError(f"Invalid {criterion} state for {neuron_id} day {day}")
                    if state != "pass":
                        reasons.append(f"day_{day}_{criterion}_{state}")
                if workspace_sha256 is not None:
                    if not isinstance(visit.get("notes", ""), str):
                        raise ValueError("Visit notes must be text")
                    category = visit.get("failure_category", "")
                    if not isinstance(category, str) or category not in FAILURE_CATEGORIES:
                        raise ValueError("Invalid visit failure category")
        verdicts.append(dict(neuron_id=neuron_id, well=evidence["well"],
                             evidence_sha256=evidence["evidence_sha256"],
                             eligible=not reasons, reasons=reasons))
    result = dict(schema_version=expected_schema, tracks=verdicts,
                accepted_ids=[row["neuron_id"] for row in verdicts if row["eligible"]],
                reviewer=review.get("reviewer", ""), reviewed_at=review.get("reviewed_at", ""),
                identity_source="488_only", phenotype_source="561_after_identity_and_roi",
                biological_inference_approved=False)
    if workspace_sha256 is not None:
        result["workspace_sha256"] = workspace_sha256
    return result
