"""Check newly added plot semantics and output evidence without baseline reruns."""

import json
import subprocess
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pytest

from tmem_align.audit_v1.analysis_example import create_example
from tmem_align.audit_v1.matched_analysis import DAYS, analyze
from tmem_align.audit_v1.scientific_figures import (
    WATERMARK,
    generate,
    phenotype_figure,
    qc_figure,
    registration_figure,
    segmentation_figure,
    tracking_figure,
)


@pytest.fixture(scope="module")
def analysis(tmp_path_factory):
    root = tmp_path_factory.mktemp("figure-example")
    manifest = create_example(root / "input")
    analyze(manifest, root / "analysis")
    return root / "analysis"


def test_six_synthetic_examples_and_explicit_survival_block(analysis, tmp_path):
    index = generate(analysis, tmp_path / "figures", image_examples=True)
    assert set(index["figures"]) == set(map(str, range(1, 8)))
    assert index["watermark"] == WATERMARK
    assert index["synthetic_diagnostics"]["registration_error_px"] == pytest.approx(0)
    assert index["synthetic_diagnostics"]["puncta_detected"] == 3
    assert 0 < index["synthetic_diagnostics"]["segmentation_target_mask_iou"] < 1
    assert index["figures"]["6"]["files"] == []
    assert "censoring" in index["figures"]["6"]["reason"]
    for number in (1, 2, 3, 4, 5, 7):
        files = index["figures"][str(number)]["files"]
        assert len(files) == 2
        for record in files:
            assert len(record["sha256"]) == 64
            assert (tmp_path / "figures" / record["path"]).stat().st_size > 1000
    with pytest.raises(FileExistsError):
        generate(analysis, tmp_path / "figures")


def test_plot_cannot_use_mutated_analysis(analysis, tmp_path):
    import shutil

    copied = tmp_path / "tampered"
    shutil.copytree(analysis, copied)
    path = copied / "neuron_longitudinal.csv"
    path.write_text(path.read_text() + "altered")
    with pytest.raises(ValueError, match="fingerprint"):
        generate(copied, tmp_path / "no-figures")
    assert not (tmp_path / "no-figures").exists()


def test_missing_visit_breaks_trajectory_line_and_has_no_invented_value():
    table = pd.DataFrame(
        [
            {
                "neuron_id": "E05_N001",
                "day": day,
                "condition": "reporter_control",
                "mean_mcherry_intensity": np.nan if day == 16 else float(day),
                "observation_status": "missing_image" if day == 16 else "accepted",
            }
            for day in DAYS
        ]
    )
    figure = tracking_figure(table, synthetic=True)
    assert np.isnan(figure.axes[0].lines[0].get_ydata()[2])
    assert list(figure.axes[0].lines[0].get_xdata()) == list(DAYS)
    assert any(text.get_text() == WATERMARK for text in figure.texts)
    assert any("8/9" in text.get_text() for text in figure.texts)
    plt.close(figure)


def test_qc_counts_match_denominator_and_statuses_are_not_survival():
    table = pd.DataFrame(
        {
            "observation_status": ["accepted", "excluded_qc", "lost_to_followup"],
            "reason": ["", "multiple cells", "identity unavailable"],
        }
    )
    figure = qc_figure(table, synthetic=True)
    assert sum(patch.get_width() for patch in figure.axes[0].patches) == 3
    assert "denominator 3" in figure.axes[0].get_title()
    assert "survival" not in figure._suptitle.get_text().lower()
    plt.close(figure)


def test_manual_mask_cannot_be_claimed_for_synthetic_truth():
    image = np.ones((8, 8))
    mask = image.astype(bool)
    with pytest.raises(ValueError, match="Manual mask"):
        segmentation_figure(
            image,
            mask,
            mask,
            synthetic=True,
            source="synthetic",
            manual_mask={"mask": mask, "evidence": "invented"},
        )
    figure = segmentation_figure(image, mask, mask, synthetic=True, source="synthetic")
    assert "Construction truth" in figure.axes[2].get_title()
    assert any(text.get_text() == WATERMARK for text in figure.texts)
    plt.close(figure)


def test_image_panels_require_source_and_consistent_geometry():
    image = np.ones((8, 8))
    qc = {"registration_channel": "561", "dy": 0, "dx": 0, "overlap_fraction": 1}
    with pytest.raises(ValueError, match="488"):
        registration_figure(image, image, image, qc, synthetic=True, source="test")
    with pytest.raises(ValueError, match="source"):
        registration_figure(image, image, image, qc, synthetic=True, source="")
    qc["registration_channel"] = "488"
    with pytest.raises(ValueError, match="dimensions"):
        registration_figure(image, image[:2], image, qc, synthetic=True, source="test")


def test_invalid_puncta_diffuse_partition_rejected():
    image = np.ones((8, 8))
    mask = image.astype(bool)
    stages = {
        name: mask.copy()
        for name in (
            "01_phenotype_roi",
            "02_background_mask",
            "06_size_filtered_puncta",
            "08_diffuse_support",
        )
    }
    with pytest.raises(ValueError, match="partition"):
        phenotype_figure(image, stages, synthetic=True, source="synthetic")


def test_cli_rejects_empty_real_input_template_without_creating_outputs(tmp_path):
    root = Path(__file__).resolve().parents[2]
    manifest = tmp_path / "inputs.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "tmem.matched_analysis_inputs.v1",
                "evidence_type": "REAL_ACCEPTED",
                "measurement_units": {"intensity": "ADU", "area": "px2"},
                "bundles": [],
            }
        )
    )
    result = subprocess.run(
        [
            sys.executable,
            str(root / "scripts/analyze_matched_wells.py"),
            "--inputs",
            str(manifest),
            "--out",
            str(tmp_path / "out"),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 2 and "BLOCKED" in result.stderr
    assert not (tmp_path / "out").exists()
