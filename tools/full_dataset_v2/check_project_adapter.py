#!/usr/bin/env python3
"""Exercise the live checkout's science with known-truth synthetic ND2 readers.

These checks are separate from original-image validation and cannot establish
real-site correspondence, full-well coverage or Cell Paint portability.
"""
import argparse
import json
from pathlib import Path
import sys
from unittest.mock import patch

import numpy as np

import full_dataset as f
import project_adapter as a
from test_full_dataset import Fixture, FakeND2, ND2


def run(repo, out):
    repo = Path(repo).resolve(strict=True)
    out = f.new_directory(out, repo)
    before = f.source_binding(repo)
    a.attach_repo(repo)
    fixture = Fixture(methodName="runTest")
    fixture.setUp()
    try:
        fixture.profile["name"] = "february_neuron"
        fixture.profile["processing"]["candidate_tracking"] = True
        rng = np.random.default_rng(20261105)
        yy, xx = np.mgrid[:144, :144]
        reference = np.rint(40 + rng.uniform(0, 60, (144, 144)) +
                            1700 * np.exp(-((yy-72)**2+(xx-72)**2)/(2*8**2))).astype(np.uint16)
        expected_yx = [-3, 4]
        for path, data in FakeND2.files.items():
            day = f.parse_name(Path(path).name)[1]
            names = data["channels"]
            image = reference if day == 8 else np.roll(reference, (3, -4), (0, 1))
            canonical = {"DAPI 405": image // 3, "RFP 561": image // 2, "GFP 488": image}
            data["sizes"] = {"P": 2, "C": 3, "Y": 144, "X": 144}
            data["array"] = np.stack([np.stack([canonical[c] + p for c in names]) for p in range(2)])
        inv = f.inventory(fixture.raw, fixture.root / "large_inventory", nd2_module=ND2)
        manifest = f.make_plan(inv, fixture.mapping, fixture.profile, repo, out / "field_results", allow_subset=True)
        checks = []
        with patch.dict(sys.modules, {"nd2": ND2}):
            for task in manifest["tasks"]:
                receipt = f.run_task(manifest, task["id"])
                root = Path(manifest["out_root"]) / task["id"] / "artifacts"
                qc = f.load(root / "REGISTRATION_QC_PRIVATE.json")["visits"][1]
                from tmem_align.audit_v1.plate_preflight import PARAMETERS
                assert f.load(root / "REGISTRATION_QC_PRIVATE.json")["resolved_parameters"] == a.resolve_registration_parameters(fixture.profile, frozen=PARAMETERS)
                measured = [qc["estimated_y_shift"], qc["estimated_x_shift"]]
                np.testing.assert_allclose(measured, expected_yx, atol=0.51, rtol=0)
                assert (root / "stages/ACTUAL_IMAGE_FLOWCHART.svg").is_file()
                assert receipt["result"]["channels_checked_every_visit"]
                assert receipt["accepted_identities"] == 0
                checks.append({"id": task["id"], "known_shift_expected_yx": expected_yx,
                               "known_shift_measured_yx": measured, "accepted_identities": 0})
            summary = f.aggregate(manifest, hash_inputs=True)
            assert summary["execution_complete"] and summary["completed"] == 4
            for task in manifest["tasks"]:
                assert f.run_task(manifest, task["id"])["resumed"]
        # Actual production stitching, with asymmetric fields and known placements.
        from tmem_align.audit_v1.stitching import Tile, assemble_well
        first = np.zeros((3, 8, 10), dtype=np.uint16)
        first[:, 2, 3] = [10, 20, 30]
        second = np.zeros_like(first)
        second[:, 5, 7] = [100, 200, 300]
        mosaic, coverage, _ = assemble_well([Tile("left", first, 0, 0), Tile("right", second, 0, 10)], [8, 20])
        np.testing.assert_array_equal(mosaic[:, 2, 3], [10, 20, 30])
        np.testing.assert_array_equal(mosaic[:, 5, 17], [100, 200, 300])
        assert np.all(coverage == 1)
        # LUT rendering does not mutate source or measurement inputs.
        from tmem_align.audit_v1.display import LUT
        from tmem_align.audit_v1.visualization import propose_lut_bbox, render_preview
        original = reference.copy()
        box = propose_lut_bbox(reference, LUT(100, 2000, "488"), anchor_yx=(72, 72), range_policy="within_range")
        assert box["display_only"] and not box["adopted"]
        render_preview(reference, LUT(100, 2000, "488"))
        np.testing.assert_array_equal(reference, original)
        assert f.source_binding(repo) == before
        result = {"status": "passed", "fixture": "synthetic original-reader interface, actual bound production functions",
                  "checks": checks, "stitching_asymmetric_landmarks": True, "lut_readonly": True,
                  "exact_source_resume": True, "source_unchanged": True,
                  "real_original_nd2_pilot": False, "biological_validation": False, "source": before}
        f.atomic_json(out / "ADAPTER_VERIFICATION_PRIVATE.json", result)
        return result
    finally:
        fixture.doCleanups()


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repo", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    try:
        report = run(args.repo, args.out)
        print(json.dumps({k: v for k, v in report.items() if k != "source"}, indent=2))
    except Exception as exc:
        args.out.mkdir(parents=True, exist_ok=True)
        f.atomic_json(args.out / "ADAPTER_VERIFICATION_PRIVATE.json", {"status": "failed", "error": str(exc)})
        raise
