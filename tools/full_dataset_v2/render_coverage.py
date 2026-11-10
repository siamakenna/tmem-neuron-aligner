#!/usr/bin/env python3
"""Render receipt-derived coverage; grey slots are outside the supplied manifest."""
import argparse
import html
from pathlib import Path

from full_dataset import aggregate, atomic_json, disjoint, load


def render(manifest, output):
    disjoint(output, manifest["raw_root"])
    disjoint(output, manifest["repo"])
    summary = aggregate(manifest, hash_inputs=True)
    wells = {}
    for row in summary["tasks"]:
        wells.setdefault(row["well"], []).append(row)
    colors = {"complete": "#2da97a", "qc_failed": "#e9aa3d", "failed": "#e36d74", "pending": "#7e9bd2"}
    svg = ['<svg xmlns="http://www.w3.org/2000/svg" width="1330" height="820" viewBox="0 0 1330 820">',
           '<rect width="100%" height="100%" fill="#101826"/>',
           '<g font-family="sans-serif" fill="white">',
           f'<text x="24" y="32" font-size="22">Original-source task coverage: {summary["completed"]}/{summary["expected"]} completed</text>',
           '<text x="24" y="57" font-size="13">Green completed | amber recorded QC failures | red failed/invalid | blue pending | grey outside manifest</text>',
           '<text x="24" y="78" font-size="13">Labels show completed/expected site tasks. Completion does not certify identity or biological results.</text>']
    for col in range(1, 25):
        svg.append(f'<text x="{51+(col-1)*52}" y="110" font-size="12">{col:02}</text>')
    for ri, letter in enumerate("ABCDEFGHIJKLMNOP"):
        y = 125 + ri * 40
        svg.append(f'<text x="16" y="{y+22}" font-size="15">{letter}</text>')
        for col in range(1, 25):
            name = f"{letter}{col:02}"
            rows = wells.get(name, [])
            completed = sum(r["status"] == "completed" for r in rows)
            color = "#293346"
            if rows:
                status = "complete" if completed == len(rows) else "pending"
                if any(r["status"] in {"failed", "invalid"} for r in rows): status = "failed"
                elif any(r["qc_failed_days"] or r.get("segmentation_failed_days") or r.get("tracking_failed_days")
                         or r.get("well_registration_qc_pass") is False for r in rows): status = "qc_failed"
                color = colors[status]
            x = 40 + (col-1) * 52
            label = f"{completed}/{len(rows)}" if rows else ""
            svg.append(f'<g><title>{html.escape(name + ": " + str(rows))}</title><rect x="{x}" y="{y}" width="47" height="33" rx="4" fill="{color}"/><text x="{x+7}" y="{y+22}" font-size="12">{label}</text></g>')
    svg.append('</g></svg>')
    output = Path(output)
    output.write_text("\n".join(svg))
    atomic_json(output.with_suffix(".json"), summary)
    return summary


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    result = render(load(args.manifest), args.out)
    print(f'Coverage saved: {args.out}; completed={result["completed"]}/{result["expected"]}')
