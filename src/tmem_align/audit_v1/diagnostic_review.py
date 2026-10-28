"""Private 488 review preparation/validation. Never an acceptance or export gate.

Only existing diagnostic outputs are read. No phenotype pixels or measurements
are loaded, no source is rewritten, and blank/uncertain decisions stay unresolved.
"""

from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import re
import struct
from datetime import datetime
from pathlib import Path

from .review_gate import DAYS

ROOT = Path(__file__).resolve().parents[3]
SCHEMA = "tmem.diagnostic_review.v1"
IDENTITY = {"", "yes", "no", "uncertain"}
OWNERSHIP = {"", "clear", "uncertain", "contaminated"}
DECISIONS = ("same_cell_yes_no_uncertain", "ROI_ownership_clear_uncertain_contaminated")
FIELDS = (
    "neuron_id",
    "day",
    "trace_manifest_sha256",
    "reviewer",
    *DECISIONS,
    "notes",
    "reviewed_at",
    "source_sha256",
    "display_sha256",
    "workspace_sha256",
    "source_channel",
)
EXCLUDED = {
    "F05_N025": "Historical multi-neuron ROI exclusion",
    "N05_N011": "Current source packet excluded; old favorable reference cannot override",
    "N05_N012": "Conservative N05_N012 block; N012 packet identity still needs exact source resolution",
    "E05_N006": "Unresolved historical identity/anchor issue",
    "F05_N007": "Unresolved historical ROI ownership",
}
TECHNICAL = {"J05_N015"}
FINAL_REQUIREMENTS = [
    "Existing v6 curated source evidence and rendered-workspace fingerprints",
    "Separate authentic final review including phenotype_qc_561 AFTER 488 identity/ROI gates",
    "All nine tracking, adaptive, global-registration and well-registration QC flags",
    "N012 packet full identity/source evidence and other pending identities resolved",
    "Historical exclusions and technical-only policy; accepted-export provenance",
    "Matched-well cohort and well-level replication; no neuron-level pseudoreplication",
]


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def sha(path):
    path = Path(path)
    before = path.stat()
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    after = path.stat()
    if (before.st_size, before.st_mtime_ns, before.st_ino) != (
        after.st_size,
        after.st_mtime_ns,
        after.st_ino,
    ):
        raise ValueError("EVIDENCE_STALE: source changed while hashing")
    return digest


def read_json(path):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate JSON key: " + key)
            result[key] = value
        return result

    def invalid(value):
        raise ValueError("Nonfinite JSON value: " + value)

    return json.loads(Path(path).read_text(), object_pairs_hook=pairs, parse_constant=invalid)


def regular(root, relative):
    root, rel = Path(root).resolve(), Path(relative)
    if rel.is_absolute() or ".." in rel.parts or "\\" in str(rel):
        raise ValueError("Unsafe evidence path")
    path = root / rel
    if (
        not path.is_file()
        or not path.resolve().is_relative_to(root)
        or any((root / Path(*rel.parts[:i])).is_symlink() for i in range(1, len(rel.parts) + 1))
    ):
        raise ValueError("Missing/linked evidence file: " + str(rel))
    return path


def output_path(path, protected=()):
    path = Path(path).absolute()
    if any(p.is_symlink() for p in [path, *path.parents]):
        raise ValueError("Outputs cannot use symlinks")
    path = path.resolve()
    if any(path.is_relative_to(Path(p).resolve()) for p in [ROOT, *protected]):
        raise ValueError("Private output must be outside repository and source directories")
    if path.exists():
        raise FileExistsError("Existing output preserved: " + str(path))
    return path


def evidence(benchmark, gallery):
    """Hash a bounded 488 subset, not registered stacks or all stage arrays."""
    benchmark, gallery = Path(benchmark).resolve(), Path(gallery).resolve()
    files, cases, visits = [], [], []

    def bind(root, name, kind, expected=None):
        path = regular(root, name)
        actual = sha(path)
        if expected is not None and actual != expected:
            raise ValueError("EVIDENCE_STALE: " + name)
        files.append({"root": kind, "path": name, "sha256": actual})
        return path, actual

    bp, benchmark_sha = bind(benchmark, "benchmark_summary.json", "benchmark")
    state = read_json(bp)
    rp, _ = bind(gallery, "panel_summary.json", "gallery")
    report = read_json(rp)
    if (
        report.get("benchmark_summary_sha256") != benchmark_sha
        or state.get("status") != "completed_pending_scientific_review"
        or state.get("master_and_configuration_unchanged") is not True
        or state.get("scientific_inference_ready") is not False
        or state.get("real_accepted_ids") != []
        or state.get("days") != list(DAYS)
    ):
        raise ValueError("EVIDENCE_STALE or incomplete diagnostic benchmark")
    reported = {c["neuron_id"]: c for c in report["cases"]}
    ids = state["selected_neuron_ids"]
    if len(ids) != len(set(ids)) or set(ids) != set(reported):
        raise ValueError("Duplicate/missing diagnostic case")
    for nid in ids:
        if not re.fullmatch(r"(?:E05|F05|I05|J05|M05|N05)_N\d{3}", nid):
            raise ValueError("Invalid neuron ID")
        prefix = "tracks/" + nid + "/"
        mp, manifest_sha = bind(
            benchmark, prefix + "manifest.json", "benchmark", reported[nid]["trace_manifest_sha256"]
        )
        manifest = read_json(mp)
        records = {r["stage"]: r for r in manifest["stages"]}

        def local(name, prefix=prefix, manifest=manifest):
            path, digest = bind(benchmark, prefix + name, "benchmark", manifest["files"][name])
            return path, digest

        sp, _ = local("summary.json")
        summary = read_json(sp)
        if (
            summary.get("real_accepted_ids") != []
            or summary.get("scientific_inference_ready") is not False
        ):
            raise ValueError("Diagnostics cannot assert biological acceptance")
        metadata_hashes = {}
        metadata = {}
        for name in (
            "crop_geometry.json",
            "tracking_comparison.json",
            "parameter_sensitivity.json",
        ):
            path, digest = local(name)
            metadata[name] = read_json(path)
            metadata_hashes[name] = digest
        if (
            metadata["tracking_comparison.json"].get("all_proposals_unadopted") is not True
            or metadata["parameter_sensitivity.json"].get("all_settings_unadopted") is not True
        ):
            raise ValueError("Adopted diagnostic geometry is not reviewable here")
        geometry = metadata["crop_geometry.json"]
        fixed_name, search_name = nid + "_488.png", nid + "_488_search_context.png"
        displays = {}
        for name in (fixed_name, search_name):
            path, digest = bind(gallery, name, "gallery")
            with path.open("rb") as stream:
                header = stream.read(24)
            shape = (1152, 1296) if name == fixed_name else (1206, 1350)
            if header[:8] != b"\x89PNG\r\n\x1a\n" or struct.unpack(">II", header[16:24]) != shape:
                raise ValueError(
                    "Unsupported contact-sheet layout; do not review miscropped pixels"
                )
            displays[name] = digest
        display_sha = hashlib.sha256(canonical(displays)).hexdigest()
        fixed_hashes = {}
        for name in ("primary_identity_core", "phenotype_roi_holes_filled"):
            if name in records:
                artifact = records[name]["artifacts"]["numeric"]
                _, fixed_hashes[name] = local(artifact["path"])
        case_visits = []
        for i, day in enumerate(DAYS):
            source = records[f"visit_{i:02d}_registered_488"]["artifacts"]["numeric"]
            _, image_sha = local(source["path"])
            qc = records.get(f"primary_segmentation_visit_{i:02d}_qc")
            if qc is None:
                qc = records[f"primary_segmentation_visit_{i:02d}_qc_failure"]
            local(qc["record_file"])
            details = qc["details"]
            valid = summary["valid_488_by_day"][str(day)]
            reasons = []
            if not valid:
                if details.get("tracking_valid_inherited") is False:
                    reasons.append("inherited_tracking_QC_failed")
                if details.get("reason"):
                    reasons.append(str(details["reason"]))
                if details.get("border_touch"):
                    reasons.append("segmentation_border_touch")
                ratio = details.get("reference_area_ratio")
                if ratio is not None and not 0.30 <= ratio <= 2.5:
                    reasons.append("mask_area_ratio_outside_0.30_to_2.5")
                if not reasons:
                    reasons.append(
                        "primary_488_QC_failed: inspect source stage parameters/centroid/area"
                    )
            row = {
                "neuron_id": nid,
                "day": day,
                "trace_manifest_sha256": manifest_sha,
                "source_sha256": hashlib.sha256(
                    canonical(
                        {
                            "image": image_sha,
                            "fixed": fixed_hashes,
                            "metadata": metadata_hashes,
                            "master": state["input_files"]["master"]["sha256"],
                            "configuration": state["configuration"]["sha256"],
                            "qc": qc["record_sha256"],
                        }
                    )
                ).hexdigest(),
                "display_sha256": display_sha,
                "automated_valid_488": valid,
                "inherited_tracking_valid": metadata["tracking_comparison.json"][
                    "results_by_radius"
                ]["60"][i]["historical_tracking_valid"],
                "automated_failure_reasons": reasons,
                "geometry": geometry[i],
            }
            case_visits.append(row)
            visits.append(row)
        cases.append(
            {
                "neuron_id": nid,
                "diagnostic_status": summary["diagnostic_status"],
                "core_area_px": summary["core_area_px"],
                "roi_area_px": records.get("phenotype_roi_holes_filled", {})
                .get("statistics", {})
                .get("nonzero"),
                "potential_ownership_concern_requires_human_review": True,
                "secondary_soma_pass_is_not_ownership": summary[
                    "automated_secondary_soma_single_pass"
                ],
                "tracking": metadata["tracking_comparison.json"],
                "sensitivity": metadata["parameter_sensitivity.json"],
                "fixed_image": fixed_name,
                "search_image": search_name,
                "visits": case_visits,
            }
        )
    return {
        "schema_version": SCHEMA,
        "identity_source": "488_only",
        "days": list(DAYS),
        "cases": cases,
        "visits": visits,
        "source_files": files,
        "benchmark_sha256": benchmark_sha,
        "biological_acceptance_granted": False,
    }


def ui_source():
    return (ROOT / "scripts" / "diagnostic_review_ui.js").read_text()


def render(context, gallery):
    pictures = {}
    for c in context["cases"]:
        for name in (c["fixed_image"], c["search_image"]):
            pictures[name] = (
                "data:image/png;base64,"
                + base64.b64encode(regular(gallery, name).read_bytes()).decode()
            )
    payload = json.dumps({"context": context, "pictures": pictures}, allow_nan=False).replace(
        "<", "\\u003c"
    )
    return (
        '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
        "<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; img-src data:; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'none'\">"
        "<title>Private 488 review</title><style>body{font:17px system-ui;margin:24px;background:#f4f3ef;color:#202020}header,section{background:white;padding:18px;margin-bottom:16px;border:1px solid #ddd}label{display:inline-block;margin:8px}button,select,input,textarea{font:inherit;padding:8px}canvas{max-width:48%;height:auto;background:#111;image-rendering:pixelated}textarea{width:90%}#qc{white-space:pre-wrap}#message{color:#9b1c1c}button{cursor:pointer}#progress{font-weight:bold}</style>"
        "<header><h1>488 identity & ROI review</h1><p>Human annotation only. No automatic acceptance or measurement export. "
        "Original QC failures cannot be changed here. Only 488 evidence is shown; review 561 separately through the existing final workflow.</p>"
        '<label>Reviewer <input id="reviewer" autocomplete="off"></label>'
        '<button id="download">Download private JSON</button> <label>Reload JSON <input id="load" type="file" accept=".json"></label>'
        '<p id="progress"></p><p id="message" role="alert"></p></header>'
        '<section><label>Neuron <select id="neuron"></select></label><label>Day <select id="day"></select></label>'
        '<button id="prev">Previous</button><button id="next">Next</button>'
        "<p>White cross: frozen anchor. Yellow: identity core. Red: fixed phenotype ROI. "
        "Cyan/magenta/orange circles: unadopted search radii 40/60/80. White rectangle in search context: unchanged 128px crop.</p>"
        '<canvas id="fixed" width="768" height="864"></canvas><canvas id="search" width="804" height="900"></canvas>'
        '<pre id="qc"></pre><details><summary>Source fingerprints / automated triage (not human labels)</summary><pre id="provenance"></pre></details></section>'
        '<section><label>Same neuron? <select id="identity"><option value="">Not reviewed</option><option value="yes">Yes</option><option value="no">No</option><option value="uncertain">Uncertain</option></select></label>'
        '<label>ROI ownership <select id="ownership"><option value="">Not reviewed</option><option value="clear">Clear</option><option value="uncertain">Uncertain</option><option value="contaminated">Contaminated</option></select></label>'
        '<p><label>Notes / unresolved questions<br><textarea id="notes" rows="3"></textarea></label></p>'
        '<button id="save">Save this visit annotation</button><p>Use uncertainty freely. Explain uncertain/no/contaminated decisions. '
        "Download JSON before closing; no automatic browser storage or external service is used. Private annotations must not be committed.</p></section>"
        "<script>const REVIEW_DATA="
        + payload
        + ";</script><script>"
        + ui_source()
        + "</script></html>"
    )


def prepare(benchmark, gallery, out):
    out = output_path(out, [benchmark, gallery])
    context = evidence(benchmark, gallery)
    context["ui_sha256"] = hashlib.sha256(ui_source().encode()).hexdigest()
    context["generator_sha256"] = sha(Path(__file__))
    context["workspace_sha256"] = hashlib.sha256(canonical(context)).hexdigest()
    page = render(context, gallery)
    out.mkdir(parents=True, exist_ok=False)
    (out / "workspace.json").write_text(json.dumps(context, indent=2, allow_nan=False) + "\n")
    (out / "index.html").write_text(page)
    blank = blank_annotations(context)
    (out / "blank_annotations.json").write_text(json.dumps(blank, indent=2) + "\n")
    write_csv(out / "blank_annotations.csv", blank)
    readiness = {
        "observation_type": "AUTOMATED_MEASUREMENTS_AND_PROVISIONAL_TRIAGE_NOT_HUMAN_LABELS",
        "visits": context["visits"],
        "cases": context["cases"],
        "initial_dry_run": validate(blank, context),
        "geometry_policy": "Primary area180/radius60 unchanged; alternatives are sensitivity only",
        "accuracy_established": False,
    }
    (out / "readiness_summary.json").write_text(
        json.dumps(readiness, indent=2, allow_nan=False) + "\n"
    )
    return context


def blank_annotations(context):
    return {
        "schema_version": SCHEMA,
        "workspace_sha256": context["workspace_sha256"],
        "source_channel": "488_only",
        "reviewer": "",
        "observations": [
            {
                **{
                    k: r[k]
                    for k in (
                        "neuron_id",
                        "day",
                        "trace_manifest_sha256",
                        "source_sha256",
                        "display_sha256",
                    )
                },
                "workspace_sha256": context["workspace_sha256"],
                "source_channel": "488_only",
                "reviewer": "",
                "reviewed_at": "",
                DECISIONS[0]: "",
                DECISIONS[1]: "",
                "notes": "",
            }
            for r in context["visits"]
        ],
    }


def verify_workspace(workspace, benchmark, gallery):
    recorded = read_json(regular(workspace, "workspace.json"))
    current = evidence(benchmark, gallery)
    current["ui_sha256"] = hashlib.sha256(ui_source().encode()).hexdigest()
    current["generator_sha256"] = sha(Path(__file__))
    current["workspace_sha256"] = hashlib.sha256(canonical(current)).hexdigest()
    if recorded != current or regular(workspace, "index.html").read_text() != render(
        current, gallery
    ):
        raise ValueError(
            "EVIDENCE_STALE: workspace/source/display/code changed; do not rebind old decisions"
        )
    return current


def load_annotations(path):
    path = Path(path)
    if path.suffix.lower() == ".json":
        return read_json(path)
    if path.suffix.lower() != ".csv":
        raise ValueError("Use JSON or CSV annotations")
    with path.open(newline="") as stream:
        reader = csv.DictReader(stream)
        if len(reader.fieldnames or []) != len(set(reader.fieldnames or [])) or set(
            reader.fieldnames or []
        ) != set(FIELDS):
            raise ValueError(
                "CSV requires exact provenance-bound fields; old blank template is not reviewer evidence"
            )
        rows = list(reader)
    if any(None in r or any(v is None for v in r.values()) for r in rows):
        raise ValueError("Malformed CSV observation")
    reviewers = {r["reviewer"] for r in rows if r["reviewer"]}
    workspaces = {r["workspace_sha256"] for r in rows}
    if len(reviewers) > 1 or len(workspaces) != 1:
        raise ValueError("Inconsistent reviewer/workspace attribution")
    return {
        "schema_version": SCHEMA,
        "reviewer": next(iter(reviewers), ""),
        "workspace_sha256": next(iter(workspaces)),
        "source_channel": "488_only",
        "observations": rows,
    }


def validate(document, context):
    if not isinstance(document, dict) or set(document) != {
        "schema_version",
        "workspace_sha256",
        "source_channel",
        "reviewer",
        "observations",
    }:
        raise ValueError(
            "Unknown/missing document fields; no acceptance/QC/561 override is supported"
        )
    if document.get("schema_version") != SCHEMA or document.get("source_channel") != "488_only":
        raise ValueError("Only explicit 488-only diagnostic annotations are allowed")
    if document.get("workspace_sha256") != context["workspace_sha256"]:
        raise ValueError("EVIDENCE_STALE: annotation workspace fingerprint differs")
    reviewer = document.get("reviewer", "")
    if not isinstance(reviewer, str) or reviewer != reviewer.strip():
        raise ValueError("Reviewer must be consistent non-padded text")
    expected = {(r["neuron_id"], r["day"]): r for r in context["visits"]}
    seen, complete, unresolved, positive, missing = {}, [], [], [], []
    rows = document.get("observations")
    if not isinstance(rows, list):
        raise ValueError("Annotation observations must be a list")  # noqa: TRY004 - validation API
    for row in rows:
        if not isinstance(row, dict) or set(row) != set(FIELDS):
            raise ValueError(
                "Unknown/missing annotation fields (no QC overrides, acceptance or 561 decisions)"
            )
        day = row["day"]
        if isinstance(day, str) and day.isdecimal():
            day = int(day)
        if type(day) is not int:
            raise ValueError("Invalid day")
        if not isinstance(row["neuron_id"], str):
            raise ValueError("Invalid neuron identifier")  # noqa: TRY004 - validation API
        key = (row["neuron_id"], day)
        if key not in expected or key in seen:
            raise ValueError("Duplicate/unknown observation: " + str(key))
        seen[key] = row
        source = expected[key]
        for field in ("trace_manifest_sha256", "source_sha256", "display_sha256"):
            if row[field] != source[field]:
                raise ValueError("EVIDENCE_STALE: " + field)
        if (
            row["workspace_sha256"] != context["workspace_sha256"]
            or row["source_channel"] != "488_only"
        ):
            raise ValueError("Stale or non-488 observation")
        identity, ownership = (row[k] for k in DECISIONS)
        if (
            not isinstance(identity, str)
            or not isinstance(ownership, str)
            or identity not in IDENTITY
            or ownership not in OWNERSHIP
        ):
            raise ValueError("Invalid categorical annotation")
        if not isinstance(row["notes"], str):
            raise ValueError("Notes must be text")  # noqa: TRY004 - validation API
        annotated = bool(identity or ownership or row["notes"])
        if annotated:
            if not reviewer or row["reviewer"] != reviewer:
                raise ValueError("Missing/inconsistent human reviewer attribution")
            try:
                date = datetime.fromisoformat(row["reviewed_at"].replace("Z", "+00:00"))
                if date.tzinfo is None or date.utcoffset() is None:
                    raise ValueError("Timezone missing")
            except (ValueError, TypeError, AttributeError) as error:
                raise ValueError("Invalid/missing timezone-aware review timestamp") from error
        elif row["reviewer"] or row["reviewed_at"]:
            raise ValueError("Attribution without an explicit annotation")
        if (
            identity in {"no", "uncertain"} or ownership in {"uncertain", "contaminated"}
        ) and not row["notes"].strip():
            raise ValueError("Explain unresolved/negative human decisions in notes")
        if identity and ownership:
            complete.append(key)
            if identity == "yes" and ownership == "clear":
                positive.append(key)
            else:
                unresolved.append(key)
        else:
            missing.append(key)
    if set(seen) != set(expected):
        raise ValueError(
            "Missing observations: require all frozen visits, including blank/unresolved rows"
        )
    tracks = []
    for case in context["cases"]:
        nid = case["neuron_id"]
        keys = [(nid, d) for d in DAYS]
        blocked = [
            r["day"]
            for r in case["visits"]
            if not r["automated_valid_488"] or r["inherited_tracking_valid"] is not True
        ]
        if nid in TECHNICAL:
            status, reasons = "TECHNICAL_ONLY", ["J05_N015 is not a biological replicate"]
        elif nid in EXCLUDED:
            status, reasons = "EXCLUDED", [EXCLUDED[nid]]
        elif blocked or case["diagnostic_status"] == "diagnostic_rejected":
            status, reasons = (
                "QC_BLOCKED",
                ["Immutable primary/inherited QC failed", "Failed days: " + str(blocked)],
            )
        elif all(k in positive for k in keys):
            status, reasons = (
                "ELIGIBLE_FOR_EXISTING_FINAL_REVIEW",
                ["488-only preparation complete; NOT scientifically accepted"],
            )
        else:
            status, reasons = (
                "REVIEW_PENDING",
                ["Missing/partial/uncertain/negative independent 488 decisions"],
            )
        tracks.append(
            {
                "neuron_id": nid,
                "status": status,
                "reasons": reasons,
                "completed_visits": sum(k in complete for k in keys),
                "unresolved_visits": [d for n, d in keys if (n, d) in unresolved],
                "unreviewed_or_partial_visits": [d for n, d in keys if (n, d) in missing],
                "automated_failed_days": blocked,
                "accepted": False,
                "existing_final_export_requirements": FINAL_REQUIREMENTS,
            }
        )
    return {
        "schema_version": SCHEMA,
        "reviewer_identity_and_independence_authenticated": False,
        "observations": len(seen),
        "complete_decisions": len(complete),
        "unresolved_decisions": len(unresolved),
        "unreviewed_or_partial": len(missing),
        "positive_488_decisions": len(positive),
        "uncertain_decisions": sum("uncertain" in (r[DECISIONS[0]], r[DECISIONS[1]]) for r in rows),
        "negative_decisions": sum(
            r[DECISIONS[0]] == "no" or r[DECISIONS[1]] == "contaminated" for r in rows
        ),
        "reviewer": reviewer,
        "tracks": tracks,
        "real_accepted_ids": [],
        "biological_acceptance_granted": False,
        "scientific_inference_ready": False,
        "n012_packet_full_identity_still_requires_source_evidence": True,
    }


def write_csv(path, document):
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=FIELDS)
    writer.writeheader()
    for row in document["observations"]:
        if any(
            str(row.get(k, "")).lstrip().startswith(("=", "+", "-", "@"))
            for k in ("reviewer", "notes")
        ):
            raise ValueError(
                "Formula-like text is not safe for spreadsheet CSV; preserve JSON instead"
            )
        writer.writerow({k: row[k] for k in FIELDS})
    with Path(path).open("x", newline="") as target:
        target.write(stream.getvalue())
