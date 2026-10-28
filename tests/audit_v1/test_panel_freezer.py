"""Selection-only software controls; no microscopy or biological review."""

import csv
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "panel_freezer", ROOT / "scripts/freeze_diagnostic_panel.py"
)
freezer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(freezer)


@pytest.fixture
def panel(tmp_path):
    root = tmp_path / "dataset"
    root.mkdir()
    master = root / "master.csv"
    rows = [
        {
            "neuron_id": f"{w}_N{n:03d}",
            "well": w,
            "day": d,
            "time_index": i,
            "anchor_y": 64,
            "anchor_x": 64,
            "tracking_valid": False,
        }
        for w in freezer.runner.WELLS
        for n in range(101, 106)
        for i, d in enumerate(freezer.runner.DAYS)
    ]
    with master.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    inputs = {
        "master": {"path": "master.csv", "sha256": freezer.runner.sha256(master)},
        "stacks": {w: {"path": w + ".ome.tif", "sha256": "a" * 64} for w in freezer.runner.WELLS},
        "days": list(freezer.runner.DAYS),
        "channels": ["405", "561", "488"],
    }
    (root / "dataset_manifest.json").write_text(json.dumps(inputs))
    prior = tmp_path / "prior.json"
    prior.write_text(
        json.dumps(
            {
                "version": "CONTROL.v1",
                "seed": "old",
                "historical_exclusions": [
                    {"neuron_id": n, "reason": "CONTROL", "provenance": "CONTROL"}
                    for n in freezer.runner.FIXED_EXCLUSIONS
                ],
                "selected_neuron_ids": [w + "_N101" for w in freezer.runner.WELLS],
            }
        )
    )
    config = tmp_path / "config.json"
    config.write_text("{}")
    return root, prior, config, tmp_path


def test_new_policy_nonoverlap_reconstructs_without_stack_reads(panel):
    root, prior, config, tmp = panel
    out = tmp / "new.json"
    result = freezer.freeze(root, prior, "CONTROL.v2", "new", 2, config, out)
    assert len(result["selected_neuron_ids"]) == 12
    assert not set(result["selected_neuron_ids"]) & set(
        json.loads(prior.read_text())["selected_neuron_ids"]
    )
    assert result["registered_stacks_rehashed"] is False and not result["held_out_claimed"]
    # No TIFF exists in this fixture; reading a stack would fail.
    before = out.read_bytes()
    again = tmp / "again.json"
    freezer.freeze(root, prior, "CONTROL.v2", "new", 2, config, again)
    assert before == again.read_bytes()
    with pytest.raises(FileExistsError):
        freezer.freeze(root, prior, "CONTROL.v2", "new", 2, config, out)


def test_original_version_or_missing_historical_exclusion_rejected(panel):
    root, prior, config, tmp = panel
    with pytest.raises(ValueError):
        freezer.freeze(root, prior, "CONTROL.v1", "new", 2, config, tmp / "bad.json")
    data = json.loads(prior.read_text())
    data["historical_exclusions"] = []
    prior.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        freezer.freeze(root, prior, "CONTROL.v2", "new", 2, config, tmp / "bad.json")
