from __future__ import annotations

import numpy as np
import pytest
import tifffile as tif
from PIL import Image

from scripts.make_tracking_gif import main

MNEON_CH = 2
MCHERRY_CH = 1


def _gauss(h, w, centers, sigma=4.0, amp=6000.0):
    y, x = np.mgrid[:h, :w]
    frame = np.zeros((h, w), dtype=np.float32)
    for cy, cx in centers:
        frame += amp * np.exp(-(((y - cy) ** 2 + (x - cx) ** 2) / (2 * sigma**2)))
    return frame


def _write_stack(path, centers_per_day, h=128, w=160):
    """Write a synthetic (T, 3, H, W) TCYX stack; blobs in mNeon + weaker mCherry."""
    t = len(centers_per_day)
    stack = np.zeros((t, 3, h, w), dtype=np.uint16)
    for i, centers in enumerate(centers_per_day):
        stack[i, MNEON_CH] = _gauss(h, w, centers).astype(np.uint16)
        stack[i, MCHERRY_CH] = _gauss(h, w, centers, sigma=2.0, amp=2500.0).astype(np.uint16)
    tif.imwrite(path, stack, metadata={"axes": "TCYX"}, ome=True)
    return stack


def _drifting(t, drift=2):
    """3 well-separated blobs drifting slowly over t days (stays trackable)."""
    return [[(40 + drift * i, 40 + drift * i), (40, 120), (95, 75)] for i in range(t)]


def _stack_path(d, well="SYN"):
    return d / f"{well}_registered_common_overlap_tcyx.ome.tif"


def _base_argv(stack_dir, out_dir, well="SYN", days=(1, 2, 3, 4), extra=()):
    argv = [
        "--stack-dir",
        str(stack_dir),
        "--well",
        well,
        "--days",
        *[str(x) for x in days],
        "--output-dir",
        str(out_dir),
        "--n-cells",
        "3",
        "--fullfield-cells",
        "5",
        "--half",
        "40",
        "--duration-ms",
        "50",
    ]
    return argv + list(extra)


def _is_gif(path):
    with Image.open(path) as img:
        assert img.format == "GIF"
        return getattr(img, "n_frames", 1)


def test_cli_all_three_modes(tmp_path):
    _write_stack(_stack_path(tmp_path), _drifting(4))
    out = tmp_path / "out"
    main(_base_argv(tmp_path, out))

    montage = out / "SYN_tracking_montage.gif"
    fullfield = out / "SYN_tracking_fullfield.gif"
    assert montage.exists() and montage.stat().st_size > 0
    assert fullfield.exists() and fullfield.stat().st_size > 0
    assert _is_gif(montage) > 1  # ping-pong of 4 frames
    assert _is_gif(fullfield) > 1
    assert list(out.glob("SYN_cell*.gif"))  # per-cell gifs written


def test_cli_modes_subset(tmp_path):  # edge
    _write_stack(_stack_path(tmp_path), _drifting(4))
    out = tmp_path / "out"
    main(_base_argv(tmp_path, out, extra=("--modes", "fullfield")))

    assert (out / "SYN_tracking_fullfield.gif").exists()
    assert not (out / "SYN_tracking_montage.gif").exists()
    assert not list(out.glob("SYN_cell*.gif"))


def test_cli_percell_count(tmp_path):
    _write_stack(_stack_path(tmp_path), _drifting(4))
    out = tmp_path / "out"
    main(_base_argv(tmp_path, out, extra=("--modes", "percell")))

    gifs = list(out.glob("SYN_cell*.gif"))
    assert 1 <= len(gifs) <= 3  # capped at --n-cells
    for g in gifs:
        assert g.name.startswith("SYN_cell")
        assert _is_gif(g) >= 1


def test_cli_no_trail_runs(tmp_path):
    _write_stack(_stack_path(tmp_path), _drifting(4))
    out = tmp_path / "out"
    main(_base_argv(tmp_path, out, extra=("--modes", "montage", "--no-trail")))
    assert (out / "SYN_tracking_montage.gif").exists()


def test_cli_missing_stack(tmp_path):  # edge
    out = tmp_path / "out"
    with pytest.raises(SystemExit):
        main(_base_argv(tmp_path, out, well="NOPE"))


def test_cli_days_length_mismatch(tmp_path):  # edge
    _write_stack(_stack_path(tmp_path), _drifting(4))
    out = tmp_path / "out"
    argv = _base_argv(tmp_path, out, days=(1, 2, 3))  # 3 days vs 4 timepoints
    with pytest.raises(SystemExit):
        main(argv)


def test_cli_no_cells_tracked(tmp_path):  # edge
    # every blob moves each day, so a tiny --max-dist breaks all tracks
    centers = [
        [(40 + 5 * i, 40 + 5 * i), (60 + 5 * i, 120 - 3 * i), (100 - 4 * i, 70 + 5 * i)]
        for i in range(4)
    ]
    _write_stack(_stack_path(tmp_path), centers)
    out = tmp_path / "out"
    with pytest.raises(SystemExit, match="No cells tracked"):
        main(_base_argv(tmp_path, out, extra=("--max-dist", "0.1")))


def test_cli_half_larger_than_image(tmp_path):  # edge
    _write_stack(_stack_path(tmp_path), _drifting(4))
    out = tmp_path / "out"
    main(_base_argv(tmp_path, out, extra=("--modes", "montage", "--half", "9999")))
    assert (out / "SYN_tracking_montage.gif").exists()


def test_cli_single_timepoint(tmp_path):  # edge
    _write_stack(_stack_path(tmp_path), _drifting(1))
    out = tmp_path / "out"
    main(_base_argv(tmp_path, out, days=(1,), extra=("--modes", "montage")))
    gif = out / "SYN_tracking_montage.gif"
    assert gif.exists()
    assert _is_gif(gif) >= 1
