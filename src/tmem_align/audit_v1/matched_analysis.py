"""Evidence-checked descriptive analysis; biological replication stays at well level.

Existing all-nine export policy is unchanged. A separate cohort ledger keeps
excluded, missing and pending tracks visible without treating them as measurements.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import re
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from .review_gate import DAYS, evaluate_review, evidence_manifest, verify_review_workspace

PAIRS = (("E05", "F05"), ("I05", "J05"), ("M05", "N05"))
WELLS = tuple(well for pair in PAIRS for well in pair)
CONDITIONS = {
    well: "reporter_control" if well in ("E05", "I05", "M05") else "TMEM106B" for well in WELLS
}
STATUSES = (
    "accepted",
    "excluded_qc",
    "pending_review",
    "lost_to_followup",
    "uncertain_identity",
    "missing_image",
    "failed_measurement",
)
FATES = (
    "",
    "not_classified",
    "observed_alive",
    "confirmed_death",
    "lost_to_followup",
    "uncertain_identity",
    "missing_image_or_failed_measurement",
    "excluded_qc",
)
QUANTITIES = (
    "phenotype_roi_area",
    "total_mcherry_intensity",
    "punctate_mcherry_integrated_intensity",
    "diffuse_mcherry_integrated_intensity",
    "puncta_count",
)
METRICS = (*QUANTITIES, "mean_mcherry_intensity", "diffuse_fraction", "puncta_density")
FLAGS = (
    "adaptive_valid",
    "single_soma_pass",
    "tracking_valid",
    "global_reg_qc_pass",
    "global_reg_well_registration_qc_pass",
)
ROSTER_FIELDS = (
    "neuron_id",
    "well",
    "day",
    "condition",
    "observation_status",
    "cell_fate",
    "reason",
    "source_reference",
)
TABLES = (
    "neuron_longitudinal",
    "well_day_summary",
    "matched_pair_day",
    "condition_day_summary",
    "qc_summary",
)
SYNTHETIC = "SYNTHETIC_EXAMPLE"
REAL = "REAL_ACCEPTED"


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_json(path):
    def invalid(value):
        raise ValueError(f"Nonfinite JSON constant: {value}")

    return json.loads(Path(path).read_text(), parse_constant=invalid)


def read_csv(path):
    with Path(path).open(newline="") as handle:
        reader = csv.DictReader(handle)
        fields = reader.fieldnames or []
        if len(fields) != len(set(fields)):
            raise ValueError(f"Duplicate columns: {path}")
        rows = list(reader)
    if any(None in row or any(value is None for value in row.values()) for row in rows):
        raise ValueError(f"Malformed CSV row: {path}")
    return fields, rows


def require(condition, message):
    if not condition:
        raise ValueError(message)


def local_path(base, value, *, directory=False):
    require(isinstance(value, str) and bool(value.strip()), "Input path is missing")
    path = Path(value)
    path = path if path.is_absolute() else base / path
    require(not path.is_symlink(), f"Input cannot be a symlink: {path}")
    path = path.resolve(strict=True)
    require(path.is_dir() if directory else path.is_file(), f"Wrong input path type: {path}")
    return path


def true(value):
    return str(value).strip().lower() in {"true", "1"}


def identity(row):
    nid, well = row.get("neuron_id", ""), row.get("well", "")
    require(bool(re.fullmatch(r"[A-P]\d{2}_N\d+", nid)), "Invalid neuron identity")
    require(well in WELLS and nid.split("_")[0] == well, "Neuron/well identity mismatch")
    text = str(row.get("day", ""))
    require(text.isdecimal() and int(text) in DAYS, "Unexpected imaging day")
    return nid, int(text)


def quantity_values(row):
    result = {}
    for field in QUANTITIES:
        try:
            value = float(row[field])
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"Missing/invalid {field}") from error
        require(math.isfinite(value) and value >= 0, f"Nonfinite/negative {field}")
        result[field] = value
    require(result["phenotype_roi_area"] > 0, "ROI area must be positive")
    require(result["puncta_count"].is_integer(), "Puncta count must be an integer")
    require(
        math.isclose(
            result["total_mcherry_intensity"],
            result["punctate_mcherry_integrated_intensity"]
            + result["diffuse_mcherry_integrated_intensity"],
            rel_tol=1e-6,
            abs_tol=1e-4,
        ),
        "Intensity partition does not conserve total",
    )
    return result


def check_geometry(folder, rows):
    """Validate quantitative crop geometry locally, without changing export policy."""
    with np.load(folder / "small_fixture.npz", allow_pickle=False) as data:
        boxes = data["boxes_tcyx"]
        core, roi = data["identity_core"], data["phenotype_roi"]
        masks, valid = data["adaptive_masks"], data["adaptive_valid"]
        require(
            boxes.shape == (9, 3, 128, 128) and boxes.dtype == np.uint16,
            "Require the reviewed uint16 nine-visit TCYX crop",
        )
        require(
            all(mask.shape == (128, 128) and mask.dtype == bool for mask in (core, roi)),
            "Invalid fixed 488 mask geometry",
        )
        require(core.any() and roi.any() and not np.any(core & ~roi), "Empty/inconsistent core/ROI")
        require(
            masks.shape == (9, 128, 128)
            and masks.dtype == bool
            and valid.shape == (9,)
            and valid.dtype == bool,
            "Invalid adaptive mask geometry",
        )
        require(valid.all() and all(mask.any() for mask in masks), "Invalid/empty adaptive visit")
        require(
            all(float(row["phenotype_roi_area"]) == int(roi.sum()) for row in rows),
            "Measurement ROI area differs from reviewed mask",
        )


def load_bundle(bundle, base, mode, fingerprints):
    # Reuse the actual exporter checks; source scripts are shipped with this checkout.
    from .analysis_example import source_script

    automated_failures = source_script("export_reviewed_metrics.py").automated_failures

    paths = {
        key: local_path(base, bundle.get(key), directory=key in {"export", "curated", "workspace"})
        for key in ("export", "curated", "workspace", "config", "reviews")
    }
    export = paths["export"]
    config, review = read_json(paths["config"]), read_json(paths["reviews"])
    scope = read_json(export / "analysis_scope.json")
    source = evidence_manifest(paths["curated"], config["neuron_ids"])
    rendered = verify_review_workspace(paths["workspace"], source, config["known_exclusions"])
    # verify_review_workspace accepts either review/ itself or its parent.
    workspace = paths["workspace"]
    if (workspace / "review").is_dir():
        workspace = workspace / "review"
    require(
        read_json(workspace / "config.json") == config, "Config differs from reviewed workspace"
    )
    verdict = evaluate_review(
        review, source, config["known_exclusions"], workspace_sha256=rendered["workspace_sha256"]
    )
    recorded_verdict = read_json(export / "review_verdicts.json")
    require(
        recorded_verdict.get("gate_scope")
        == "Manual review verdict; automated QC is checked separately before metrics export",
        "Export verdict lacks the expected gate scope",
    )
    require(
        {key: value for key, value in recorded_verdict.items() if key != "gate_scope"} == verdict,
        "Export verdict differs from current evidence-bound review",
    )
    require(bool(verdict["accepted_ids"]), "No accepted measurements")
    for key, expected in {
        "accepted_ids": verdict["accepted_ids"],
        "biological_pairs": [list(pair) for pair in PAIRS],
        "config_sha256": sha256(paths["config"]),
        "review_file_sha256": sha256(paths["reviews"]),
        "review_workspace_sha256": rendered["workspace_sha256"],
        "render_manifest_sha256": sha256(workspace / "render_manifest.json"),
        "ic_policy": config["ic_policy"],
        "inference_ready": False,
    }.items():
        require(key in scope and scope[key] == expected, f"Missing/stale export provenance: {key}")
    require(
        scope.get("wells") == sorted({nid.split("_")[0] for nid in verdict["accepted_ids"]}),
        "Export well inventory mismatch",
    )
    require(
        bool(scope.get("base_git_commit")) and bool(scope.get("export_code_sha256")),
        "Missing source identifiers",
    )
    source_root = Path(__file__).resolve().parents[3]
    expected_code = ("scripts/export_reviewed_metrics.py", "src/tmem_align/audit_v1/review_gate.py")
    require(
        set(scope["export_code_sha256"]) == set(expected_code), "Export code inventory mismatch"
    )
    for name in expected_code:
        require(
            scope["export_code_sha256"][name] == sha256(source_root / name),
            "Export source code differs; inspect/re-export using the current reviewed contract",
        )
        fingerprints[str(source_root / name)] = sha256(source_root / name)
    require(bool(review.get("reviewer", "").strip()), "Missing reviewer")
    synthetic_reviewer = (
        "AUTOMATED" in review["reviewer"].upper() or "SYNTHETIC" in review["reviewer"].upper()
    )
    require(
        synthetic_reviewer if mode == SYNTHETIC else not synthetic_reviewer,
        "Synthetic reviewer cannot qualify as human review; evidence modes must match",
    )
    require(
        review.get("schema_version") == "tmem.manual_review.v2",
        "Require current rendered review schema",
    )
    stamp = datetime.fromisoformat(review["reviewed_at"].replace("Z", "+00:00"))
    require(stamp.utcoffset() is not None, "Review timestamp needs timezone")
    source_by_id = {item["neuron_id"]: item for item in source}
    expected = {}
    tracking = {}
    for nid in verdict["accepted_ids"]:
        folder = paths["curated"] / nid
        params = read_json(folder / "parameters.json")
        if mode == REAL:
            require(
                "SYNTHETIC" not in str(params.get("evidence_type", "")).upper(),
                "Synthetic source arrays cannot enter real analysis",
            )
        failures = automated_failures(folder)
        require(not failures, f"Automated QC failed for {nid}: {failures}")
        _, rows = read_csv(folder / "metrics.csv")
        _, tracks = read_csv(folder / "fixture_tracks.csv")
        check_geometry(folder, rows)
        for row in tracks:
            tracking[identity(row)] = row
        for row in rows:
            key = identity(row)
            require(key not in expected, "Duplicate source observation")
            expected[key] = row
    _, released = read_csv(export / "accepted_neuron_metrics.csv")
    require(len(released) == len(expected), "Export row count mismatch")
    result, seen = [], set()
    for row in released:
        key = identity(row)
        require(key in expected and key not in seen, "Duplicate/unknown exported observation")
        seen.add(key)
        original, track = expected[key], tracking[key]
        for field, value in original.items():
            if field != "review":
                require(row.get(field) == value, f"Export differs from reviewed source: {field}")
        require(
            row.get("source_review_status") == original.get("review", ""),
            "Source review status mismatch",
        )
        require(
            row.get("review") == "MANUAL_ACCEPTED" and true(row.get("review_gate_pass")),
            "Technical/unreviewed row is not an accepted biological observation",
        )
        require(
            row.get("reviewer") == review["reviewer"]
            and row.get("reviewed_at") == review["reviewed_at"],
            "Review attribution mismatch",
        )
        require(
            row.get("evidence_sha256") == source_by_id[key[0]]["evidence_sha256"],
            "Source evidence fingerprint mismatch",
        )
        flags = {field: row.get(field, track.get(field, "")) for field in FLAGS}
        require(all(true(value) for value in flags.values()), "Failed/missing automated QC flag")
        values = quantity_values(row)
        result.append(
            {
                **row,
                **values,
                "day": key[1],
                "condition": CONDITIONS[row["well"]],
                **flags,
                "bundle_reference": str(export),
            }
        )
    for file in (
        paths["config"],
        paths["reviews"],
        export / "analysis_scope.json",
        export / "accepted_neuron_metrics.csv",
        export / "review_verdicts.json",
        workspace / "render_manifest.json",
    ):
        fingerprints[str(file)] = sha256(file)
    # Full array/render byte checks are represented by recomputed manifests above.
    return result


def load_inputs(manifest_path):
    manifest_path = Path(manifest_path).resolve(strict=True)
    manifest, base = read_json(manifest_path), manifest_path.parent
    require(
        manifest.get("schema_version") == "tmem.matched_analysis_inputs.v1",
        "Unsupported input schema",
    )
    mode = manifest.get("evidence_type")
    require(mode in (REAL, SYNTHETIC), "Declare one evidence type")
    require(
        manifest.get("measurement_units")
        == {"intensity": "synthetic_ADU" if mode == SYNTHETIC else "ADU", "area": "px2"},
        "Units missing/incompatible",
    )
    bundles = manifest.get("bundles")
    require(isinstance(bundles, list) and len(bundles) > 0, "No accepted export bundles supplied")
    fingerprints = {str(manifest_path): sha256(manifest_path)}
    accepted, keys = [], set()
    for bundle in bundles:
        for row in load_bundle(bundle, base, mode, fingerprints):
            key = identity(row)
            require(key not in keys, "Duplicate observation across export bundles")
            keys.add(key)
            accepted.append(row)
    policy_path = local_path(base, manifest.get("decision_policy"))
    policy = read_json(policy_path)
    require(
        policy.get("schema_version") == "tmem.analysis_decisions.v1", "Unsupported decision policy"
    )
    require(policy.get("evidence_type") == mode, "Decision policy evidence type mismatch")
    exclusions = policy.get("excluded_neuron_ids")
    require(
        isinstance(exclusions, dict)
        and all(
            isinstance(k, str) and isinstance(v, str) and v.strip() for k, v in exclusions.items()
        ),
        "Invalid exclusions",
    )
    if mode == REAL:
        require(
            policy.get("pending_identity_resolution") == [],
            "Current decision identities remain unresolved",
        )
        require(
            {"F05_N025", "N05_N011"}.issubset(exclusions),
            "Current known exclusions must be preserved",
        )
        technical = policy.get("technical_only_neuron_ids")
        pending = policy.get("pending_neuron_ids")
        packet_exclusions = policy.get("packet_exclusions")
        require(
            isinstance(technical, list) and "J05_N015" in technical,
            "Retained J05 technical rows must remain technical only",
        )
        require(
            isinstance(pending, list) and all(isinstance(nid, str) for nid in pending),
            "Declare pending neuron identities explicitly",
        )
        require(
            isinstance(packet_exclusions, dict) and isinstance(packet_exclusions.get("N012"), dict),
            "Import the current N012 packet decision; do not guess its identity",
        )
        n012 = packet_exclusions["N012"]
        require(
            n012.get("neuron_id") in exclusions and bool(n012.get("source_reference")),
            "N012 packet exclusion needs a resolved excluded identity and source",
        )
        require(
            not any(row["neuron_id"] in set(technical + pending) for row in accepted),
            "Technical-only or pending neuron cannot enter accepted biological analysis",
        )
        evidence = policy.get("evidence_files")
        require(
            isinstance(evidence, list) and len(evidence) > 0, "Current decision evidence is missing"
        )
        for record in evidence:
            file = local_path(policy_path.parent, record.get("path"))
            require(sha256(file) == record.get("sha256"), "Decision evidence fingerprint mismatch")
            fingerprints[str(file)] = sha256(file)
    fingerprints[str(policy_path)] = sha256(policy_path)
    require(
        not any(row["neuron_id"] in exclusions for row in accepted),
        "Known exclusion in accepted export",
    )
    roster_path = local_path(base, manifest.get("cohort_status_csv"))
    fields, roster = read_csv(roster_path)
    require(set(ROSTER_FIELDS).issubset(fields) and bool(roster), "Missing/empty cohort ledger")
    fingerprints[str(roster_path)] = sha256(roster_path)
    seen, by_neuron = set(), {}
    for row in roster:
        key = identity(row)
        require(key not in seen, "Duplicate cohort visit")
        seen.add(key)
        require(row["condition"] == CONDITIONS[row["well"]], "Well/condition mismatch")
        require(
            row["observation_status"] in STATUSES and row["cell_fate"] in FATES,
            "Unknown observation status or cell fate",
        )
        require(
            bool(row["source_reference"].strip()), "Cohort decision requires a source reference"
        )
        require(
            row["observation_status"] == "accepted" or bool(row["reason"].strip()),
            "Missing status reason",
        )
        require(
            (row["observation_status"] == "accepted") == (key in keys),
            "Cohort accepted status contradicts released measurements",
        )
        require(
            not (row["neuron_id"] in exclusions and row["observation_status"] == "accepted"),
            "Known exclusion in cohort",
        )
        require(
            not (
                row["observation_status"] == "accepted"
                and row["cell_fate"]
                in {
                    "lost_to_followup",
                    "uncertain_identity",
                    "missing_image_or_failed_measurement",
                    "excluded_qc",
                }
            ),
            "Accepted observation conflicts with cell-fate classification",
        )
        row["day"] = key[1]
        by_neuron[key[0]] = row["well"]
    require(keys.issubset(seen), "Released measurements lack cohort records")
    return manifest, roster, accepted, fingerprints, exclusions, by_neuron


def build_tables(manifest_path):
    manifest, roster, accepted, fingerprints, exclusions, by_neuron = load_inputs(manifest_path)
    mode = manifest["evidence_type"]
    ledger = {(row["neuron_id"], row["day"]): row for row in roster}
    measurements = {(row["neuron_id"], row["day"]): row for row in accepted}
    rows, warnings = [], []
    for nid, well in sorted(by_neuron.items()):
        for day in DAYS:
            row = ledger.get((nid, day))
            if row is None:
                row = {
                    "neuron_id": nid,
                    "well": well,
                    "day": day,
                    "condition": CONDITIONS[well],
                    "observation_status": "missing_image",
                    "cell_fate": "not_classified",
                    "reason": "expected_visit_not_supplied",
                    "source_reference": "cohort ledger gap",
                }
                warnings.append(f"{nid} Day {day}: expected visit not supplied; no death inferred")
            values = {field: np.nan for field in METRICS}
            if (nid, day) in measurements:
                source = measurements[nid, day]
                values.update({field: source[field] for field in QUANTITIES})
                area, total = source["phenotype_roi_area"], source["total_mcherry_intensity"]
                values.update(
                    mean_mcherry_intensity=total / area,
                    diffuse_fraction=source["diffuse_mcherry_integrated_intensity"] / total
                    if total
                    else np.nan,
                    puncta_density=source["puncta_count"] / area,
                )
            rows.append({**row, **values})
    longitudinal = pd.DataFrame(rows)
    for metric in METRICS:
        baseline = longitudinal[longitudinal.day == 8].set_index("neuron_id")[metric]
        start = longitudinal.neuron_id.map(baseline)
        longitudinal[f"{metric}_change_from_day8"] = longitudinal[metric] - start
        longitudinal[f"{metric}_pct_change_from_day8"] = (
            (longitudinal[metric] - start) / start.where(start != 0) * 100
        )
    well_rows = []
    for well in WELLS:
        if well not in by_neuron.values():
            warnings.append(f"{well}: no declared neurons; matched well is missing")
        for day in DAYS:
            group = longitudinal[(longitudinal.well == well) & (longitudinal.day == day)]
            valid = group[group.observation_status == "accepted"]
            item = {
                "well": well,
                "day": day,
                "condition": CONDITIONS[well],
                "n_expected_neurons": len(group),
                "n_accepted_neurons": len(valid),
            }
            item.update(
                {
                    f"n_{status}": int((group.observation_status == status).sum())
                    for status in STATUSES
                }
            )
            for metric in METRICS:
                values = valid[metric].dropna()
                item.update(
                    {
                        f"{metric}_mean": values.mean(),
                        f"{metric}_median": values.median(),
                        f"{metric}_within_well_sd": values.std(ddof=1),
                        f"{metric}_n_neurons": len(values),
                    }
                )
            well_rows.append(item)
    well_summary = pd.DataFrame(well_rows)
    paired = []
    for control, experimental in PAIRS:
        for day in DAYS:
            c = well_summary[(well_summary.well == control) & (well_summary.day == day)].iloc[0]
            e = well_summary[(well_summary.well == experimental) & (well_summary.day == day)].iloc[
                0
            ]
            available = c.n_accepted_neurons > 0 and e.n_accepted_neurons > 0
            if not available:
                warnings.append(
                    f"{control}/{experimental} Day {day}: matched accepted wells missing"
                )
            item = {
                "pair": f"{control}/{experimental}",
                "control_well": control,
                "experimental_well": experimental,
                "day": day,
                "pair_available": bool(available),
                "control_n_neurons": int(c.n_accepted_neurons),
                "experimental_n_neurons": int(e.n_accepted_neurons),
                "reason": "" if available else "missing_accepted_matched_well",
            }
            for metric in METRICS:
                cv, ev = c[f"{metric}_mean"], e[f"{metric}_mean"]
                item.update(
                    {
                        f"{metric}_control": cv,
                        f"{metric}_experimental": ev,
                        f"{metric}_difference": ev - cv if available else np.nan,
                        f"{metric}_ratio": ev / cv if available and cv != 0 else np.nan,
                    }
                )
            paired.append(item)
    pairs = pd.DataFrame(paired)
    require(pairs.pair_available.any(), "Insufficient accepted matched wells: no paired visit")
    conditions = []
    for day in DAYS:
        pair_day = pairs[(pairs.day == day) & pairs.pair_available]
        if len(pair_day) < 3:
            warnings.append(
                f"Day {day}: {len(pair_day)}/3 contributing pairs; descriptive incomplete cohort"
            )
        for condition in ("reporter_control", "TMEM106B"):
            values = well_summary[
                (well_summary.day == day)
                & (well_summary.condition == condition)
                & (well_summary.n_accepted_neurons > 0)
            ]
            item = {
                "day": day,
                "condition": condition,
                "n_wells": len(values),
                "n_pairs": len(pair_day),
                "n_neurons": int(values.n_accepted_neurons.sum()),
            }
            for metric in METRICS:
                v, d = values[f"{metric}_mean"].dropna(), pair_day[f"{metric}_difference"].dropna()
                item.update(
                    {
                        f"{metric}_equal_well_mean": v.mean(),
                        f"{metric}_between_well_sd": v.std(ddof=1),
                        f"{metric}_n_wells": len(v),
                        f"{metric}_equal_pair_difference": d.mean(),
                        f"{metric}_between_pair_sd": d.std(ddof=1),
                        f"{metric}_n_pairs": len(d),
                    }
                )
            conditions.append(item)
    qc = (
        longitudinal.groupby(["observation_status", "reason"], dropna=False)
        .size()
        .reset_index(name="n_observations")
    )
    qc["denominator_expected_visits"] = len(longitudinal)
    tables = dict(
        zip(TABLES, (longitudinal, well_summary, pairs, pd.DataFrame(conditions), qc), strict=True)
    )
    metadata = {
        "schema_version": "tmem.matched_analysis.v1",
        "evidence_type": mode,
        "manifest_path": str(Path(manifest_path).resolve()),
        "input_sha256": fingerprints,
        "measurement_units": manifest["measurement_units"],
        "exclusions": exclusions,
        "expected_days": list(DAYS),
        "pairs": [list(pair) for pair in PAIRS],
        "biological_unit": "well or matched well pair",
        "neurons_are_independent_replicates": False,
        "survival_analysis_performed": False,
        "scientific_inference_approved": False,
        "analysis_code_sha256": sha256(Path(__file__)),
        "metric_definitions": {
            "mean_mcherry_intensity": "total / fixed 488-derived ROI area",
            "diffuse_fraction": "diffuse / total; undefined at total=0",
            "puncta_density": "puncta count / ROI px2",
        },
    }
    return tables, metadata, sorted(set(warnings))


def analyze(manifest_path, out):
    tables, metadata, warnings = build_tables(manifest_path)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    for name, table in tables.items():
        table.to_csv(out / f"{name}.csv", index=False)
    metadata["output_sha256"] = {f"{name}.csv": sha256(out / f"{name}.csv") for name in TABLES}
    (out / "analysis_warnings.json").write_text(json.dumps(warnings, indent=2) + "\n")
    metadata["output_sha256"]["analysis_warnings.json"] = sha256(out / "analysis_warnings.json")
    (out / "analysis_provenance.json").write_text(
        json.dumps(metadata, indent=2, allow_nan=False) + "\n"
    )
    return tables, metadata, warnings


def verify_analysis(path):
    """Revalidate live source evidence and exact table bytes before plotting."""
    path = Path(path)
    recorded = read_json(path / "analysis_provenance.json")
    tables, actual, warnings = build_tables(recorded["manifest_path"])
    require(
        {k: v for k, v in recorded.items() if k != "output_sha256"} == actual,
        "Analysis provenance is stale",
    )
    for name in TABLES:
        file = path / f"{name}.csv"
        require(
            sha256(file) == recorded["output_sha256"].get(file.name),
            "Analysis table fingerprint mismatch",
        )
        require(
            file.read_text() == tables[name].to_csv(index=False),
            "Analysis table differs from verified computation",
        )
    require(read_json(path / "analysis_warnings.json") == warnings, "Analysis warnings changed")
    return tables, actual, warnings
