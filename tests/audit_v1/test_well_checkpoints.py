"""SOFTWARE_FIXTURE_ONLY executor checks; not real-image performance."""

import csv
import json

import pytest

from tmem_align.audit_v1.well_checkpoints import atomic, run_jobs, writer_lock


def worker(job):
    if job.get("fail"):
        raise RuntimeError("constructed failure")
    return {
        "qc": [{"well": job["well"], "timepoint_day": d, "qc_pass": True} for d in [8, 12]],
        "metrics": None,
        "error": None,
    }


def aggregate(receipts, jobs):
    return {
        "all_wells_registration_qc.csv": [
            r for receipt in receipts for r in receipt["result"]["qc"]
        ]
    }


@pytest.mark.parametrize("workers", [1, 2, 4])
def test_parallel_equality_resume_and_failures(tmp_path, workers):
    jobs = [{"well": "B02", "fail": True}, {"well": "A01"}]
    out = tmp_path / "new"
    r = run_jobs(jobs, worker, out, {"fixture": True}, workers=workers)
    assert [x["status"] for x in r] == ["completed", "failed"]
    assert r[0]["result"]["qc"] == worker(jobs[1])["qc"]
    assert all(x["peak_rss_bytes"] > 0 for x in r)
    assert run_jobs(jobs, worker, out, {"fixture": True}, workers=workers, resume=True) == r
    with pytest.raises(ValueError):
        run_jobs(jobs, worker, out, {"fixture": False}, resume=True)


def test_source_mutation_and_legacy_resume(tmp_path):
    p = tmp_path / "source.txt"
    p.write_text("SOFTWARE_FIXTURE_ONLY")
    out = tmp_path / "run"
    jobs = [{"well": "A01", "sources": [str(p)]}]
    run_jobs(jobs, worker, out, {})
    p.write_text("changed")
    with pytest.raises(ValueError, match="Stale"):
        run_jobs(jobs, worker, out, {}, resume=True)
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    with pytest.raises(ValueError, match="(?i)legacy"):
        run_jobs(jobs, worker, legacy, {}, resume=True)


def test_lock_atomic_and_duplicate(tmp_path, monkeypatch):
    with writer_lock(tmp_path), pytest.raises(BlockingIOError), writer_lock(tmp_path):
        pass
    with writer_lock(tmp_path):
        pass
    import tmem_align.audit_v1.well_checkpoints as cp

    def interrupted(*args):
        raise OSError("constructed interrupted replace")

    monkeypatch.setattr(cp.os, "replace", interrupted)
    p = tmp_path / "receipt.json"
    with pytest.raises(OSError):
        atomic(p, {"fixture": True})
    assert not p.exists()
    with pytest.raises(ValueError, match="Duplicate"):
        run_jobs([{"well": "A01"}, {"well": "A01"}], worker, tmp_path / "no", {})


def test_aggregate_numeric_visit_order(tmp_path):
    out = tmp_path / "run"
    run_jobs([{"well": "A01"}], worker, out, {}, aggregate_tables=aggregate)
    with (out / "all_wells_registration_qc.csv").open() as f:
        rows = list(csv.DictReader(f))
    assert [int(r["timepoint_day"]) for r in rows] == [8, 12]
    assert json.loads((out / "aggregate_manifest.json").read_text())["table_sha256"]


@pytest.mark.parametrize("missing", [None, "", "   "])
def test_missing_day_last_without_becoming_zero(tmp_path, missing):
    def fixture_tables(receipts, jobs):
        return {
            "all_wells_registration_qc.csv": [
                {"well": "A01", "day": missing, "label": "missing"},
                {"well": "A01", "day": 8, "label": "eight"},
                {"well": "A01", "day": 0, "label": "zero"},
            ]
        }

    out = tmp_path / "run"
    run_jobs([{"well": "A01"}], worker, out, {}, aggregate_tables=fixture_tables)
    with (out / "all_wells_registration_qc.csv").open() as f:
        rows = list(csv.DictReader(f))
    assert [r["label"] for r in rows] == ["zero", "eight", "missing"]
    assert rows[-1]["day"] == ("" if missing is None else missing)


@pytest.mark.parametrize("bad", [True, "garbage", "nan", "inf"])
def test_invalid_aggregate_day_fails_before_final_marker(tmp_path, bad):
    def fixture_tables(receipts, jobs):
        return {"all_wells_registration_qc.csv": [{"well": "A01", "day": bad}]}

    out = tmp_path / "run"
    with pytest.raises((ValueError, TypeError), match="Invalid aggregate visit day"):
        run_jobs([{"well": "A01"}], worker, out, {}, aggregate_tables=fixture_tables)
    assert (out / "A01.json").is_file()
    assert not (out / "aggregate_manifest.json").exists()
