"""SOFTWARE_FIXTURE_ONLY integration regressions; no real ND2 pixels/headers."""

import csv
import json
import os
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from tmem_align.audit_v1 import full_plate as fp
from tmem_align.audit_v1 import plate_preflight as pf
from tmem_align.audit_v1 import well_checkpoints as cp


def valid_tables(c, failed=()):
    selected, qc, metrics = [], [], []
    for w in c["wells"]:
        for d in c["visits"]:
            name = f"SOFTWARE_FIXTURE_ONLY_Day{d}_Well{w}_Seq0000.nd2"
            selected.append(
                {
                    "well": w,
                    "day": d,
                    "condition": "fixture",
                    "path": name,
                    "file_name": name,
                    "mcherry_analysis_valid": w in c["reporter_wells"],
                }
            )
            if w in failed:
                continue
            qc.append(
                {
                    "well": w,
                    "condition": "fixture",
                    "timepoint_day": d,
                    "registration_channel": c["channels"]["alignment"],
                    "estimated_y_shift": 0,
                    "estimated_x_shift": 1,
                    "pre_registration_correlation": 0.5,
                    "post_registration_correlation": 0.8,
                    "overlap_fraction": 0.9,
                    "registration_error": None,
                    "qc_pass": d == c["visits"][0],
                }
            )
            if w in c["reporter_wells"]:
                metrics.append(
                    {
                        "well": w,
                        "condition": "fixture",
                        "timepoint_day": d,
                        "file_name": name,
                        "mcherry_channel": c["channels"]["phenotype"],
                        "registration_channel": c["channels"]["alignment"],
                        "puncta_count": 2,
                        "diffuse_to_punctate_ratio": None,
                    }
                )
    failures = [{"well": w, "error": "SOFTWARE_FIXTURE_ONLY failure"} for w in failed]
    return {
        "selected_files": selected,
        "registration_qc": qc,
        "mcherry_measurements": metrics,
        "failures": failures,
        "summary_stats": fp.expected_summary(qc, metrics, failures),
    }


@pytest.fixture
def study(tmp_path):
    root = Path(__file__).resolve().parents[2]
    c = json.loads((root / "configs/tmem_full_plate_20261104.json").read_text())
    c.update(wells=["C05", "E05"], reporter_wells=["E05"], visits=[0, 8], expected_shape=[3, 4, 5])
    rows = valid_tables(c)["selected_files"]
    for row in rows:
        p = tmp_path / row["file_name"]
        p.write_bytes(b"SOFTWARE_FIXTURE_ONLY not an image")
        row.update(path=str(p), site_fov="Seq0000")
    return c, rows


def header(_path=None):
    return {
        "axes": "CYX",
        "sizes": {"C": 3, "Y": 4, "X": 5},
        "shape": [3, 4, 5],
        "dtype": "uint16",
        "is_rgb": False,
        "channels": [{"name": n, "reported_excitation": 405} for n in ["405", "488", "561"]],
    }


def test_preflight_metadata_only_and_unresolved(study):
    c, rows = study
    seen = []
    receipt = pf.preflight_selection(
        rows, c, inspect_header=lambda p: (seen.append(p), header())[1]
    )
    assert len(seen) == 4
    assert all(o["optical_identity"] == "UNRESOLVED" for o in receipt["observations"])
    assert receipt["observations"][0]["day"] == 0
    assert "STAT_ONLY" in receipt["source_integrity_assurance"]


@pytest.mark.parametrize(
    "kind",
    [
        "missing",
        "duplicate",
        "wrong_day",
        "wrong_well",
        "seq",
        "file_name",
        "reporter",
        "missing_file",
        "hardlink",
        "symlink",
        "unreadable",
        "stage",
        "lineage",
        "site",
        "channels",
    ],
)
def test_source_boundary_rejections(study, tmp_path, kind):
    c, rows = deepcopy(study)
    if kind == "missing":
        rows.pop()
    elif kind == "duplicate":
        rows.append(deepcopy(rows[0]))
    elif kind == "wrong_day":
        rows[0]["day"] = 8
    elif kind == "wrong_well":
        rows[0]["well"] = "E05"
    elif kind == "seq":
        rows[0]["site_fov"] = "Seq9999"
    elif kind == "file_name":
        rows[0]["file_name"] = "substituted.nd2"
    elif kind == "reporter":
        rows[0]["mcherry_analysis_valid"] = True
    elif kind == "missing_file":
        rows[0]["path"] = str(tmp_path / "absent.nd2")
    elif kind in ("hardlink", "symlink"):
        target = Path(rows[1]["path"])
        target.unlink()
        if kind == "hardlink":
            os.link(rows[0]["path"], target)
        else:
            target.symlink_to(rows[0]["path"])
    elif kind == "unreadable":
        Path(rows[0]["path"]).chmod(0)
    elif kind == "stage":
        c["processing_stage"] = "REGISTERED_ATLAS"
    elif kind == "lineage":
        c["source_lineage"]["plate_id"] = "other"
    elif kind == "site":
        c["sites"] = ["tile1", "tile2"]
    else:
        c["channels"]["alignment"] = "nuclear"
    with pytest.raises((ValueError, OSError)):
        pf.preflight_selection(rows, c, inspect_header=header)


@pytest.mark.parametrize("bad", [True, False, -1, 0.5, "1.5", "nan", "inf", None, "", "08"])
def test_bad_days_fail(study, bad):
    c, rows = study
    rows[0]["day"] = bad
    with pytest.raises(ValueError):
        pf.preflight_selection(rows, c, inspect_header=header)


@pytest.mark.parametrize(
    "kind",
    [
        "axes",
        "dtype",
        "shape",
        "rgb",
        "bf",
        "P",
        "T",
        "Z",
        "missing_channel",
        "ambiguous_channel",
        "combined_channel",
        "reorder",
    ],
)
def test_header_capabilities(study, kind):
    c, rows = study

    def inspect(p):
        h = header()
        if kind == "axes":
            h["axes"] = "YXC"
        elif kind == "dtype":
            h["dtype"] = "float32"
        elif kind == "shape":
            h["shape"] = [3, 5, 4]
        elif kind == "rgb":
            h["is_rgb"] = True
        elif kind == "bf":
            h.update(axes="YX", sizes={"Y": 4, "X": 5}, shape=[4, 5])
        elif kind in ("P", "T", "Z"):
            h["sizes"][kind] = 2
        elif kind == "missing_channel":
            h["channels"][1]["name"] = "unknown"
        elif kind == "ambiguous_channel":
            h["channels"][0]["name"] = "488"
        elif kind == "combined_channel":
            h["channels"][1]["name"] = "488+561"
            h["channels"][2]["name"] = "other"
        elif kind == "reorder" and "Day8_" in p.name:
            h["channels"].reverse()
        return h

    with pytest.raises((ValueError, TypeError)):
        pf.preflight_selection(rows, c, inspect_header=inspect)


def test_worker_guards_loaded_arrays_and_nonreporter(study):
    import run_checkpointed_plate as runner

    c, rows = study
    series = [r for r in rows if r["well"] == "C05"]
    preflight = pf.preflight_selection(series, c, inspect_header=header, complete=False)
    job = {
        "well": "C05",
        "rows": series,
        "contract": c,
        "days": c["visits"],
        "channels": ["488", "561"],
        "preflight_sha256": pf.canonical_digest(preflight),
    }
    for kind in ["valid", "shape", "dtype", "channels", "nonreporter"]:

        def load(*_args, kind=kind):
            return {
                "array": np.zeros(
                    (3, 4, 5) if kind != "shape" else (3, 5, 4),
                    dtype="uint16" if kind != "dtype" else "float32",
                ),
                "channel_names": ["405", "488", "561"]
                if kind != "channels"
                else ["488", "405", "561"],
            }

        fake = SimpleNamespace(load_nd2_cyx=load)

        def process(_well, actual_rows, *_args, kind=kind, fake=fake, **kwargs):
            assert kwargs["ref_mode"] == "anchored" and kwargs["min_post_correlation"] == 0.07
            for r in actual_rows:
                fake.load_nd2_cyx(r["path"], 1, 1000)
            return {
                "qc": [],
                "metrics": [{"well": "C05"}] if kind == "nonreporter" else None,
                "error": None,
            }

        fake._process_one_well = process
        if kind == "valid":
            assert runner.worker(job, legacy=fake, inspect_header=header)["error"] is None
        else:
            with pytest.raises(ValueError):
                runner.worker(job, legacy=fake, inspect_header=header)
        assert fake.load_nd2_cyx is load
    job["preflight_sha256"] = "stale"
    with pytest.raises(ValueError, match="Preflight changed"):
        runner.worker(job, legacy=fake, inspect_header=header)


@pytest.mark.parametrize(
    "field,value",
    [
        ("well", "E05"),
        ("days", [8, 0]),
        ("days", [False, 8]),
        ("days", [0.0, 8]),
        ("channels", ["561", "488"]),
    ],
)
def test_worker_task_identity_rejected_before_loading(study, field, value):
    import run_checkpointed_plate as runner

    c, rows = study
    job = {
        "well": "C05",
        "rows": [r for r in rows if r["well"] == "C05"],
        "contract": c,
        "days": c["visits"],
        "channels": ["488", "561"],
    }
    job[field] = value
    with pytest.raises(ValueError, match="task identity"):
        runner.worker(job, inspect_header=lambda _p: pytest.fail("No header read permitted"))


def test_complete_dependency_config_runtime_binding(tmp_path, study):
    c, _ = study
    source = tmp_path / "src/tmem_align/analysis"
    source.mkdir(parents=True)
    dependency = source / "mcherry_metrics.py"
    dependency.write_text("# SOFTWARE_FIXTURE_ONLY\n")
    (tmp_path / "scripts").mkdir()
    frozen = tmp_path / "reference.json"
    frozen.write_text('{"fixture": true}')
    c["frozen_processing_config"] = "reference.json"
    config, selection = tmp_path / "contract.json", tmp_path / "selected.csv"
    config.write_text(json.dumps(c))
    selection.write_text("SOFTWARE_FIXTURE_ONLY")

    def binding():
        return pf.build_run_binding(tmp_path, config, selection, c, runtime={"fixture": "1"})

    first = binding()
    dependency.write_text("# changed omitted scientific dependency\n")
    second = binding()
    assert first != second and first["source_tree_sha256"] != second["source_tree_sha256"]
    added = source / "added.py"
    added.write_text("# fixture")
    assert binding() != second
    added.unlink()
    assert binding() == second
    frozen.write_text('{"fixture": false}')
    assert binding() != second
    assert not first["frozen_reference_config"]["applied_by_legacy_worker"]
    assert set(pf.runtime_fingerprint(version=lambda _name: "fixture")["packages"]) >= {
        "nd2",
        "scipy",
        "pandas",
    }
    out = tmp_path / "receipts"
    cp.run_jobs([{"well": "A01"}], receipt_worker, out, first)
    with pytest.raises(ValueError, match="Stale"):
        cp.run_jobs([{"well": "A01"}], never_worker, out, second, resume=True)


def test_generic_channel_declaration_is_not_legacy_execution_approval(study):
    c, _ = study
    c["channels"] = {"alignment": "561", "phenotype": "488"}
    assert fp.validate_contract(c)["channels"]["alignment"] == "561"
    with pytest.raises(ValueError, match="Unsupported legacy"):
        pf.validate_legacy_contract(c)


def receipt_worker(job):
    return {
        "qc": [{"well": job["well"], "timepoint_day": 0, "qc_pass": True}],
        "metrics": None,
        "error": None,
    }


def never_worker(_job):
    raise AssertionError("WORKER MUST NOT EXECUTE")


@pytest.mark.parametrize(
    "damage", ["missing_receipt", "payload", "truncated", "marker", "duplicate_json", "extra"]
)
def test_finalized_damage_never_calls_worker(tmp_path, monkeypatch, damage):
    out = tmp_path / "run"
    jobs = [{"well": "A01"}]
    cp.run_jobs(jobs, receipt_worker, out, {})
    receipt, marker = out / "A01.json", out / "aggregate_manifest.json"
    if damage == "missing_receipt":
        receipt.unlink()
    elif damage == "payload":
        r = json.loads(receipt.read_text())
        r["result"]["qc"][0]["qc_pass"] = False
        receipt.write_text(json.dumps(r))
    elif damage == "truncated":
        receipt.write_text('{"schema_version":')
    elif damage == "marker":
        marker.write_text("invalid")
    elif damage == "duplicate_json":
        receipt.write_text('{"well":"A01","well":"A02"}')
    else:
        (out / "B02.json").write_text(receipt.read_text())
    calls = []
    monkeypatch.setattr(cp, "_execute", lambda *_: calls.append("BAD"))
    with pytest.raises(ValueError):
        cp.run_jobs(jobs, never_worker, out, {}, resume=True)
    assert not calls
    assert list((out / "quarantine").glob("*/report.json"))
    assert marker.exists()


def test_unfinished_payload_corruption_preserved(tmp_path):
    out = tmp_path / "run"
    jobs = [{"well": "A01"}]
    cp.run_jobs(jobs, receipt_worker, out, {})
    (out / "aggregate_manifest.json").unlink()
    p = out / "A01.json"
    r = json.loads(p.read_text())
    r["result"]["qc"][0]["qc_pass"] = False
    p.write_text(json.dumps(r))
    before = p.read_bytes()
    with pytest.raises(ValueError, match="quarantined"):
        cp.run_jobs(jobs, never_worker, out, {}, resume=True)
    assert p.read_bytes() == before


def test_finalized_table_damage_rejects_before_execution(tmp_path, monkeypatch):
    out = tmp_path / "run"
    jobs = [{"well": "A01"}]

    def tables(receipts, _jobs):
        return {"all_wells_registration_qc.csv": receipts[0]["result"]["qc"]}

    cp.run_jobs(jobs, receipt_worker, out, {}, aggregate_tables=tables)
    path = out / "all_wells_registration_qc.csv"
    path.write_text("truncated")
    calls = []
    monkeypatch.setattr(cp, "_execute", lambda *_: calls.append("BAD"))
    with pytest.raises(ValueError, match="finalized"):
        cp.run_jobs(jobs, never_worker, out, {}, resume=True, aggregate_tables=tables)
    assert not calls and path.read_text() == "truncated"


def test_reversed_completion_is_deterministic(tmp_path, monkeypatch):
    # Explicit scheduler injection, separate from the existing actual 1/2/4-process checks.
    from concurrent.futures import Future

    saved = []
    original_atomic = cp.atomic

    def record(path, value, **kwargs):
        if Path(path).name in ("A01.json", "B02.json"):
            saved.append(Path(path).stem)
        return original_atomic(path, value, **kwargs)

    class Pool:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def submit(self, function, *args):
            future = Future()
            future.set_result(function(*args))
            return future

    monkeypatch.setattr(cp, "atomic", record)
    monkeypatch.setattr(cp, "ProcessPoolExecutor", Pool)
    monkeypatch.setattr(cp, "as_completed", lambda futures: reversed(list(futures)))
    result = cp.run_jobs(
        [{"well": "A01"}, {"well": "B02"}], receipt_worker, tmp_path / "reverse", {}, workers=2
    )
    assert saved == ["B02", "A01"]
    assert [r["well"] for r in result] == ["A01", "B02"]


def receipt_tables(receipts, _jobs):
    return {"all_wells_registration_qc.csv": receipts[0]["result"]["qc"]}


def test_partial_aggregate_missing_receipt_never_hashes_source_or_runs(tmp_path, monkeypatch):
    source = tmp_path / "SOFTWARE_FIXTURE_ONLY.bin"
    source.write_bytes(b"fixture")
    out = tmp_path / "partial"
    jobs = [{"well": "A01", "sources": [str(source)]}]
    cp.run_jobs(jobs, receipt_worker, out, {}, aggregate_tables=receipt_tables)
    (out / "aggregate_manifest.json").unlink()
    (out / "A01.json").unlink()
    table_path = out / "all_wells_registration_qc.csv"
    before = table_path.read_bytes()
    hashed, called = [], []
    original_sha, original_execute = cp.sha, cp._execute

    def sha_spy(path):
        if Path(path) == source:
            hashed.append(str(path))
        return original_sha(path)

    def execute_spy(*args):
        called.append("BAD")
        return original_execute(*args)

    monkeypatch.setattr(cp, "sha", sha_spy)
    monkeypatch.setattr(cp, "_execute", execute_spy)
    with pytest.raises(ValueError):
        cp.run_jobs(jobs, never_worker, out, {}, resume=True, aggregate_tables=receipt_tables)
    assert not hashed and not called
    assert not (out / "A01.json").exists()
    assert table_path.read_bytes() == before
    assert list((out / "quarantine").glob("*/report.json"))


def test_intact_interrupted_aggregate_preserves_bytes_and_resumes(tmp_path, monkeypatch):
    out = tmp_path / "intact"
    jobs = [{"well": "A01"}]
    initial = cp.run_jobs(jobs, receipt_worker, out, {}, aggregate_tables=receipt_tables)
    (out / "aggregate_manifest.json").unlink()
    path = out / "all_wells_registration_qc.csv"
    before = path.read_bytes()
    assert b"\r\n" in before
    calls = []
    monkeypatch.setattr(cp, "_execute", lambda *_: calls.append("BAD"))
    resumed = cp.run_jobs(jobs, never_worker, out, {}, resume=True, aggregate_tables=receipt_tables)
    assert resumed == initial and not calls
    assert path.read_bytes() == before and (out / "aggregate_manifest.json").is_file()


def test_changed_partial_aggregate_is_quarantined_not_overwritten(tmp_path):
    out = tmp_path / "changed"
    jobs = [{"well": "A01"}]
    cp.run_jobs(jobs, receipt_worker, out, {}, aggregate_tables=receipt_tables)
    (out / "aggregate_manifest.json").unlink()
    path = out / "all_wells_registration_qc.csv"
    path.write_bytes(path.read_bytes() + b"extra")
    before = path.read_bytes()
    with pytest.raises(ValueError):
        cp.run_jobs(jobs, never_worker, out, {}, resume=True, aggregate_tables=receipt_tables)
    assert path.read_bytes() == before
    assert list((out / "quarantine").glob("*/report.json"))


@pytest.mark.parametrize("mode", ["all_success", "mixed", "all_failed", "nonreporter"])
def test_table_reconciliation_valid(study, mode):
    c, _ = study
    if mode == "nonreporter":
        c.update(wells=["C05"], reporter_wells=[])
    failed = c["wells"] if mode == "all_failed" else ["C05"] if mode == "mixed" else []
    t = valid_tables(c, failed)
    r = fp.validate_tables(t, c)
    assert not r["issues"], r
    assert r["successful_wells"] == sorted(set(c["wells"]) - set(failed))
    if mode == "all_success":
        assert t["summary_stats"][0]["qc_pass"] == 2
        assert t["summary_stats"][0]["qc_total"] == 2


@pytest.mark.parametrize(
    "damage",
    [
        "missing_qc",
        "duplicate_qc",
        "extra_qc",
        "missing_metric",
        "empty_metric",
        "duplicate_metric",
        "nonreporter",
        "wrong_source",
        "empty_summary",
        "duplicate_summary",
        "summary_count",
        "summary_mean",
        "qc_bool",
    ],
)
def test_table_reconciliation_rejects_incomplete(study, damage):
    c, _ = study
    t = valid_tables(c)
    if damage == "missing_qc":
        t["registration_qc"].pop()
    elif damage == "duplicate_qc":
        t["registration_qc"].append(deepcopy(t["registration_qc"][0]))
    elif damage == "extra_qc":
        t["registration_qc"][0]["well"] = "N99"
    elif damage == "missing_metric":
        t["mcherry_measurements"].pop()
    elif damage == "empty_metric":
        t["mcherry_measurements"] = []
    elif damage == "duplicate_metric":
        t["mcherry_measurements"].append(deepcopy(t["mcherry_measurements"][0]))
    elif damage == "nonreporter":
        t["mcherry_measurements"][0]["well"] = "C05"
    elif damage == "wrong_source":
        t["mcherry_measurements"][0]["file_name"] = "wrong.nd2"
    elif damage == "empty_summary":
        t["summary_stats"] = []
    elif damage == "duplicate_summary":
        t["summary_stats"].append(deepcopy(t["summary_stats"][0]))
    elif damage == "summary_count":
        t["summary_stats"][0]["observations"] = 999
    elif damage == "summary_mean":
        t["summary_stats"][0]["mean_overlap_fraction"] = 0.1
    else:
        t["registration_qc"][0]["qc_pass"] = "maybe"
    assert fp.validate_tables(t, c)["issues"]


def test_malformed_csv_and_legacy_summary_integration(tmp_path, study):
    import run_checkpointed_plate as runner

    c, _ = study
    t = valid_tables(c)
    jobs = [
        {"well": w, "contract": c, "rows": [r for r in t["selected_files"] if r["well"] == w]}
        for w in c["wells"]
    ]
    receipts = [
        {
            "result": {
                "qc": [r for r in t["registration_qc"] if r["well"] == w],
                "metrics": [r for r in t["mcherry_measurements"] if r["well"] == w],
                "error": None,
            }
        }
        for w in c["wells"]
    ]
    output = runner.aggregate_tables(receipts, jobs)
    assert set(output) == {"all_wells_" + k + ".csv" for k in fp.TABLE_COLUMNS}
    for key, rows in t.items():
        p = tmp_path / ("all_wells_" + key + ".csv")
        with p.open("w", newline="") as f:
            wr = csv.DictWriter(f, fieldnames=fp.TABLE_COLUMNS[key])
            wr.writeheader()
            wr.writerows(rows)
    assert fp.audit_run(tmp_path, c)["status"] == "FINAL_TABLES_PRESENT"
    p = tmp_path / "all_wells_summary_stats.csv"
    p.write_text("summary_type,summary_type\nbad,bad\n")
    assert fp.audit_run(tmp_path, c)["status"] == "INCONSISTENT"
