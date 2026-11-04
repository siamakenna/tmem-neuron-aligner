"""Conservative dataset, acquisition-receipt and illustrative-example contracts."""

import csv
import hashlib
import json
import math
import re
import statistics
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def plain(path):
    p = Path(path).absolute()
    if ".." in p.parts or any(q.is_symlink() for q in (p, *p.parents)):
        raise ValueError("Unsafe path")
    return p


def private_output(out, inputs=()):
    out = plain(out)
    if out.exists() or any(
        out.is_relative_to(plain(p)) or plain(p).is_relative_to(out) for p in (REPO, *inputs)
    ):
        raise ValueError("Require new private output outside repository and inputs")
    out.mkdir(parents=True, mode=0o700)
    return out


def write_json(path, value):
    with Path(path).open("x") as f:
        json.dump(value, f, indent=2, allow_nan=False)
    Path(path).chmod(0o600)


def validate_contract(c):
    if c.get("schema_version") != "tmem.dataset_contract.v2":
        raise ValueError("Unsupported dataset contract")
    for k in ("experiment_id", "plate_id", "coordinate_frame", "expected_axes", "expected_dtype"):
        if not isinstance(c.get(k), str) or not c[k]:
            raise ValueError("Missing " + k)
    if not isinstance(c.get("plate_shape"), list) or len(c["plate_shape"]) != 2:
        raise ValueError("Invalid plate shape")
    rows, cols = c["plate_shape"]
    if any(type(n) is not int or n < 1 for n in (rows, cols)) or rows > 26:
        raise ValueError("Invalid plate shape")
    for key in ("wells", "visits", "sites"):
        values = c[key]
        if (
            not isinstance(values, list)
            or not values
            or any(not isinstance(v, (str, int)) for v in values)
            or len(values) != len(set(values))
        ):
            raise ValueError("Empty/duplicate " + key)
    if any(type(d) is not int or d < 0 for d in c["visits"]) or c["visits"] != sorted(c["visits"]):
        raise ValueError("Invalid visit schedule")
    for well in c["wells"]:
        if (
            not isinstance(well, str)
            or not re.fullmatch(r"[A-Z][0-9]{2}", well)
            or ord(well[0]) - 64 > rows
            or not 1 <= int(well[1:]) <= cols
        ):
            raise ValueError("Out-of-bounds well")
    if any(not isinstance(s, str) or not s for s in c["sites"]):
        raise ValueError("Invalid site")
    channels = c["channels"]
    if (
        not isinstance(channels, dict)
        or set(channels) != {"alignment", "phenotype"}
        or channels["alignment"] == channels["phenotype"]
    ):
        raise ValueError("Ambiguous or phenotype-driven channel map")
    if any(not isinstance(v, str) or not v for v in channels.values()):
        raise ValueError("Explicit channel names required")
    if not isinstance(c.get("reporter_wells"), list) or any(
        not isinstance(w, str) for w in c["reporter_wells"]
    ):
        raise ValueError("Invalid reporter map")
    if not set(c["reporter_wells"]).issubset(c["wells"]) or len(c["reporter_wells"]) != len(
        set(c["reporter_wells"])
    ):
        raise ValueError("Invalid reporter map")
    if c["missing_visit_policy"] not in ("reject", "record_missing"):
        raise ValueError("Invalid missing visit policy")
    if c.get("expected_shape") is not None and (
        not isinstance(c["expected_shape"], list)
        or len(c["expected_shape"]) != len(c["expected_axes"])
        or any(type(n) is not int or n < 1 for n in c["expected_shape"])
    ):
        raise ValueError("Invalid dimensions")
    if len(set(c["expected_axes"])) != len(c["expected_axes"]) or any(
        x not in "PTCZYXS" for x in c["expected_axes"]
    ):
        raise ValueError("Invalid axes")
    if c.get("geometry_status") != "COVERAGE_UNRESOLVED":
        raise ValueError("Independent spatial confirmation is not authenticated by this adapter")
    for field in ("processing_stage", "source_identity_policy"):
        if field in c and (not isinstance(c[field], str) or not c[field]):
            raise ValueError("Invalid " + field)
    if "source_lineage" in c and c["source_lineage"] != {
        "experiment_id": c["experiment_id"],
        "plate_id": c["plate_id"],
    }:
        raise ValueError("Invalid declared source lineage")
    return c


def load_contract(path):
    return validate_contract(json.loads(plain(path).read_text()))


def contract_digest(contract):
    """Bind all declared dataset semantics, independent of JSON whitespace."""
    return hashlib.sha256(
        json.dumps(
            validate_contract(contract), sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def validate_curation(value, manifest, manifest_sha):
    if (
        value.get("schema_version") != "tmem.example_curation.v1"
        or value.get("figure_manifest_sha256") != manifest_sha
    ):
        raise ValueError("Stale/invalid curation")
    sources = {s["neuron_id"]: s["trace_manifest_sha256"] for s in manifest["sources"]}
    roles = ("longitudinal", "segmentation", "tracking", "ownership_ambiguous")
    if set(value["selections"]) != set(roles):
        raise ValueError("Explicit example roles required")
    if len({item.get("neuron_id") for item in value["selections"].values()}) != len(roles):
        raise ValueError("Duplicate curated identities")
    for role, item in value["selections"].items():
        if (
            item.get("channel") != "488"
            or item.get("neuron_id") not in sources
            or item.get("trace_manifest_sha256") != sources[item["neuron_id"]]
        ):
            raise ValueError("Example source/channel mismatch")
        if item.get("status") == "REVIEW_CONFIRMED":
            raise ValueError(
                "Genuine independent final-review verification unavailable; confirmation rejected"
            )
        if (
            item.get("status") not in ("ILLUSTRATIVE_UNREVIEWED", "AMBIGUOUS")
            or not item.get("rationale")
            or not item.get("source_refs")
        ):
            raise ValueError("Missing curation rationale/status")
        if role == "ownership_ambiguous" and item["status"] != "AMBIGUOUS":
            raise ValueError("Ownership example must disclose ambiguity")
    return value["selections"]


QC_COLUMNS = (
    "well",
    "condition",
    "timepoint_day",
    "registration_channel",
    "estimated_y_shift",
    "estimated_x_shift",
    "pre_registration_correlation",
    "post_registration_correlation",
    "overlap_fraction",
    "registration_error",
    "qc_pass",
)
METRIC_COLUMNS = (
    "well",
    "condition",
    "timepoint_day",
    "file_name",
    "mcherry_channel",
    "registration_channel",
    "puncta_count",
    "diffuse_to_punctate_ratio",
)
SUMMARY_COLUMNS = (
    "summary_type",
    "condition",
    "day",
    "wells",
    "observations",
    "qc_pass",
    "qc_total",
    "mean_overlap_fraction",
    "mean_diffuse_to_punctate_ratio",
    "median_diffuse_to_punctate_ratio",
    "mean_puncta_count",
)
TABLE_COLUMNS = {
    "selected_files": ("well", "day", "condition", "path", "file_name", "mcherry_analysis_valid"),
    "registration_qc": QC_COLUMNS,
    "mcherry_measurements": METRIC_COLUMNS,
    "failures": ("well", "error"),
    "summary_stats": SUMMARY_COLUMNS,
}


def _day(value):
    if type(value) is int and value >= 0:
        return value
    if isinstance(value, str) and re.fullmatch(r"0|[1-9][0-9]*", value):
        return int(value)
    raise ValueError("Invalid integer visit")


def _bool(value):
    if type(value) is bool:
        return value
    if value in ("True", "False"):
        return value == "True"
    raise ValueError("Invalid QC Boolean")


def _number(value, missing=False):
    if value is None or value == "":
        if missing:
            return None
        raise ValueError("Missing numeric value")
    if isinstance(value, bool):
        raise TypeError("Boolean numeric value")
    result = float(value)
    if not math.isfinite(result):
        if missing:
            return None
        raise ValueError("Nonfinite numeric value")
    return result


def read_table(path):
    """Preserve schema and reject duplicate columns or truncated/malformed rows."""
    with plain(path).open(newline="") as f:
        reader = csv.DictReader(f)
        fields = reader.fieldnames or []
        if len(fields) != len(set(fields)) or any(not x for x in fields):
            raise ValueError("Duplicate/empty CSV header")
        rows = list(reader)
    if any(None in row or any(v is None for v in row.values()) for row in rows):
        raise ValueError("Malformed CSV row")
    return rows, fields


def expected_summary(qc, metrics, failures):
    """Independent reconstruction of legacy group identities, counts and aggregates."""
    result = []
    for kind, records in (("registration_qc", qc), ("mcherry_valid_measurement", metrics)):
        groups = defaultdict(list)
        for row in records:
            groups[(row["condition"], _day(row["timepoint_day"]))].append(row)
        for (condition, day), group in sorted(groups.items()):
            row = dict.fromkeys(SUMMARY_COLUMNS)
            row.update(
                summary_type=kind,
                condition=condition,
                day=day,
                wells=len({r["well"] for r in group}),
                observations=len(group),
            )
            if kind == "registration_qc":
                row.update(
                    qc_pass=sum(_bool(r["qc_pass"]) for r in group),
                    qc_total=len(group),
                    mean_overlap_fraction=statistics.mean(
                        _number(r["overlap_fraction"]) for r in group
                    ),
                )
            else:
                ratios = [
                    v
                    for r in group
                    if (v := _number(r["diffuse_to_punctate_ratio"], True)) is not None
                ]
                puncta = [v for r in group if (v := _number(r["puncta_count"], True)) is not None]
                row.update(
                    mean_diffuse_to_punctate_ratio=statistics.mean(ratios) if ratios else None,
                    median_diffuse_to_punctate_ratio=statistics.median(ratios) if ratios else None,
                    mean_puncta_count=statistics.mean(puncta) if puncta else None,
                )
            result.append(row)
    if failures:
        row = dict.fromkeys(SUMMARY_COLUMNS)
        row.update(
            summary_type="failures",
            condition="all",
            day="",
            wells=len({r["well"] for r in failures}),
            observations=len(failures),
        )
        result.append(row)
    return result


def validate_tables(tables, contract, schemas=None):
    """Validate complete or partial legacy records without inventing measurements."""
    c = validate_contract(contract)
    expected = {(w, d) for w in c["wells"] for d in c["visits"]}
    issues, key_details, assurance = [], {}, []
    records = {key: tables.get(key) or [] for key in TABLE_COLUMNS}
    for key, required in TABLE_COLUMNS.items():
        rows = records[key]
        if tables.get(key) is None:
            continue
        fields = set(schemas[key]) if schemas is not None else set().union(*(set(r) for r in rows))
        if rows and any(not set(required).issubset(r) for r in rows):
            issues.append("Missing required row columns: " + key)
        if fields and not set(required).issubset(fields):
            issues.append("Missing required table columns: " + key)
        if not fields and not rows:
            all_failed = {r.get("well") for r in records["failures"]} == set(c["wells"])
            if (
                key in ("failures", "mcherry_measurements")
                or key == "registration_qc"
                and all_failed
            ):
                assurance.append("HEADERLESS_EMPTY_LEGACY_" + key)
            else:
                issues.append("Empty/missing table schema: " + key)

    def keys(key, day="timepoint_day"):
        output = []
        for row in records[key]:
            try:
                identity = (row["well"], _day(row[day]))
                if not isinstance(identity[0], str):
                    raise TypeError("Invalid well")
                output.append(identity)
            except (ValueError, KeyError, TypeError):
                issues.append("Malformed identity: " + key)
        return output

    selected, qc_keys, metric_keys = (
        keys("selected_files", "day"),
        keys("registration_qc"),
        keys("mcherry_measurements"),
    )
    failed = [r.get("well") for r in records["failures"]]
    if any(not isinstance(w, str) or w not in c["wells"] for w in failed) or len(failed) != len(
        set(failed)
    ):
        issues.append("Invalid/duplicate failure identities")
    failed_set = {w for w in failed if isinstance(w, str)}
    if any(
        not isinstance(r.get("error"), str) or not r["error"].strip() for r in records["failures"]
    ):
        issues.append("Missing explicit failure reason")
    covered_failed = {(w, d) for w in failed_set for d in c["visits"]}
    success = {w for w in c["wells"] if {(w, d) for d in c["visits"]}.issubset(qc_keys)}
    eligible = {(w, d) for w in success & set(c["reporter_wells"]) for d in c["visits"]}
    for name, actual, wanted in (
        ("selection", selected, expected),
        ("qc", qc_keys, expected - covered_failed),
        ("phenotype", metric_keys, eligible),
    ):
        counts = Counter(actual)
        detail = {
            "missing": sorted(wanted - set(actual)),
            "extra": sorted(set(actual) - wanted),
            "duplicates": sorted(k for k, n in counts.items() if n > 1),
        }
        key_details[name] = detail
        present = (
            tables.get(
                {
                    "selection": "selected_files",
                    "qc": "registration_qc",
                    "phenotype": "mcherry_measurements",
                }[name]
            )
            is not None
        )
        if detail["extra"] or detail["duplicates"] or present and detail["missing"]:
            issues.append("Incomplete/duplicate/extra " + name + " keys")
    if set(qc_keys) & covered_failed:
        issues.append("QC/failure overlap")
    selected_map = {k: row for k, row in zip(selected, records["selected_files"])}
    for row in records["selected_files"]:
        try:
            if _bool(row["mcherry_analysis_valid"]) != (row["well"] in c["reporter_wells"]):
                raise ValueError("Reporter map")
        except (KeyError, ValueError):
            issues.append("Reporter selection mismatch")
    for row in records["registration_qc"]:
        try:
            key = (row["well"], _day(row["timepoint_day"]))
            _bool(row["qc_pass"])
            if row["condition"] != selected_map[key]["condition"]:
                raise ValueError("Condition mismatch")
            from .plate_preflight import channel_index

            channel_index([row["registration_channel"]], c["channels"]["alignment"])
            for field in QC_COLUMNS[4:10]:
                value = _number(row[field], field == "registration_error")
                if field == "overlap_fraction" and not 0 <= value <= 1:
                    raise ValueError("Invalid overlap")
        except (KeyError, ValueError, TypeError):
            issues.append("Invalid QC schema/value/source")
    for row in records["mcherry_measurements"]:
        try:
            key = (row["well"], _day(row["timepoint_day"]))
            if (
                key not in eligible
                or row["condition"] != selected_map[key]["condition"]
                or row["file_name"] != selected_map[key]["file_name"]
            ):
                raise ValueError("Phenotype source/eligibility mismatch")
            from .plate_preflight import channel_index

            channel_index([row["mcherry_channel"]], c["channels"]["phenotype"])
            channel_index([row["registration_channel"]], c["channels"]["alignment"])
            count = _number(row["puncta_count"], True)
            if count is not None and (count < 0 or int(count) != count):
                raise ValueError("Invalid puncta count")
            _number(row["diffuse_to_punctate_ratio"], True)
        except (KeyError, ValueError, TypeError):
            issues.append("Invalid/nonreporter phenotype schema/value/source")
    if tables.get("summary_stats") is not None and not issues:
        try:
            expected_rows = expected_summary(
                records["registration_qc"], records["mcherry_measurements"], records["failures"]
            )

            def summary_key(r):
                return (
                    r["summary_type"],
                    r["condition"],
                    "" if r["summary_type"] == "failures" else _day(r["day"]),
                )

            wanted = {summary_key(r): r for r in expected_rows}
            actual = [summary_key(r) for r in records["summary_stats"]]
            if len(actual) != len(set(actual)) or set(actual) != set(wanted):
                raise ValueError("Summary key coverage")
            for row in records["summary_stats"]:
                if row["summary_type"] == "failures" and row["day"] not in ("", None):
                    raise ValueError("Failure summary must be undated")
                for field in SUMMARY_COLUMNS[3:]:
                    a, b = _number(row[field], True), wanted[summary_key(row)][field]
                    if (
                        field in ("wells", "observations", "qc_pass", "qc_total")
                        and a is not None
                        and (a < 0 or int(a) != a)
                    ):
                        raise ValueError("Noninteger summary count")
                    if (
                        (a is None) != (b is None)
                        or a is not None
                        and not math.isclose(a, b, rel_tol=1e-7, abs_tol=1e-9)
                    ):
                        raise ValueError("Summary count/metric mismatch")
        except (ValueError, KeyError, TypeError):
            issues.append("Invalid/incomplete summary schema/counts/metrics")
    return {
        "issues": sorted(set(issues)),
        "key_details": key_details,
        "schema_assurance": assurance,
        "successful_wells": sorted(success - failed_set),
        "expected_phenotype_observations": len(eligible),
    }


def audit_run(run, contract, process_status="UNKNOWN"):
    run = plain(run)
    if process_status not in ("RUNNING", "EXITED", "UNKNOWN"):
        raise ValueError("Invalid observed process status")
    c = validate_contract(contract)
    expected = {(w, d) for w in c["wells"] for d in c["visits"]}
    tables = {}
    schemas = {}
    bindings = {}
    parse_issues = []
    for key in (
        "selected_files",
        "registration_qc",
        "failures",
        "mcherry_measurements",
        "summary_stats",
    ):
        p = plain(run / ("all_wells_" + key + ".csv"))
        if p.is_file():
            h = sha(p)
            try:
                tables[key], schemas[key] = read_table(p)
            except ValueError as exc:
                tables[key], schemas[key] = [], []
                parse_issues.append(key + ": " + str(exc))
            if sha(p) != h:
                raise ValueError("Changing run table; retry read-only audit later")
            bindings[str(p)] = h
        else:
            tables[key] = None
            schemas[key] = []
    if tables["selected_files"] is None:
        raise ValueError("Missing selection manifest")
    validation = validate_tables(tables, c, schemas)
    issues = parse_issues + validation["issues"]

    def usable(rows, dayfield):
        output = []
        for r in rows:
            try:
                if (r["well"], _day(r[dayfield])) in expected:
                    output.append(r)
            except (KeyError, ValueError, TypeError):
                continue
        return output

    selected = [(r["well"], _day(r["day"])) for r in usable(tables["selected_files"], "day")]
    qc = tables["registration_qc"] or []
    usable_qc = usable(qc, "timepoint_day")
    keys = [(r["well"], _day(r["timepoint_day"])) for r in usable_qc]
    failures = [r["well"] for r in tables["failures"] or [] if r.get("well") in c["wells"]]
    missing = expected - set(keys) - {(w, d) for w in failures for d in c["visits"]}
    bywell = []
    byday = []
    for w in c["wells"]:
        records = [r for r in usable_qc if r["well"] == w]
        valid = all(r.get("qc_pass") in ("True", "False") for r in records)
        passes = sum(r.get("qc_pass") == "True" for r in records)
        bywell.append(
            {
                "well": w,
                "selected_visits": sum(x == w for x, d in selected),
                "qc_visits": len(records),
                "qc_passes": passes if valid else None,
                "pass_fraction": passes / len(records)
                if valid
                and len(records) == len(c["visits"])
                and len({r["timepoint_day"] for r in records}) == len(records)
                else None,
                "status": "FAILED"
                if w in failures
                else "RECORDED"
                if len(records) == len(c["visits"])
                else "PENDING",
            }
        )
    for d in c["visits"]:
        records = [r for r in usable_qc if _day(r["timepoint_day"]) == d]
        byday.append(
            {
                "day": d,
                "expected_wells": len(c["wells"]),
                "qc_observations": len(records),
                "passes": sum(r.get("qc_pass") == "True" for r in records),
                "missing": len(c["wells"]) - len({r["well"] for r in records}),
            }
        )
    complete = all(v is not None for v in tables.values())
    if complete and missing:
        issues.append("Unexplained missing QC visits")
    for p, h in bindings.items():
        if sha(p) != h:
            raise ValueError("Source changed during audit")
    return {
        "schema_version": "tmem.full_plate_audit.v1",
        "status": "INCONSISTENT" if issues else "FINAL_TABLES_PRESENT" if complete else "PENDING",
        "process_status_observation": process_status,
        "expected_wells": len(c["wells"]),
        "wells": c["wells"],
        "contract_sha256": contract_digest(c),
        "expected_visits": len(expected),
        "days": c["visits"],
        "selection_rows": len(selected),
        "qc_rows": len(qc),
        "recorded_failed_wells": failures,
        "unexplained_missing_visits": len(missing),
        "missing_tables": [k for k, v in tables.items() if v is None],
        "issues": issues,
        "key_details": validation["key_details"],
        "schema_assurance": validation["schema_assurance"],
        "successful_wells": validation["successful_wells"],
        "expected_phenotype_observations": validation["expected_phenotype_observations"],
        "failure_records": tables["failures"] or [],
        "by_well": bywell,
        "by_day": byday,
        "qc_records": qc,
        "source_sha256": bindings,
        "scientific_inference_ready": False,
        "accepted_ids": [],
    }
