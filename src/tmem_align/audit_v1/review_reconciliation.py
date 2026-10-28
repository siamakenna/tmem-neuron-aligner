"""Read-only reconciliation of private 488 decisions with existing final gates.

This module neither approves tracks nor writes accepted measurements. It reports
what genuine source-bound artifacts are present, missing, inconsistent or stale.
"""

from __future__ import annotations

import csv
import importlib.util
import json
import os
from pathlib import Path

import numpy as np

from . import diagnostic_review as diagnostic
from . import matched_analysis as matched
from .review_gate import (
    evaluate_review,
    evidence_manifest,
    review_directory,
    verify_review_workspace,
)

SCHEMA = "tmem.review_reconciliation.v1"
MISSING_FINAL = [
    "v6_curated_source",
    "v6_rendered_workspace",
    "authentic_v6_final_review",
    "independent_final_561_QC",
    "all_nine_global_and_adaptive_QC",
    "existing_accepted_export",
]
GLOBAL_BLOCKERS = [
    "Independent 488 identity/ROI decisions for all declared visits",
    "Preserve all inherited failed QC; no rescue or partial-visit acceptance",
    "Known F05/N05 exclusions and J05_N015 technical-only status",
    "N012 packet full identity/source/exclusion evidence and other flagged N05 identities",
    "Genuine separate final561review and existing v6 source/render/export fingerprints",
    "Matching detector-coordinate raw images and illumination-correction provenance",
    "Physical calibration, historical stitching and alignment validation where claimed",
    "Eligible accepted six-well cohort; biological unit is well/matched well pair",
    "Independent fate and censoring evidence before any survival analysis",
]


def _path(base, value, *, directory=False):
    return matched.local_path(base, value, directory=directory)


def _diagnostic_array(benchmark, nid, name, manifest):
    records = {r["stage"]: r for r in manifest["stages"]}
    relative = records[name]["artifacts"]["numeric"]["path"]
    path = diagnostic.regular(Path(benchmark) / "tracks" / nid, relative)
    if diagnostic.sha(path) != manifest["files"][relative]:
        raise ValueError("Diagnostic numeric source changed")
    return np.load(path, allow_pickle=False)


def compare_geometry(curated, benchmark, nid, expected_manifest_sha):
    """Compare exact 488 pixels/core/ROI; never use 561 outcomes to choose geometry."""
    trace = Path(benchmark) / "tracks" / nid
    manifest_path = diagnostic.regular(trace, "manifest.json")
    if diagnostic.sha(manifest_path) != expected_manifest_sha:
        raise ValueError("Diagnostic manifest is stale")
    manifest = diagnostic.read_json(manifest_path)
    path = diagnostic.regular(Path(curated), nid + "/small_fixture.npz")
    with np.load(path, allow_pickle=False) as data:
        boxes, core, roi = data["boxes_tcyx"], data["identity_core"], data["phenotype_roi"]
        if boxes.shape != (9, 3, 128, 128) or boxes.dtype != np.uint16:
            raise ValueError("Final crop axes/shape/dtype differ from frozen diagnostic geometry")
        if any(x.shape != (128, 128) or x.dtype != bool for x in (core, roi)):
            raise ValueError("Final core/ROI shape or dtype differs")
        for i in range(9):
            original = _diagnostic_array(benchmark, nid, f"visit_{i:02d}_registered_488", manifest)
            if not np.array_equal(boxes[i, 2], original):
                raise ValueError("Final 488 crop differs at visit" + str(i))
        for name, value in (("primary_identity_core", core), ("phenotype_roi_holes_filled", roi)):
            if not np.array_equal(value, _diagnostic_array(benchmark, nid, name, manifest)):
                raise ValueError("Final fixed 488 core/ROI differs; no automatic rebind")
    return True


def compare_parameters(parameters, frozen):
    """Require declared primary geometry parameters, not a favorable alternative."""
    mapping = {
        "bbox_size": frozen["bbox_size"],
        "segmentation_min_area": frozen["segmentation"]["min_area"],
        "identity_consensus_fraction": frozen["segmentation"]["consensus_fraction"],
        "min_core_area": frozen["segmentation"]["min_core_area"],
        "max_core_area": frozen["segmentation"]["max_core_area"],
        "phenotype_dilation": frozen["segmentation"]["phenotype_dilation"],
        "background_exclusion": frozen["segmentation"]["background_exclusion"],
        "puncta_min_size": frozen["segmentation"]["puncta_min_size"],
    }
    for name, value in mapping.items():
        if name not in parameters or type(parameters[name]) is bool or parameters[name] != value:
            raise ValueError("Missing/changed frozen primary parameter: " + name)
    for name in ("tracking_search_radius", "search_radius"):
        if name in parameters and parameters[name] != frozen["tracking"]["search_radius"]:
            raise ValueError("Tracking alternative was adopted: " + name)
    return True


def _exporter():
    path = diagnostic.ROOT / "scripts/export_reviewed_metrics.py"
    spec = importlib.util.spec_from_file_location("readiness_exporter_contract", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def evaluate_final(entry, base, nid, case, benchmark):
    """Reuse verified v6 contracts, only after diagnostic 488 review/QC passes."""
    result = {
        "state": "MISSING_FINAL_EVIDENCE",
        "missing": list(MISSING_FINAL),
        "source_geometry_verified": False,
        "v6_manual_gate_verified": False,
        "automated_final_QC_verified": False,
        "existing_export_verified": False,
        "fingerprints": {},
        "accepted_measurements_created_here": False,
    }
    if not entry:
        return result
    try:
        if not isinstance(entry, dict) or set(entry) - {
            "curated",
            "workspace",
            "config",
            "reviews",
            "export",
        }:
            raise ValueError("Unknown final-evidence link fields")
        required = ("curated", "workspace", "config", "reviews")
        if not all(entry.get(k) for k in required):
            result["missing"] = [k for k in required if not entry.get(k)]
            return result
        paths = {
            k: _path(base, entry[k], directory=k in {"curated", "workspace", "export"})
            for k in required
        }
        config = diagnostic.read_json(paths["config"])
        review = diagnostic.read_json(paths["reviews"])
        if config.get("neuron_ids") != [nid]:
            raise ValueError(
                "Final evidence must use a target-only configuration before measurement reads"
            )
        params = diagnostic.read_json(
            diagnostic.regular(paths["curated"], nid + "/parameters.json")
        )
        if "SYNTHETIC" in str(params.get("evidence_type", "")).upper():
            raise ValueError("Synthetic source cannot qualify as genuine final evidence")
        trace = diagnostic.read_json(
            diagnostic.regular(Path(benchmark) / "tracks" / nid, "manifest.json")
        )
        compare_parameters(params, trace["metadata"]["parameters"])
        reviewer = str(review.get("reviewer", "")).upper()
        if any(word in reviewer for word in ("SYNTHETIC", "AUTOMATED", "SOFTWARE CONTROL")):
            raise ValueError("Software control reviewer is not independent human evidence")
        source = evidence_manifest(paths["curated"], config["neuron_ids"])
        rendered = verify_review_workspace(paths["workspace"], source, config["known_exclusions"])
        render_root = review_directory(paths["workspace"])
        if diagnostic.read_json(render_root / "config.json") != config:
            raise ValueError("Final configuration differs from the reviewed display")
        result["source_geometry_verified"] = compare_geometry(
            paths["curated"], benchmark, nid, case["visits"][0]["trace_manifest_sha256"]
        )
        verdict = evaluate_review(
            review,
            source,
            config["known_exclusions"],
            workspace_sha256=rendered["workspace_sha256"],
        )
        track = next(r for r in verdict["tracks"] if r["neuron_id"] == nid)
        result["v6_gate_reasons"] = track["reasons"]
        result["fingerprints"] = {
            str(p): diagnostic.sha(p)
            for p in (paths["config"], paths["reviews"], render_root / "render_manifest.json")
        }
        for record in source:
            for name, binding in record["files"].items():
                result["fingerprints"][str(paths["curated"] / record["neuron_id"] / name)] = (
                    binding["sha256"]
                )
        for name, binding in rendered["files"].items():
            result["fingerprints"][str(render_root / name)] = binding["sha256"]
        if not track["eligible"]:
            result.update(
                state="FINAL_REVIEW_PENDING", missing=["authentic_all_criteria_v6_review"]
            )
            return result
        result["v6_manual_gate_verified"] = True
        failures = _exporter().automated_failures(paths["curated"] / nid)
        if failures:
            result.update(state="FINAL_QC_BLOCKED", missing=failures)
            return result
        result["automated_final_QC_verified"] = True
        result.update(state="EXISTING_EXPORT_MISSING", missing=["existing_accepted_export"])
        if entry.get("export"):
            paths["export"] = _path(base, entry["export"], directory=True)
            scope = diagnostic.read_json(paths["export"] / "analysis_scope.json")
            if scope.get("accepted_ids") != [nid]:
                raise ValueError("Final export must be target-only before measurement reads")
            bundle = {k: str(p) for k, p in paths.items()}
            fingerprints = {}
            rows = matched.load_bundle(bundle, base, matched.REAL, fingerprints)
            target = [r for r in rows if r["neuron_id"] == nid]
            if len(target) != 9 or sorted(int(r["day"]) for r in target) != list(diagnostic.DAYS):
                raise ValueError("Existing export does not contain all nine target visits")
            result["fingerprints"].update(fingerprints)
            result.update(
                state="VERIFIED_EXISTING_EXPORT", missing=[], existing_export_verified=True
            )
            result["bundle_paths"] = bundle
    except (ValueError, KeyError, OSError, TypeError, StopIteration) as error:
        result.update(
            state="FINAL_EVIDENCE_STALE_OR_INVALID",
            error=str(error),
            existing_export_verified=False,
            missing=["current_consistent_final_evidence"],
        )
    return result


def verify_cohort(inputs, reconciled):
    result = {"state": "MISSING_ACCEPTED_COHORT_INPUTS", "verified_ids": [], "fingerprints": {}}
    if inputs is None:
        return result
    if not reconciled:
        result.update(
            state="COHORT_BLOCKED",
            error="488 review/QC and verified existing exports required before phenotype analysis",
        )
        return result
    try:
        declared = diagnostic.read_json(inputs)
        if declared.get("evidence_type") != matched.REAL:
            raise ValueError("Synthetic/unapproved inputs cannot qualify as real accepted cohort")
        for bundle in declared.get("bundles", []):
            base = Path(inputs).resolve().parent
            paths = {
                k: str(
                    _path(base, bundle.get(k), directory=k in {"curated", "workspace", "export"})
                )
                for k in ("curated", "workspace", "config", "reviews", "export")
            }
            export = Path(paths["export"])
            scope = diagnostic.read_json(export / "analysis_scope.json")
            accepted = scope.get("accepted_ids", [])
            if len(accepted) != 1 or accepted[0] not in reconciled:
                raise ValueError("Declared export is not a reconciled target-only bundle")
            evidence = reconciled[accepted[0]]
            if paths != evidence.get("bundle_paths"):
                raise ValueError("Cohort bundle differs from exact reconciled final evidence")
            for path, expected in evidence["fingerprints"].items():
                if diagnostic.sha(Path(path)) != expected:
                    raise ValueError("Reconciled evidence changed before phenotype analysis")
        _, _, rows, fingerprints, _, _ = matched.load_inputs(inputs)
        ids = sorted({r["neuron_id"] for r in rows})
        if not ids or not set(ids).issubset(reconciled):
            raise ValueError(
                "Analysis includes tracks without reconciled diagnostic/final source review"
            )
        result.update(
            state="VERIFIED_REAL_ACCEPTED_COHORT_INPUTS",
            verified_ids=ids,
            fingerprints=fingerprints,
        )
    except (ValueError, KeyError, OSError, TypeError) as error:
        result.update(state="COHORT_BLOCKED", error=str(error))
    return result


def figure_readiness(analysis, cohort):
    result = {
        "analysis_verified": False,
        "figures_rendered": False,
        "longitudinal_trajectories": "BLOCKED_NO_VERIFIED_ACCEPTED_ANALYSIS",
        "within_well_summary": "BLOCKED_NO_VERIFIED_ACCEPTED_ANALYSIS",
        "matched_well_comparison": "BLOCKED_NO_VERIFIED_ACCEPTED_ANALYSIS",
        "QC_and_attrition": "BLOCKED_NO_VERIFIED_ACCEPTED_ANALYSIS",
        "ROI_segmentation_provenance": "REQUIRES_GENUINE_FINAL_SOURCE_AND_RENDER_BINDINGS",
        "survival": "BLOCKED_INDEPENDENT_FATE_CENSORING_EVIDENCE_AND_MODEL_REQUIRED",
        "raw_IC_alignment": "BLOCKED_MATCHING_RAW_CALIBRATION_AND_TRANSFORMS_REQUIRED",
        "fingerprints": {},
    }
    if analysis is None:
        return result
    if cohort["state"] != "VERIFIED_REAL_ACCEPTED_COHORT_INPUTS":
        result["error"] = "Reconciled accepted cohort required before opening phenotype analysis"
        return result
    try:
        declared = diagnostic.read_json(Path(analysis) / "analysis_provenance.json")
        source = Path(declared["manifest_path"]).resolve()
        if declared.get("evidence_type") != matched.REAL or diagnostic.sha(source) != cohort[
            "fingerprints"
        ].get(str(source)):
            raise ValueError("Figure provenance is not the reconciled real cohort")
        tables, metadata, _ = matched.verify_analysis(analysis)
        if (
            metadata["evidence_type"] != matched.REAL
            or cohort["state"] != "VERIFIED_REAL_ACCEPTED_COHORT_INPUTS"
        ):
            raise ValueError(
                "Real source-reviewed accepted cohort required before biological figures"
            )
        ids = set(
            tables["neuron_longitudinal"].loc[
                tables["neuron_longitudinal"]["observation_status"] == "accepted", "neuron_id"
            ]
        )
        if not ids.issubset(cohort["verified_ids"]):
            raise ValueError("Figure analysis IDs differ from reconciled cohort")
        if diagnostic.sha(metadata["manifest_path"]) != cohort["fingerprints"].get(
            str(Path(metadata["manifest_path"]).resolve())
        ):
            raise ValueError("Figure input manifest differs from verified cohort")
        result.update(
            analysis_verified=True,
            longitudinal_trajectories="READY_FOR_EXISTING_VERIFIED_PLOTTER",
            within_well_summary="READY_FOR_EXISTING_VERIFIED_PLOTTER",
            QC_and_attrition="READY_FOR_EXISTING_VERIFIED_PLOTTER",
            ROI_segmentation_provenance="BOUND_TO_RECONCILED_V6_SOURCE_AND_RENDER_EVIDENCE",
            fingerprints=dict(metadata["input_sha256"]),
        )
        wells = {n.split("_")[0] for n in ids}
        result["matched_well_comparison"] = (
            "READY_FOR_EXISTING_VERIFIED_PLOTTER"
            if set(matched.WELLS).issubset(wells)
            else "BLOCKED_INCOMPLETE_SIX_WELL_ACCEPTED_COHORT"
        )
    except (ValueError, KeyError, OSError, TypeError) as error:
        result["error"] = str(error)
    return result


def build_report(
    context,
    annotations,
    benchmark,
    *,
    final_links=None,
    final_base=None,
    analysis_inputs=None,
    analysis=None,
):
    verdict = diagnostic.validate(annotations, context)
    links = {} if final_links is None else final_links
    ids = {c["neuron_id"] for c in context["cases"]}
    if not isinstance(links, dict) or not set(links).issubset(ids):
        raise ValueError("Final evidence links contain unknown diagnostic tracks")
    rows = {(r["neuron_id"], int(r["day"])): r for r in annotations["observations"]}
    by_status = {r["neuron_id"]: r for r in verdict["tracks"]}
    tracks, visits, verified = [], [], {}
    for case in context["cases"]:
        nid = case["neuron_id"]
        status = by_status[nid]
        ready = status["status"] == "ELIGIBLE_FOR_EXISTING_FINAL_REVIEW"
        final = (
            evaluate_final(links.get(nid), Path(final_base or "."), nid, case, benchmark)
            if ready
            else {
                "state": "NOT_EVALUATED_BEFORE_488_REVIEW_AND_QC",
                "missing": list(MISSING_FINAL),
                "existing_export_verified": False,
                "fingerprints": {},
            }
        )
        if ready and final["existing_export_verified"]:
            verified[nid] = final
        tracks.append(
            {
                "neuron_id": nid,
                "well": nid.split("_")[0],
                "diagnostic_status": case["diagnostic_status"],
                "diagnostic_readiness": status["status"],
                "diagnostic_review_complete_visits": status["completed_visits"],
                "unresolved_or_negative_visits": status["unresolved_visits"],
                "unreviewed_or_partial_visits": status["unreviewed_or_partial_visits"],
                "automated_failed_days": status["automated_failed_days"],
                "final_evidence": final,
                "decisions_not_translated_to_final_review": True,
                "source_trace_manifest_sha256": case["visits"][0]["trace_manifest_sha256"],
                "frozen_core_area_px": case.get("core_area_px"),
                "geometry_alternative_adopted": False,
            }
        )
        for source in case["visits"]:
            human = rows[(nid, source["day"])]
            visits.append(
                {
                    **human,
                    "well": nid.split("_")[0],
                    "automated_valid_488": source["automated_valid_488"],
                    "inherited_tracking_valid": source["inherited_tracking_valid"],
                    "immutable_failure_reasons": source["automated_failure_reasons"],
                    "track_readiness": status["status"],
                    "verified_existing_export": nid in verified,
                    "fixed_488_sheet": case.get("fixed_image"),
                    "registered_search_context": case.get("search_image"),
                    "visit_index": list(diagnostic.DAYS).index(source["day"]),
                    "cell_fate": "NOT_CLASSIFIED_HERE; SOURCE_FATE_CENSORING_NOT_EVALUATED",
                }
            )
    cohort = verify_cohort(analysis_inputs, verified)
    figures = figure_readiness(analysis, cohort)
    wells = []
    for well in matched.WELLS:
        subset = [r for r in tracks if r["well"] == well]
        observed = [r for r in visits if r["well"] == well]
        count = lambda state, subset=subset: sum(r["diagnostic_readiness"] == state for r in subset)
        accepted = sum(r["neuron_id"] in verified for r in subset)
        wells.append(
            {
                "well": well,
                "diagnostic_candidates": len(subset),
                "qc_blocked": count("QC_BLOCKED"),
                "review_pending": count("REVIEW_PENDING"),
                "excluded": count("EXCLUDED"),
                "technical_only": count("TECHNICAL_ONLY"),
                "positive_488_ready_for_final_review": count("ELIGIBLE_FOR_EXISTING_FINAL_REVIEW"),
                "verified_existing_export_neurons": accepted,
                "cohort_eligible_neurons": sum(
                    r["neuron_id"] in cohort["verified_ids"] for r in subset
                ),
                "total_visits": len(observed),
                "automated_failed_visits": sum(
                    not r["automated_valid_488"] or not r["inherited_tracking_valid"]
                    for r in observed
                ),
                "nonaccepted_visits": len(observed) - 9 * accepted,
                "unreviewed_or_partial_visits": sum(
                    not r[diagnostic.DECISIONS[0]] or not r[diagnostic.DECISIONS[1]]
                    for r in observed
                ),
            }
        )
    by_well = {r["well"]: r for r in wells}
    pairs = [
        {
            "wells": list(pair),
            "eligible_counts": [by_well[w]["cohort_eligible_neurons"] for w in pair],
            "ready": all(by_well[w]["cohort_eligible_neurons"] > 0 for w in pair),
            "treatment_effect_computed": False,
        }
        for pair in matched.PAIRS
    ]
    return {
        "schema_version": SCHEMA,
        "report_type": "PRIVATE_READINESS_NOT_BIOLOGICAL_ANALYSIS",
        "workspace_sha256": context["workspace_sha256"],
        "neuron_readiness": tracks,
        "visit_ledger": visits,
        "original_human_annotations": annotations,
        "diagnostic_review_summary": verdict,
        "well_readiness": wells,
        "matched_pair_readiness": pairs,
        "accepted_cohort": cohort,
        "figure_readiness": figures,
        "verified_existing_export_ids": sorted(verified),
        "accepted_measurements_created_here": 0,
        "biological_unit": "well or matched well pair",
        "neurons_are_independent_replicates": False,
        "treatment_effect_computed": False,
        "survival_analysis_performed": False,
        "scientific_inference_approved": False,
        "global_scientific_blockers": GLOBAL_BLOCKERS,
        "trusted_policy": {
            "exclusions": diagnostic.EXCLUDED,
            "technical_only": sorted(diagnostic.TECHNICAL),
            "n012_packet_identity_not_inferred": True,
            "other_flagged_N05_identities_not_invented": True,
        },
    }


def _write_json(path, value):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as stream:
        stream.write(json.dumps(value, indent=2, allow_nan=False) + "\n")


def run(
    workspace,
    benchmark,
    gallery,
    annotations,
    out,
    *,
    final_links=None,
    analysis_inputs=None,
    analysis=None,
):
    out = diagnostic.output_path(out, [workspace, benchmark, gallery])
    context = diagnostic.verify_workspace(workspace, benchmark, gallery)
    annotation_sha = diagnostic.sha(annotations)
    document = diagnostic.load_annotations(annotations)
    links = {}
    base = Path(".")
    if final_links:
        declaration = diagnostic.read_json(final_links)
        if (
            not isinstance(declaration, dict)
            or set(declaration) != {"schema_version", "tracks"}
            or declaration.get("schema_version") != "tmem.final_review_links.v1"
            or not isinstance(declaration.get("tracks"), dict)
        ):
            raise ValueError("Unsupported final-evidence links schema")
        links = declaration.get("tracks")
        base = Path(final_links).resolve().parent
    result = build_report(
        context,
        document,
        benchmark,
        final_links=links,
        final_base=base,
        analysis_inputs=analysis_inputs,
        analysis=analysis,
    )
    result["annotation_file_sha256"] = annotation_sha
    if diagnostic.sha(annotations) != annotation_sha:
        raise ValueError("Annotations changed during reconciliation")
    for track in result["neuron_readiness"]:
        for path, digest in track["final_evidence"]["fingerprints"].items():
            if diagnostic.sha(path) != digest:
                raise ValueError("Final evidence changed during reconciliation")
    for section in (result["accepted_cohort"], result["figure_readiness"]):
        for path, digest in section.get("fingerprints", {}).items():
            if diagnostic.sha(path) != digest:
                raise ValueError("Cohort/figure source changed during reconciliation")
    out.mkdir(parents=True, mode=0o700, exist_ok=False)
    _write_json(out / "reconciliation.json", result)
    _write_json(
        out / "figure_readiness.json", dict(schema_version=SCHEMA, **result["figure_readiness"])
    )
    for name, rows in (
        ("visit_readiness.csv", result["visit_ledger"]),
        ("well_readiness.csv", result["well_readiness"]),
        ("matched_pair_readiness.csv", result["matched_pair_readiness"]),
    ):
        fields = list(dict.fromkeys(k for r in rows for k in r))
        fd = os.open(out / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            for row in rows:
                safe = {
                    k: json.dumps(v) if isinstance(v, (list, dict)) else v for k, v in row.items()
                }
                for key in ("reviewer", "notes"):
                    if key in safe and str(safe[key]).lstrip().startswith(("=", "+", "-", "@")):
                        safe[key] = "'" + safe[key]  # JSON retains exact original free text.
                writer.writerow(safe)
    return result
