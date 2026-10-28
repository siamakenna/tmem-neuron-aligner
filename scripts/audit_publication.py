#!/usr/bin/env python3
"""Fail closed on private/generated files and obvious credentials in a Git publication diff."""

import argparse
import csv
import io
import json
import re
import subprocess
from pathlib import PurePosixPath

BINARY_OR_PRIVATE = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".mp4",
    ".mov",
    ".tif",
    ".tiff",
    ".nd2",
    ".npy",
    ".npz",
    ".zip",
    ".gz",
    ".pdf",
    ".pptx",
    ".log",
    ".xml",
}
SECRET = re.compile(
    r"(?:gh[pousr]_[A-Za-z0-9]{25,}|github_pat_[A-Za-z0-9_]{30,}|AKIA[0-9A-Z]{16}|sk-[A-Za-z0-9_-]{35,})"
)
PERSONAL_PATH = re.compile(r"/(?:Users|home|vf/users)/[A-Za-z0-9_.-]+/|/data/[A-Za-z0-9_.-]+/")


def has_private_review(value):
    if isinstance(value, list):
        return any(has_private_review(x) for x in value)
    if not isinstance(value, dict):
        return False
    schema = value.get("schema_version", "")
    return (
        isinstance(schema, str)
        and schema.startswith(
            (
                "tmem.diagnostic_review.",
                "tmem.manual_review.",
                "tmem.rendered_review.",
                "tmem.review_reconciliation.",
            )
        )
        or bool(value.get("reviewer") or value.get("reviewed_at"))
        or "source_files" in value
        and "visits" in value
        or any(has_private_review(x) for x in value.values())
    )


def inspect_blob(name, data):
    path = PurePosixPath(name)
    problems = []
    if path.suffix.lower() in BINARY_OR_PRIVATE or any(
        p.startswith((".venv", "private-", "review-workspace"))
        or p
        in {"private", "dataset", "benchmark-local", "review-local", ".pipeline", ".env", ".ssh"}
        for p in path.parts
    ):
        problems.append("private/generated publication path")
    if b"\0" in data or len(data) > 500000:
        problems.append("binary/oversized content")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return problems + ["non-text content"]
    if SECRET.search(text):
        problems.append("credential-like token")
    if PERSONAL_PATH.search(text):
        problems.append("personal/institutional absolute path; use explicit configuration")
    if path.suffix == ".json":
        try:

            def unique(items):
                value = {}
                for key, item in items:
                    if key in value:
                        raise ValueError("Duplicate JSON key")
                    value[key] = item
                return value

            value = json.loads(text, object_pairs_hook=unique)
        except ValueError:
            return problems + ["invalid public JSON"]
        if has_private_review(value):
            problems.append("private/source-bound reviewer record or workspace")
        if isinstance(value, dict):
            if value.get("schema_version") == "tmem.diagnostic_review.v1":
                problems.append(
                    "private review workspace/annotation schema (even blank belongs outside Git)"
                )
            if value.get("reviewer") or value.get("reviewed_at"):
                problems.append("private reviewer attribution")
            if any(
                k in value
                for k in (
                    "production_source_hashes",
                    "recorded_stage_failures",
                    "input_array_sha256",
                )
            ):
                problems.append("detailed image-derived receipt belongs in private evidence store")
    if path.suffix == ".csv":
        reader = csv.DictReader(io.StringIO(text))
        if {"reviewer", "trace_manifest_sha256"}.issubset(reader.fieldnames or []):
            problems.append("private review CSV must not be published")
    return problems


def audit(base=None, staged=False):
    args = ["git", "diff", "--name-only", "--diff-filter=ACMR", "-z"]
    if staged:
        args.append("--cached")
    elif base:
        args.extend([base, "HEAD"])
    else:
        raise ValueError("Choose --staged or --base COMMIT")
    names = [x for x in subprocess.check_output(args).decode().split("\0") if x]
    findings = []
    for name in names:
        spec = ":" + name if staged else "HEAD:" + name
        data = subprocess.check_output(["git", "show", spec])
        for reason in inspect_blob(name, data):
            findings.append({"path": name, "reason": reason})
    return {
        "files_checked": len(names),
        "findings": findings,
        "scope": "staged index" if staged else "PR tip files relative to supplied base",
        "historical_commits_not_erased": True,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--staged", action="store_true")
    group.add_argument("--base")
    args = parser.parse_args()
    result = audit(args.base, args.staged)
    print(json.dumps(result, indent=2))
    raise SystemExit(bool(result["findings"]))
