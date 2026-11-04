"""Opt-in immutable per-well checkpoints; never retrofits legacy console progress."""

import csv
import fcntl
import io
import json
import math
import os
import resource
import shutil
import stat
import sys
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from contextlib import contextmanager
from pathlib import Path

from .full_plate import plain, private_output, sha
from .plate_preflight import canonical_digest, source_stat

RECEIPT_SCHEMA = "tmem.well_checkpoint.v2"
AGGREGATE_SCHEMA = "tmem.well_checkpoint.aggregate.v2"


def clean(value):
    if hasattr(value, "to_dict"):
        return clean(value.to_dict(orient="records"))
    if hasattr(value, "item"):
        return clean(value.item())
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, Path):
        return str(value)
    return value


def _aggregate_sort_key(row):
    """Order visits numerically within wells; undated summaries sort last."""
    day = row.get("timepoint_day", row.get("day"))
    if day is None or (isinstance(day, str) and not day.strip()):
        return str(row.get("well", "")), 1, 0
    if isinstance(day, bool):
        raise TypeError("Invalid aggregate visit day")
    try:
        numeric_day = float(day)
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid aggregate visit day") from exc
    if not math.isfinite(numeric_day) or numeric_day < 0 or not numeric_day.is_integer():
        raise ValueError("Invalid aggregate visit day")
    return str(row.get("well", "")), 0, numeric_day


def _aggregate_bytes(name, rows):
    """One deterministic UTF-8/CRLF representation for writes and comparisons."""
    from .full_plate import TABLE_COLUMNS

    if not name.startswith("all_wells_") or not name.endswith(".csv") or Path(name).name != name:
        raise ValueError("Unsafe aggregate table name")
    ordered = sorted(clean(rows), key=_aggregate_sort_key)
    key = name.removeprefix("all_wells_").removesuffix(".csv")
    fields = sorted({k for row in ordered for k in row} | set(TABLE_COLUMNS.get(key, ())))
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\r\n")
    writer.writeheader()
    writer.writerows(ordered)
    return stream.getvalue().encode("utf-8")


def atomic(path, value, *, text=False):
    path = plain(path)
    if path.exists():
        raise ValueError("Immutable receipt already exists")
    fd, tmp = tempfile.mkstemp(prefix="." + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            if text:
                f.write(value)
            else:
                json.dump(clean(value), f, sort_keys=True, allow_nan=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


@contextmanager
def writer_lock(out):
    p = plain(Path(out) / "writer.lock")
    fd = os.open(p, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError("Invalid writer lock")
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)


def quarantine(out, path, reason):
    """Preserve originals; diagnostic copies never authorize recovery."""
    root = plain(out / "quarantine")
    root.mkdir(mode=0o700, exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix="invalid-", dir=root))
    source = plain(path)
    copied = None
    if source.is_file():
        copied = directory / source.name
        shutil.copyfile(source, copied)
        copied.chmod(0o600)
    atomic(
        directory / "report.json",
        {
            "schema_version": "tmem.checkpoint_quarantine.v1",
            "reason": reason,
            "source": str(source),
            "original_preserved": True,
            "source_sha256": sha(copied) if copied else None,
        },
    )


def read_json(path):
    def unique(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate checkpoint JSON key")
            result[key] = value
        return result

    return json.loads(plain(path).read_text(), object_pairs_hook=unique)


def load_receipt(path, well):
    value = read_json(path)
    if (
        value.get("schema_version") != RECEIPT_SCHEMA
        or value.get("well") != well
        or value.get("status") not in ("completed", "failed")
        or not isinstance(value.get("binding"), dict)
        or not isinstance(value.get("result"), dict)
        or value.get("result_sha256") != canonical_digest(value["result"])
    ):
        raise ValueError("Corrupt checkpoint schema/payload hash")
    result = value["result"]
    if (
        not isinstance(result.get("qc"), list)
        or result.get("error") is not None
        and not isinstance(result["error"], dict)
        or result.get("metrics") is not None
        and not isinstance(result["metrics"], list)
        or any(not isinstance(r, dict) for r in result["qc"] + (result.get("metrics") or []))
        or any(r.get("well") != well for r in result["qc"] + (result.get("metrics") or []))
        or bool(result.get("error")) != (value["status"] == "failed")
    ):
        raise ValueError("Corrupt checkpoint result identity/status")
    if result.get("error") and (
        result["error"].get("well") != well
        or not result["error"].get("error")
        or result["qc"]
        or result.get("metrics")
    ):
        raise ValueError("Invalid failed receipt")
    for key in ("elapsed_seconds", "peak_rss_bytes"):
        v = value.get(key)
        if v is not None and (
            isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0
        ):
            raise ValueError("Invalid receipt resource measurement")
    return value


def verify_finalized(out, binding, names):
    marker = plain(out / "aggregate_manifest.json")
    value = read_json(marker)
    if (
        value.get("schema_version") != AGGREGATE_SCHEMA
        or value.get("binding") != clean(binding)
        or set(value.get("receipts", {})) != set(names)
        or not isinstance(value.get("table_sha256"), dict)
    ):
        raise ValueError("Invalid finalized aggregate declaration")
    for well, expected in value["receipts"].items():
        p = plain(out / (well + ".json"))
        if not p.is_file() or sha(p) != expected:
            quarantine(out, p, "Missing/corrupt finalized receipt")
            raise ValueError("Missing/corrupt finalized receipt")
        try:
            load_receipt(p, well)
        except (ValueError, KeyError, TypeError) as exc:
            quarantine(out, p, str(exc))
            raise
    for name, expected in value["table_sha256"].items():
        if (
            Path(name).name != name
            or not name.startswith("all_wells_")
            or not name.endswith(".csv")
        ):
            raise ValueError("Unsafe aggregate table path")
        p = plain(out / name)
        if not p.is_file() or sha(p) != expected:
            quarantine(out, p, "Missing/corrupt finalized table")
            raise ValueError("Missing/corrupt finalized table")
    return value


def _execute(worker, job):
    start = time.monotonic()
    try:
        result = worker(job)
    except Exception as exc:  # noqa: BLE001 -- persist explicit worker failure evidence
        result = {"qc": [], "metrics": None, "error": {"error": str(exc), "well": job["well"]}}
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return {
        "result": clean(result),
        "elapsed_seconds": time.monotonic() - start,
        "peak_rss_bytes": rss if sys.platform == "darwin" else rss * 1024,
    }


def run_jobs(jobs, worker, out, binding, *, workers=1, resume=False, aggregate_tables=None):
    if type(workers) is not int or not 1 <= workers <= 4:
        raise ValueError("Worker cap is 1..4")
    names = [j["well"] for j in jobs]
    if (
        len(names) != len(set(names))
        or any(not isinstance(w, str) or not w.isalnum() for w in names)
        or not names
    ):
        raise ValueError("Duplicate/unsafe jobs")
    out = plain(out)
    if resume:
        if out.is_relative_to(Path(__file__).resolve().parents[3]) or not out.is_dir():
            raise ValueError("Invalid resume output")
        if not plain(out / "run_binding.json").is_file():
            raise ValueError("Legacy run has no compatible declaration; not modified")
    else:
        private_output(out, [p for j in jobs for p in j.get("sources", [])])
    with writer_lock(out):
        declaration = out / "run_binding.json"
        declaration_value = {
            "schema_version": "tmem.well_checkpoint.run.v2",
            "binding": clean(binding),
            "tasks": sorted(names),
        }
        if resume:
            try:
                declared = read_json(declaration) if declaration.is_file() else None
            except ValueError as exc:
                quarantine(out, declaration, str(exc))
                raise ValueError("Corrupt run declaration preserved/quarantined") from exc
            if declared != declaration_value:
                raise ValueError("Stale config/source/code or legacy run")
        else:
            atomic(declaration, declaration_value)
        marker = plain(out / "aggregate_manifest.json")
        # Validate finalization before source hashing or scheduling any missing task.
        if marker.exists():
            try:
                verify_finalized(out, binding, names)
            except (ValueError, OSError, KeyError, TypeError) as exc:
                quarantine(out, marker, str(exc))
                raise ValueError(
                    "Invalid finalized run; preserved/quarantined, no work scheduled"
                ) from exc
        existing = {}
        for p in out.glob("*.json"):
            if p.name in ("run_binding.json", "aggregate_manifest.json"):
                continue
            try:
                if p.stem not in names:
                    raise ValueError("Unexpected task receipt")
                existing[p.stem] = load_receipt(p, p.stem)
            except (ValueError, OSError, KeyError, TypeError) as exc:
                quarantine(out, p, str(exc))
                raise ValueError("Corrupt checkpoint preserved/quarantined") from exc
        remnants = sorted(out.glob("all_wells_*.csv")) if not marker.exists() else []
        # CSV export begins only after every well receipt is durable. Without a
        # marker, retained CSVs still prove this is aggregation/recovery state,
        # not permission to recompute a missing well.
        try:
            if remnants and set(existing) != set(names):
                raise ValueError("Aggregate artifacts have missing task receipts")
            for job in jobs:
                well = job["well"]
                if well not in existing:
                    continue
                recorded = existing[well]["binding"]
                sources = {str(plain(p)) for p in job.get("sources", [])}
                hashes = recorded.get("source_sha256")
                stats = recorded.get("source_stat")
                if (
                    recorded.get("run") != clean(binding)
                    or recorded.get("job") != clean(job)
                    or not isinstance(hashes, dict)
                    or not isinstance(stats, dict)
                    or set(hashes) != sources
                    or set(stats) != sources
                    or any(
                        not isinstance(h, str)
                        or len(h) != 64
                        or any(c not in "0123456789abcdef" for c in h)
                        for h in hashes.values()
                    )
                ):
                    raise ValueError("Stale/corrupt checkpoint task binding")
                for path, recorded_stat in stats.items():
                    if (
                        not isinstance(recorded_stat, dict)
                        or set(recorded_stat) != {"size_bytes", "mtime_ns", "device", "inode"}
                        or any(type(v) is not int or v < 0 for v in recorded_stat.values())
                        or source_stat(path) != recorded_stat
                    ):
                        raise ValueError("Stale/corrupt checkpoint source identity metadata")
            if remnants:
                if aggregate_tables is None:
                    raise ValueError("Aggregate artifacts require their declared table generator")
                expected_tables = aggregate_tables([existing[w] for w in sorted(existing)], jobs)
                for path in remnants:
                    p = plain(path)
                    if p.name not in expected_tables or p.read_bytes() != _aggregate_bytes(
                        p.name, expected_tables[p.name]
                    ):
                        raise ValueError("Stale aggregate table")
        except (ValueError, OSError, KeyError, TypeError) as exc:
            for path in remnants:
                quarantine(out, path, str(exc))
            raise ValueError(
                "Stale/corrupt interrupted aggregate/checkpoint binding; no work scheduled"
            ) from exc
        if marker.exists() and aggregate_tables is not None:
            try:
                expected_tables = aggregate_tables([existing[w] for w in sorted(existing)], jobs)
                if set(expected_tables) != set(read_json(marker)["table_sha256"]):
                    raise ValueError("Finalized table set differs from validated aggregate")
            except (ValueError, OSError, KeyError, TypeError) as exc:
                quarantine(out, marker, str(exc))
                raise ValueError("Invalid finalized aggregate; no work scheduled") from exc
        results = {}
        pending = []
        fingerprints = {}
        source_stats = {}
        for job in jobs:
            fingerprints[job["well"]] = {
                str(plain(p)): sha(plain(p)) for p in job.get("sources", [])
            }
            source_stats[job["well"]] = {p: source_stat(p) for p in fingerprints[job["well"]]}
            p = plain(out / (job["well"] + ".json"))
            b = {
                "run": clean(binding),
                "job": clean(job),
                "source_sha256": fingerprints[job["well"]],
                "source_stat": source_stats[job["well"]],
            }
            if job["well"] in existing:
                r = existing[job["well"]]
                if r.get("binding") != b:
                    raise ValueError("Stale/corrupt checkpoint")
                results[job["well"]] = r
            else:
                pending.append((job, b))

        def save(job, b, value):
            for p, h in fingerprints[job["well"]].items():
                if sha(p) != h or source_stats[job["well"]][p] != source_stat(p):
                    raise ValueError("Input changed during processing")
            receipt = dict(
                schema_version=RECEIPT_SCHEMA,
                well=job["well"],
                binding=b,
                status="failed" if value["result"].get("error") else "completed",
                result_sha256=canonical_digest(value["result"]),
                **value,
            )
            atomic(out / (job["well"] + ".json"), receipt)
            load_receipt(out / (job["well"] + ".json"), job["well"])
            results[job["well"]] = receipt

        if workers == 1:
            for job, b in pending:
                save(job, b, _execute(worker, job))
        else:
            with ProcessPoolExecutor(max_workers=workers) as pool:
                futures = {pool.submit(_execute, worker, j): (j, b) for j, b in pending}
                for future in as_completed(futures):
                    job, b = futures[future]
                    try:
                        value = future.result()
                    except Exception as exc:  # noqa: BLE001 -- persist future-level failures
                        value = {
                            "result": {
                                "qc": [],
                                "metrics": None,
                                "error": {"well": job["well"], "error": str(exc)},
                            },
                            "elapsed_seconds": None,
                            "peak_rss_bytes": None,
                        }
                    save(job, b, value)
        ordered = [results[w] for w in sorted(results)]
        if not marker.exists():
            table_hashes = {}
            if aggregate_tables is not None:
                for name, rows in sorted(aggregate_tables(ordered, jobs).items()):
                    content = _aggregate_bytes(name, rows)
                    path = plain(out / name)
                    # An interrupted aggregation may leave complete immutable tables.
                    if path.exists():
                        if path.read_bytes() != content:
                            quarantine(out, path, "Stale aggregate table")
                            raise ValueError("Stale aggregate table")
                    else:
                        atomic(path, content.decode("utf-8"), text=True)
                    table_hashes[name] = sha(path)
            atomic(
                marker,
                {
                    "schema_version": AGGREGATE_SCHEMA,
                    "binding": clean(binding),
                    "receipts": {w: sha(out / (w + ".json")) for w in sorted(results)},
                    "table_sha256": table_hashes,
                    "scientific_inference_ready": False,
                },
            )
        else:
            aggregate = json.loads(marker.read_text())
            if aggregate.get("receipts") != {w: sha(out / (w + ".json")) for w in sorted(results)}:
                raise ValueError("Stale aggregate")
            for name, expected in aggregate.get("table_sha256", {}).items():
                if Path(name).name != name or sha(plain(out / name)) != expected:
                    raise ValueError("Stale aggregate table")
        return ordered
