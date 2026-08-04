from __future__ import annotations

import numpy as np
import tifffile as tif

from tmem_align.analysis.mcherry_metrics import (
    quantify_mcherry_from_file,
    quantify_mcherry_frame,
    quantify_mcherry_timeseries,
)


def test_quantify_mcherry_from_file_tyx(tmp_path):
    arr = np.zeros((3, 64, 64), dtype=np.uint16)
    arr[:, 20:25, 20:25] = 1000
    path = tmp_path / "stack.ome.tif"
    tif.imwrite(path, arr, metadata={"axes": "TYX"}, ome=True)
    df = quantify_mcherry_from_file(path)
    assert len(df) == 3
    assert "rupture_like_score" in df.columns


def test_quantify_mcherry_from_file_yx(tmp_path):
    arr = np.zeros((64, 64), dtype=np.uint16)
    arr[20:25, 20:25] = 1000
    path = tmp_path / "frame.ome.tif"
    tif.imwrite(path, arr, metadata={"axes": "YX"}, ome=True)
    df = quantify_mcherry_from_file(path)
    assert len(df) == 1
    assert "rupture_like_score" in df.columns


def test_quantify_mcherry_timeseries_with_mask():
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


def test_quantify_mcherry_frame_foreground_area():
    frame = np.zeros((64, 64), dtype=np.float32)
    frame[18:46, 18:46] = 80
    frame[28:34, 28:34] = 1000
    result = quantify_mcherry_frame(frame)
    assert result["cell_roi_area"] > 0
    assert result["cell_roi_area"] < 64 * 64
    assert "rupture_like_score" in result
