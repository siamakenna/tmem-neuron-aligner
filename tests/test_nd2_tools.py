from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import tifffile

from tmem_align import nd2_tools
from tmem_align.nd2_tools import build_manifest


def test_build_manifest_empty_folder(tmp_path: Path) -> None:
    output = tmp_path / "manifest.csv"
    df = build_manifest(tmp_path, output_csv=output)
    assert df.empty
    assert output.exists()


@pytest.fixture
def constructed_nd2(monkeypatch):
    """Lazy constructed vendor-array control; not original acquisition evidence."""
    array = np.arange(2 * 2 * 2 * 3 * 4 * 5, dtype=np.uint16).reshape(2, 2, 2, 3, 4, 5)
    computes = []

    class Selected:
        def __init__(self, selected):
            self.selected = selected
            self.shape = selected.shape
            self.dtype = selected.dtype

        def compute(self):
            computes.append(True)
            return self.selected.copy()

    class Lazy:
        def __getitem__(self, indices):
            return Selected(array[indices])

    class Image:
        sizes = None

        def __init__(self, path):
            self.sizes = dict(zip("TPZCYX", array.shape, strict=True))

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def to_dask(self):
            return Lazy()

    monkeypatch.setattr(nd2_tools, "_require_nd2", lambda: SimpleNamespace(ND2File=Image))
    return array, computes


def test_extract_nd2_selection_preserves_cyx_planes_and_dtype(tmp_path, constructed_nd2):
    array, computes = constructed_nd2
    out = tmp_path / "constructed.ome.tif"
    nd2_tools.extract_nd2_selection(tmp_path / "constructed.nd2", out, position=1, time=0, z=1)
    with tifffile.TiffFile(out) as image:
        assert image.series[0].axes == "CYX"
        assert image.series[0].dtype == np.dtype("uint16")
        np.testing.assert_array_equal(image.asarray(), array[0, 1, 1])
    assert len(computes) == 1


def test_extract_nd2_selection_z_projection_is_explicit(tmp_path, constructed_nd2):
    array, _ = constructed_nd2
    out = tmp_path / "projection.ome.tif"
    nd2_tools.extract_nd2_selection(
        tmp_path / "constructed.nd2", out, position=0, time=1, max_project_z=True
    )
    with tifffile.TiffFile(out) as image:
        assert image.series[0].axes == "CYX"
        np.testing.assert_array_equal(image.asarray(), array[1, 0].max(axis=0))


@pytest.mark.parametrize("indices", [{"position": 2}, {"time": -1}, {"channel": 3}, {"z": 2}])
def test_extract_nd2_invalid_indices_fail_before_compute(tmp_path, constructed_nd2, indices):
    _, computes = constructed_nd2
    out = tmp_path / "forbidden.ome.tif"
    with pytest.raises(IndexError, match="outside"):
        nd2_tools.extract_nd2_selection(tmp_path / "constructed.nd2", out, **indices)
    assert not computes
    assert not out.exists()


def test_extract_nd2_read_memory_guard_prevents_compute(tmp_path, constructed_nd2):
    _, computes = constructed_nd2
    out = tmp_path / "forbidden.ome.tif"
    with pytest.raises(ValueError, match="max_read_bytes"):
        nd2_tools.extract_nd2_selection(
            tmp_path / "constructed.nd2", out, position=0, time=0, z=0, max_read_bytes=1
        )
    assert not computes
    assert not out.exists()


def test_extract_nd2_output_memory_guard_prevents_write(tmp_path, constructed_nd2):
    _, computes = constructed_nd2
    out = tmp_path / "forbidden.ome.tif"
    with pytest.raises(ValueError, match="max_output_bytes"):
        nd2_tools.extract_nd2_selection(
            tmp_path / "constructed.nd2", out, position=0, time=0, z=0, max_output_bytes=1
        )
    assert len(computes) == 1
    assert not out.exists()
