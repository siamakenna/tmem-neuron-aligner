from __future__ import annotations

import numpy as np
from scipy.ndimage import shift as ndi_shift

from scripts.inventory_260213_dataset import parse_image_filename
from tmem_align.analysis.mcherry_metrics import quantify_mcherry_timeseries
from tmem_align.register import register_translation


def test_parse_260213_filename_metadata() -> None:
    parsed = parse_image_filename(
        "260216_Day8_iNeurons_WellF05_Channel405nm Binned,561nm Binned,488nm Binned_Seq0048.nd2"
    )
    assert parsed["well"] == "F05"
    assert parsed["day"] == 8
    assert "561nm Binned" in parsed["channel"]
    assert parsed["site"] == "Seq0048"
    assert parsed["parse_confidence"] == "high"


def test_phase_correlation_shift_recovery_on_synthetic_image() -> None:
    image = np.zeros((96, 96), dtype=np.float32)
    image[30:42, 40:52] = 1.0
    image[60:68, 18:30] = 0.8
    known_shift = (5.0, -7.0)
    moving = ndi_shift(image, shift=known_shift, order=1, mode="constant", cval=0)

    _, recovered, _ = register_translation(image, moving, upsample_factor=10)

    assert abs(recovered[0] + known_shift[0]) < 0.25
    assert abs(recovered[1] + known_shift[1]) < 0.25


def test_mcherry_metric_detects_more_diffuse_timepoint() -> None:
    y, x = np.mgrid[:96, :96]
    stable = np.exp(-(((y - 48) ** 2 + (x - 48) ** 2) / (2 * 18**2))).astype(np.float32)
    punctate = stable * 20
    diffuse = stable * 80
    for cy, cx in [(42, 42), (54, 52), (48, 60)]:
        punctate += 900 * np.exp(-(((y - cy) ** 2 + (x - cx) ** 2) / (2 * 2.0**2)))
        diffuse += 250 * np.exp(-(((y - cy) ** 2 + (x - cx) ** 2) / (2 * 2.0**2)))
    mcherry = np.stack([punctate, diffuse], axis=0)
    masks = np.stack([stable, stable], axis=0)

    df = quantify_mcherry_timeseries(mcherry, mask_stack=masks)

    assert len(df) == 2
    assert df.loc[0, "puncta_count"] >= 1
    assert df.loc[1, "diffuse_to_punctate_ratio"] > df.loc[0, "diffuse_to_punctate_ratio"]

