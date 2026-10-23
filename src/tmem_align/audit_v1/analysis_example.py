"""Build small, explicitly synthetic accepted-export bundles for examples/tests.

Test review assignments exercise software only and are never human observations.
"""

from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path

import numpy as np
from PIL import Image

from .matched_analysis import CONDITIONS, DAYS, ROSTER_FIELDS, SYNTHETIC
from .reference import phenotype_steps


def source_script(name):
    path = Path(__file__).resolve().parents[3] / "scripts" / name
    spec = importlib.util.spec_from_file_location(f"friday_{path.stem}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_csv(path, rows, fields=None):
    with Path(path).open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields or list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def create_example(root):
    """Use the real workspace builder/exporter; all simulated decisions say AUTOMATED."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=False)
    curated = root / "curated"
    curated.mkdir()
    # Two control neurons with deliberately unequal values test equal-well weights.
    ids = ["E05_N001", "E05_N002", "F05_N001", "I05_N001", "J05_N001", "M05_N001", "N05_N001"]
    y, x = np.mgrid[:128, :128]
    core = (y - 64) ** 2 + (x - 64) ** 2 <= 7**2
    roi = (y - 64) ** 2 + (x - 64) ** 2 <= 9**2
    base488 = 20 + 1800 * np.exp(-((y - 64) ** 2 + (x - 64) ** 2) / 50)
    raw561 = 40 + 100 * np.exp(-((y - 64) ** 2 + (x - 64) ** 2) / 110)
    for cy, cx in ((61, 61), (67, 67)):
        raw561 += 1000 * np.exp(-((y - cy) ** 2 + (x - cx) ** 2) / 3)
    for index, nid in enumerate(ids):
        folder = curated / nid
        folder.mkdir()
        boxes = np.zeros((9, 3, 128, 128), dtype=np.uint16)
        boxes[:, 0] = 20
        boxes[:, 2] = base488.astype(np.uint16)
        metrics, tracks = [], []
        factor = 1.0 + index * 0.15
        for i, day in enumerate(DAYS):
            boxes[i, 1] = np.rint(raw561 * factor * (1 + 0.04 * i)).astype(np.uint16)
            (values, _, _, _), _ = phenotype_steps(boxes[i, 1], roi)
            metrics.append(
                dict(
                    neuron_id=nid,
                    well=nid[:3],
                    day=day,
                    adaptive_valid=True,
                    single_soma_pass=True,
                    review="SYNTHETIC_SOFTWARE_FIXTURE",
                    **values,
                )
            )
            tracks.append(
                {
                    "neuron_id": nid,
                    "well": nid[:3],
                    "day": day,
                    "tracking_valid": True,
                    "global_reg_qc_pass": True,
                    "global_reg_well_registration_qc_pass": True,
                }
            )
        np.savez_compressed(
            folder / "small_fixture.npz",
            boxes_tcyx=boxes,
            identity_core=core,
            phenotype_roi=roi,
            adaptive_masks=np.repeat(core[None], 9, axis=0),
            adaptive_valid=np.ones(9, dtype=bool),
        )
        write_csv(folder / "metrics.csv", metrics)
        write_csv(folder / "fixture_tracks.csv", tracks)
        write_json(
            folder / "parameters.json",
            {
                "bbox_size": 128,
                "identity_consensus_fraction": 0.6,
                "phenotype_dilation": 2,
                "segmentation_min_area": 180,
                "min_core_area": 80,
                "max_core_area": 2500,
                "background_exclusion": 8,
                "puncta_min_size": 6,
                "evidence_type": SYNTHETIC,
            },
        )
        write_json(
            folder / "luts.json",
            {
                channel: {
                    "low": 0,
                    "high": 3000,
                    "color": channel,
                    "source": "SYNTHETIC prescribed limits",
                    "scope": "fixed-longitudinal-per-neuron",
                }
                for channel in ("488", "561")
            },
        )
        for day in DAYS:
            target = folder / f"day_{day:02d}"
            target.mkdir()
            # Compact source diagnostic placeholder, explicitly synthetic, not a manual mask.
            Image.fromarray((core * 255).astype(np.uint8)).save(target / "four_panel.png")
    config = {
        "schema_version": "tmem.display_review.v2",
        "neuron_ids": ids,
        "preserve_saved_reference_luts": True,
        "reference_lut": {
            "source": "reference_bbox",
            "low_percentile": 1.0,
            "high_percentile": 99.6,
        },
        "candidate_lut": {"source": "roi_fixed", "low_percentile": 1.0, "high_percentile": 99.6},
        "bbox_policy": "SYNTHETIC 488-derived geometry; display only LUTs",
        "ic_policy": "not_applied",
        "known_exclusions": {},
        "biological_pairs": [["E05", "F05"], ["I05", "J05"], ["M05", "N05"]],
        "review_scope": "SYNTHETIC EXAMPLE — NOT EXPERIMENTAL RESULTS",
    }
    write_json(root / "config.json", config)
    source_script("build_review_workspace.py").build(
        curated, root / "config.json", root / "workspace"
    )
    review = json.loads((root / "workspace/review/manual_review_template.json").read_text())
    review.update(
        reviewer="AUTOMATED SYNTHETIC SOFTWARE TEST — NOT HUMAN REVIEW",
        reviewed_at="2026-10-22T12:00:00+00:00",
    )
    for track in review["tracks"]:
        track["track_decision"] = "accept"
        for visit in track["visits"]:
            for criterion in ("identity_488", "roi_purity_488", "phenotype_qc_561"):
                visit[criterion] = "pass"
    write_json(root / "synthetic_test_review.json", review)
    exporter = source_script("export_reviewed_metrics.py")
    code = exporter.export(
        curated,
        root / "synthetic_test_review.json",
        root / "config.json",
        root / "export",
        workspace=root / "workspace",
    )
    if code != 0:
        raise RuntimeError("Synthetic exporter demonstration failed")
    rows = [
        {
            "neuron_id": nid,
            "well": nid[:3],
            "day": day,
            "condition": CONDITIONS[nid[:3]],
            "observation_status": "accepted",
            "cell_fate": "not_classified",
            "reason": "",
            "source_reference": "SYNTHETIC automated fixture; not human review",
        }
        for nid in ids
        for day in DAYS
    ]
    # An additional never-accepted track demonstrates missingness, not survival.
    for i, day in enumerate(DAYS[:-1]):
        status = (
            "excluded_qc",
            "pending_review",
            "lost_to_followup",
            "uncertain_identity",
            "missing_image",
            "failed_measurement",
            "excluded_qc",
            "pending_review",
        )[i]
        rows.append(
            {
                "neuron_id": "I05_N099",
                "well": "I05",
                "day": day,
                "condition": "reporter_control",
                "observation_status": status,
                "cell_fate": "not_classified",
                "reason": f"synthetic_{status}",
                "source_reference": "SYNTHETIC status demonstration",
            }
        )
    write_csv(root / "cohort_status.csv", rows, ROSTER_FIELDS)
    write_json(
        root / "decision_policy.json",
        {
            "schema_version": "tmem.analysis_decisions.v1",
            "evidence_type": SYNTHETIC,
            "excluded_neuron_ids": {},
            "pending_identity_resolution": [],
            "evidence_files": [],
        },
    )
    manifest = {
        "schema_version": "tmem.matched_analysis_inputs.v1",
        "evidence_type": SYNTHETIC,
        "measurement_units": {"intensity": "synthetic_ADU", "area": "px2"},
        "cohort_status_csv": "cohort_status.csv",
        "decision_policy": "decision_policy.json",
        "bundles": [
            {
                "export": "export",
                "curated": "curated",
                "config": "config.json",
                "reviews": "synthetic_test_review.json",
                "workspace": "workspace",
            }
        ],
    }
    write_json(root / "analysis_inputs.json", manifest)
    return root / "analysis_inputs.json"
