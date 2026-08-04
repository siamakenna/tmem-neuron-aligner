#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path
from typing import Any

from PIL import Image


DEFAULT_DASHBOARD_ROOT = Path("~/Documents/TMEM106B_processed/dashboard")
DEFAULT_SUMMARY_ROOT = Path(
    "~/Documents/TMEM106B_processed/full_mcherry_valid_defg_pass5/review_summaries"
)
DEFAULT_OVERLAP_SUMMARY_ROOT = Path("~/Documents/TMEM106B_processed/full_mcherry_valid_queue_abc/overlap_only_audit")
DEFAULT_SITE_ROOT = Path("docs")
FORBIDDEN_SUFFIXES = {
    ".nd2",
    ".tif",
    ".tiff",
    ".ome.tif",
    ".ome.tiff",
    ".zarr",
    ".mp4",
    ".gif",
}
TEXT_SUFFIXES = {".html", ".json", ".csv", ".txt", ".md", ".js", ".css"}
IMAGE_SUFFIXES = {".png"}
GENERATED_PATHS = [
    "index.html",
    "qc_summary.html",
    "roi_full_mcherry_valid_pass5.html",
    "roi_pilot.html",
    "roi_review_queue.html",
    "roi_first_pass_metric_summary.html",
    "roi_review_priority_wells.html",
    "roi_review_unreviewed.html",
    "roi_review_confirmed_same_neuron.html",
    "roi_review_poor_registration_or_exclude.html",
    "roi_review_saturation_clipping_warnings.html",
    "overlap_only_qc_summary.html",
    "overlap_only_pi_summary.html",
    "alignment_qc_review.html",
    "queue_index.json",
    "site_size_report.txt",
    "site_size_report.json",
    "assets",
    "wells",
    "rois",
    "previews",
    "roi_previews",
    "summaries",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a sanitized GitHub Pages dashboard in docs/.")
    parser.add_argument("--dashboard-root", type=Path, default=DEFAULT_DASHBOARD_ROOT)
    parser.add_argument("--summary-root", type=Path, default=DEFAULT_SUMMARY_ROOT)
    parser.add_argument("--overlap-summary-root", type=Path, default=DEFAULT_OVERLAP_SUMMARY_ROOT)
    parser.add_argument("--site-root", type=Path, default=DEFAULT_SITE_ROOT)
    parser.add_argument("--max-image-width", type=int, default=900)
    parser.add_argument("--warn-size-mb", type=float, default=350.0)
    parser.add_argument("--largest-count", type=int, default=25)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    dashboard_root = args.dashboard_root.expanduser().resolve()
    summary_root = args.summary_root.expanduser().resolve()
    overlap_summary_root = args.overlap_summary_root.expanduser().resolve()
    site_root = args.site_root.resolve()

    if not dashboard_root.exists():
        raise FileNotFoundError(dashboard_root)
    if not summary_root.exists():
        raise FileNotFoundError(summary_root)
    if not overlap_summary_root.exists():
        raise FileNotFoundError(overlap_summary_root)

    site_root.mkdir(parents=True, exist_ok=True)
    clean_generated_site(site_root)

    copied: list[dict[str, Any]] = []
    skipped: list[str] = []

    for source in iter_files(dashboard_root):
        rel = source.relative_to(dashboard_root)
        if is_forbidden(source):
            skipped.append(str(rel))
            continue
        target = site_root / rel
        copy_web_file(source, target, max_image_width=args.max_image_width)
        copied.append(file_record(target, site_root))

    summaries_target = site_root / "summaries"
    summaries_target.mkdir(parents=True, exist_ok=True)
    for source in iter_files(summary_root):
        if source.suffix.lower() not in {".csv", ".json", ".html"}:
            skipped.append(f"summary:{source.name}")
            continue
        target = summaries_target / source.name
        copy_web_file(source, target, max_image_width=args.max_image_width)
        copied.append(file_record(target, site_root))
    for source in iter_files(overlap_summary_root):
        if source.suffix.lower() not in {".csv", ".json", ".html"}:
            skipped.append(f"overlap_summary:{source.name}")
            continue
        target = summaries_target / source.name
        copy_web_file(source, target, max_image_width=args.max_image_width)
        copied.append(file_record(target, site_root))

    write_pages_readme(site_root)
    sanitize_existing_text_files(site_root)
    report = build_report(site_root, copied=copied, skipped=skipped, warn_size_mb=args.warn_size_mb, largest_count=args.largest_count)
    write_report(site_root, report)
    print_report(report)


def iter_files(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*") if path.is_file())


def clean_generated_site(site_root: Path) -> None:
    for relative in GENERATED_PATHS:
        target = site_root / relative
        if target.is_dir():
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()


def is_forbidden(path: Path) -> bool:
    name = path.name.lower()
    suffix = path.suffix.lower()
    return suffix in FORBIDDEN_SUFFIXES or any(name.endswith(forbidden) for forbidden in FORBIDDEN_SUFFIXES)


def copy_web_file(source: Path, target: Path, *, max_image_width: int) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    suffix = source.suffix.lower()
    if suffix in IMAGE_SUFFIXES:
        copy_optimized_png(source, target, max_image_width=max_image_width)
    elif suffix in TEXT_SUFFIXES:
        text = source.read_text(encoding="utf-8", errors="replace")
        target.write_text(sanitize_text(text), encoding="utf-8")
    else:
        shutil.copy2(source, target)


def copy_optimized_png(source: Path, target: Path, *, max_image_width: int) -> None:
    with Image.open(source) as image:
        image.load()
        if image.width > max_image_width:
            ratio = max_image_width / image.width
            height = max(1, int(image.height * ratio))
            image = image.resize((max_image_width, height), Image.Resampling.LANCZOS)
        if image.mode not in {"P", "L"}:
            image = image.convert("P", palette=Image.Palette.ADAPTIVE, colors=192)
        image.save(target, format="PNG", optimize=True)


def sanitize_text(text: str) -> str:
    home = str(Path.home())
    replacements = {
        f"{home}/Documents/TMEM106B_processed/": "LOCAL_PROCESSED_OUTPUT/",
        f"{home}/Documents/260213_Feb16recopy_HYdiff_landingpadlines_survival_384well1/": "LOCAL_RAW_DATA/",
        f"{home}/Documents/tmem_neuron_aligner/": "LOCAL_REPO/",
        f"{home}/": "LOCAL_USER_HOME/",
        "~/Documents/TMEM106B_processed/": "LOCAL_PROCESSED_OUTPUT/",
        "~/Documents/260213_Feb16recopy_HYdiff_landingpadlines_survival_384well1/": "LOCAL_RAW_DATA/",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
        text = text.replace(old.replace("/", "\\/"), new)
    text = re.sub(
        r"LOCAL_PROCESSED_OUTPUT/[^\s<>\"]+\.(?:ome\.tif|ome\.tiff|tif|tiff|zarr|mp4|gif)",
        "Large microscopy file stored locally/shared drive",
        text,
        flags=re.IGNORECASE,
    )
    return text


def file_record(path: Path, site_root: Path) -> dict[str, Any]:
    return {
        "path": str(path.relative_to(site_root)),
        "bytes": path.stat().st_size,
    }


def build_report(
    site_root: Path,
    *,
    copied: list[dict[str, Any]],
    skipped: list[str],
    warn_size_mb: float,
    largest_count: int,
) -> dict[str, Any]:
    files = [file_record(path, site_root) for path in iter_files(site_root)]
    total_bytes = sum(item["bytes"] for item in files)
    largest = sorted(files, key=lambda item: item["bytes"], reverse=True)[:largest_count]
    forbidden = [item["path"] for item in files if is_forbidden(site_root / item["path"])]
    remaining_absolute_paths = find_remaining_absolute_paths(site_root)
    return {
        "schema": "tmem_github_pages_dashboard_report_v1",
        "site_root": site_root.name,
        "total_bytes": total_bytes,
        "total_mib": round(total_bytes / 1024**2, 2),
        "file_count": len(files),
        "copied_file_count": len(copied),
        "skipped": skipped,
        "warning_size_mib": warn_size_mb,
        "size_warning": total_bytes > warn_size_mb * 1024**2,
        "forbidden_files": forbidden,
        "remaining_absolute_paths": remaining_absolute_paths,
        "largest_files": largest,
    }


def find_remaining_absolute_paths(site_root: Path) -> list[str]:
    hits: list[str] = []
    for path in iter_files(site_root):
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if str(Path.home()) + "/" in text:
            hits.append(str(path.relative_to(site_root)))
    return hits


def sanitize_existing_text_files(site_root: Path) -> None:
    for path in iter_files(site_root):
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        sanitized = sanitize_text(text)
        if sanitized != text:
            path.write_text(sanitized, encoding="utf-8")


def write_report(site_root: Path, report: dict[str, Any]) -> None:
    (site_root / "site_size_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    with (site_root / "site_size_report.txt").open("w", encoding="utf-8") as handle:
        handle.write(f"Total size: {report['total_mib']} MiB\n")
        handle.write(f"File count: {report['file_count']}\n")
        handle.write(f"Size warning: {report['size_warning']}\n")
        handle.write(f"Forbidden files: {len(report['forbidden_files'])}\n")
        handle.write(f"Files with absolute /Users paths: {len(report['remaining_absolute_paths'])}\n\n")
        handle.write("Largest files:\n")
        for item in report["largest_files"]:
            handle.write(f"{item['bytes']:>12}  {item['path']}\n")


def print_report(report: dict[str, Any]) -> None:
    print(f"Built {report['site_root']}")
    print(f"Total size: {report['total_mib']} MiB across {report['file_count']} files")
    if report["size_warning"]:
        print(f"Warning: site exceeds {report['warning_size_mib']} MiB")
    print(f"Forbidden files present: {len(report['forbidden_files'])}")
    print(f"Files with absolute /Users paths: {len(report['remaining_absolute_paths'])}")
    print("Largest files:")
    for item in report["largest_files"]:
        print(f"  {item['bytes']:>10}  {item['path']}")


def write_pages_readme(site_root: Path) -> None:
    readme = site_root / "README.md"
    readme.write_text(
        "# TMEM106B Dashboard Site\n\n"
        "This folder is a sanitized GitHub Pages build of the local TMEM106B review dashboard. "
        "It intentionally excludes raw ND2 files, OME-TIFF files, OME-Zarr directories, MP4/GIF files, "
        "and full processed microscopy outputs.\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
