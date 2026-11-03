"""Constructed metadata controls only, never microscope geometry approval."""

import json
import os
import stat
import subprocess
import sys
from types import SimpleNamespace
from typing import ClassVar

import numpy as np
import pytest
import tifffile

from tmem_align.audit_v1 import acquisition_inventory as inventory


def make_tiff(path, *, ome=False):
    tifffile.imwrite(
        path,
        np.arange(3 * 4 * 5, dtype=np.uint16).reshape(3, 4, 5),
        photometric="minisblack",
        ome=ome,
        metadata={"axes": "CYX", "Channel": {"Name": ["405", "561", "488"]}} if ome else None,
    )
    return path


def declaration(declaration_path, source, **updates):
    entry = {
        "path": str(source),
        "well": "E05",
        "day": 8,
        "processing_stage": "RAW_DETECTOR",
        "evidence_reference": "constructed_source_record_not_real_approval",
        "identity_source": "constructed_manifest_only",
    }
    entry.update(updates)
    declaration_path.write_text(
        json.dumps({"schema_version": inventory.DECLARATIONS, "sources": [entry]})
    )
    return declaration_path


def test_empty_and_missing_roots_are_distinct(tmp_path):
    empty = inventory.build_inventory([tmp_path])
    assert empty["scan_complete"]
    assert not empty["sources"]
    assert len(empty["source_coverage"]) == 54
    assert {r["assembly_status"] for r in empty["source_coverage"]} == {"MISSING_SOURCE"}
    missing = inventory.build_inventory([tmp_path / "missing"])
    assert not missing["scan_complete"]
    assert missing["roots"][0]["errors"] == ["MISSING_ROOT"]
    assert {r["assembly_status"] for r in missing["source_coverage"]} == {"DEFERRED"}


def test_unreadable_root_walk_error_is_retained(tmp_path, monkeypatch):
    def denied(root, *, followlinks, onerror):
        assert followlinks is False
        onerror(PermissionError("CONTROL inaccessible source"))
        return iter(())

    monkeypatch.setattr(inventory.os, "walk", denied)
    report = inventory.build_inventory([tmp_path])
    assert not report["scan_complete"]
    assert "inaccessible" in report["roots"][0]["errors"][0]


def test_file_root_is_not_a_directory(tmp_path):
    path = make_tiff(tmp_path / "field.tif")
    result = inventory.scan_roots([path])
    assert result[1][0]["errors"] == ["ROOT_MUST_BE_DIRECTORY"]
    assert result[3] is False


def test_symlink_files_directories_roots_and_ancestors_not_followed(tmp_path):
    original = tmp_path / "original"
    original.mkdir()
    make_tiff(original / "field.tif")
    linked = tmp_path / "linked"
    linked.symlink_to(original, target_is_directory=True)
    file_link = tmp_path / "field-link.tif"
    file_link.symlink_to(original / "field.tif")
    report = inventory.build_inventory([tmp_path])
    assert len(report["sources"]) == 1
    assert len(report["skipped"]) == 2
    for root in [linked, linked / "child"]:
        result = inventory.build_inventory([root])
        assert not result["sources"]
        assert not result["scan_complete"]
        assert "SYMLINK" in result["roots"][0]["errors"][0]


def test_overlapping_roots_extensions_cache_and_limit(tmp_path):
    nested = tmp_path / "nested"
    nested.mkdir()
    make_tiff(nested / "A.TIFF")
    make_tiff(nested / "B.OME.TIF")
    cache = tmp_path / ".venv-fixture"
    cache.mkdir()
    make_tiff(cache / "package-example.tif")
    result = inventory.build_inventory([tmp_path, nested])
    assert len(result["sources"]) == 2
    assert all(len(r["root_ids"]) == 2 for r in result["sources"])
    assert result["scan_complete"]
    limited = inventory.build_inventory([tmp_path], max_files=1)
    assert len(limited["sources"]) == 1
    assert not limited["scan_complete"]
    assert "TRUNCATED" in limited["roots"][0]["errors"][0]
    assert {r["assembly_status"] for r in limited["source_coverage"]} == {"DEFERRED"}


@pytest.mark.parametrize("limit", [0, -1, True, 1.5])
def test_invalid_limit_rejected(tmp_path, limit):
    with pytest.raises(ValueError, match="positive integer"):
        inventory.build_inventory([tmp_path], max_files=limit)


def test_nd2_header_never_reads_pixels_or_fabricates_names(tmp_path, monkeypatch):
    class FakeND2:
        sizes: ClassVar = {"P": 2, "C": 2, "Y": 4, "X": 5}
        shape = (2, 2, 4, 5)
        dtype = np.dtype("uint16")
        is_rgb = False
        metadata = SimpleNamespace(
            channels=[
                SimpleNamespace(channel=SimpleNamespace(name="488 named", index=0)),
                SimpleNamespace(channel=SimpleNamespace(name=None, index=1)),
            ]
        )

        def __init__(self, path):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def voxel_size(self):
            return SimpleNamespace(x=0.6, y=0.6, z=float("nan"))

        def frame_metadata(self, index):
            assert index == 0
            position = SimpleNamespace(stagePositionUm=SimpleNamespace(x=1, y=2, z=3))
            return SimpleNamespace(channels=[SimpleNamespace(position=position)])

        def asarray(self):
            pytest.fail("Inventory must not read pixels")

        def to_dask(self):
            pytest.fail("Inventory must not create pixel computation")

    monkeypatch.setitem(sys.modules, "nd2", SimpleNamespace(ND2File=FakeND2))
    path = tmp_path / "WellF05_Day39.ND2"
    path.write_bytes(b"CONTROL nonimage stub")
    report = inventory.build_inventory([tmp_path])
    record = report["sources"][0]
    header = record["metadata"]
    assert header["axes"] == "PCYX"
    assert header["position_count"] == 2
    assert [c["name"] for c in header["channels"]] == ["488 named", None]
    assert header["reported_voxel_size"] == {"x_um": 0.6, "y_um": 0.6, "z_um": None}
    assert header["frame_0_stage"]["stage_x_um"] == 1
    assert "NOT_ALL_SITE" in header["stage_map_status"]
    assert record["identity"] is None
    assert record["processing_stage"] == "UNKNOWN"
    assert record["filename_hints"]["well"] == "F05"
    assert {r["assembly_status"] for r in report["source_coverage"]} == {"DEFERRED"}
    assert record["intensity_range"] == "NOT_MEASURED_METADATA_ONLY"
    assert record["source_id_basis"] == "PATH_NOT_CONTENT_HASH"


def test_missing_nd2_dependency_and_corrupt_tiff_are_reported(tmp_path, monkeypatch):
    (tmp_path / "broken.nd2").write_bytes(b"CONTROL")
    (tmp_path / "broken.tif").write_bytes(b"CONTROL")
    monkeypatch.setitem(sys.modules, "nd2", None)
    report = inventory.build_inventory([tmp_path])
    assert len(report["sources"]) == 2
    assert {r["inspection_status"] for r in report["sources"]} == {"HEADER_ERROR"}
    assert "ModuleNotFoundError" in next(
        r["error"] for r in report["sources"] if r["file_type"] == "ND2"
    )
    assert inventory.aggregate(report)["assemblies_verified_here"] == 0


def test_nd2_missing_optional_metadata_stays_unavailable(tmp_path, monkeypatch):
    class Minimal:
        sizes: ClassVar = {"Y": 4, "X": 5}
        shape = (4, 5)
        dtype = "uint16"
        is_rgb = False
        metadata = SimpleNamespace(channels=[])

        def __init__(self, path):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def voxel_size(self):
            raise ValueError("CONTROL unavailable")

        def frame_metadata(self, index):
            raise ValueError("CONTROL unavailable")

    monkeypatch.setitem(sys.modules, "nd2", SimpleNamespace(ND2File=Minimal))
    result = inventory.inspect_nd2_header(tmp_path / "fake.nd2")
    assert result["channels"] == []
    assert result["channel_identity_status"] == "UNAVAILABLE"
    assert result["calibration_status"] == "UNAVAILABLE"
    assert result["frame_0_stage"]["stage_coordinate_source"] == "UNAVAILABLE"


def test_tiff_multi_series_and_ome_metadata_without_pixels(tmp_path, monkeypatch):
    ome = make_tiff(tmp_path / "field.ome.tif", ome=True)
    multi = tmp_path / "multi.tif"
    with tifffile.TiffWriter(multi) as writer:
        writer.write(np.zeros((4, 5), dtype=np.uint16))
        writer.write(np.zeros((7, 8), dtype=np.uint8))
    monkeypatch.setattr(tifffile.TiffFile, "asarray", lambda *a, **k: pytest.fail("No pixel reads"))
    monkeypatch.setattr(tifffile, "imread", lambda *a, **k: pytest.fail("No pixel reads"))
    result = inventory.inspect_tiff_header(ome)
    assert result["series"][0]["axes"] == "CYX"
    assert [c["Name"] for c in result["ome_pixels"][0]["channels"]] == ["405", "561", "488"]
    generic = inventory.inspect_tiff_header(multi)
    assert len(generic["series"]) == 2
    assert generic["ome_pixels"] == []
    assert generic["acquisition_axes_status"] == "UNAVAILABLE"


def test_source_mutation_during_header_inspection_fails_closed(tmp_path, monkeypatch):
    p = tmp_path / "field.tif"
    p.write_bytes(b"CONTROL")

    def changed(path):
        path.write_bytes(b"CONTROL changed source")
        return {}

    monkeypatch.setattr(inventory, "inspect_tiff_header", changed)
    source = inventory.build_inventory([tmp_path])["sources"][0]
    assert source["inspection_status"] == "HEADER_ERROR"
    assert "Source changed" in source["error"]


def test_declared_raw_coverage_is_not_geometry_or_assembly_approval(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    source = make_tiff(root / "field.tif")
    decl = declaration(tmp_path / "declaration.json", source, site_id="field_0")
    report = inventory.build_inventory([root], declarations=decl)
    row = next(r for r in report["source_coverage"] if r["well"] == "E05" and r["day"] == 8)
    assert row["header_read_raw_source_count"] == 1
    assert row["assembly_status"] == "MISSING_GEOMETRY"
    assert len(report["source_coverage"]) == 54
    assert report["sources"][0]["identity"]["status"] == "DECLARED_NOT_INDEPENDENTLY_VALIDATED"
    assert inventory.aggregate(report)["declared_raw_coverage_count"] == 1
    assert inventory.aggregate(report)["assemblies_verified_here"] == 0
    assert not {r["assembly_status"] for r in report["source_coverage"]} & {
        "COMPLETE_AND_VERIFIED",
        "ASSEMBLED_PENDING_REVIEW",
    }


def test_registered_declaration_cannot_replace_original(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    source = make_tiff(root / "WellE05_Day8_registered.ome.tif", ome=True)
    decl = declaration(tmp_path / "decl.json", source, processing_stage="REGISTERED")
    report = inventory.build_inventory([root], declarations=decl)
    assert inventory.aggregate(report)["declared_raw_coverage_count"] == 0
    assert {r["assembly_status"] for r in report["source_coverage"]} == {"MISSING_SOURCE"}


@pytest.mark.parametrize(
    "updates",
    [
        {"well": "Z99"},
        {"day": True},
        {"day": 9},
        {"processing_stage": "TRUST_ME"},
        {"identity_source": ""},
        {"evidence_reference": " "},
        {"extra": 1},
        {"site_id": ""},
        {"derived_from": "not-list"},
        {"derived_from": ["missing.tif"]},
        {"path": "missing.tif"},
    ],
)
def test_invalid_declarations_fail(tmp_path, updates):
    source = make_tiff(tmp_path / "field.tif")
    decl = declaration(tmp_path / "decl.json", source, **updates)
    with pytest.raises(ValueError):
        inventory.build_inventory([tmp_path], declarations=decl)


def test_duplicate_and_self_reference_declarations_fail(tmp_path):
    source = make_tiff(tmp_path / "field.tif")
    decl = declaration(tmp_path / "decl.json", source)
    doc = json.loads(decl.read_text())
    doc["sources"].append(doc["sources"][0])
    decl.write_text(json.dumps(doc))
    with pytest.raises(ValueError, match="duplicate"):
        inventory.build_inventory([tmp_path], declarations=decl)
    declaration(decl, source, derived_from=[str(source)])
    with pytest.raises(ValueError, match="self"):
        inventory.build_inventory([tmp_path], declarations=decl)


@pytest.mark.parametrize("document", [{}, [], {"schema_version": "wrong", "sources": []}])
def test_invalid_declaration_schema(tmp_path, document):
    decl = tmp_path / "decl.json"
    decl.write_text(json.dumps(document))
    with pytest.raises(ValueError):
        inventory.build_inventory([tmp_path], declarations=decl)


def test_private_outputs_permissions_nonoverwrite_and_path_free_summary(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    make_tiff(root / "private_field.tif")
    out = tmp_path / "out"
    report = inventory.run([root], out)
    assert stat.S_IMODE(out.stat().st_mode) == 0o700
    assert {p.name for p in out.iterdir()} == {
        "acquisition_inventory.json",
        "source_coverage.csv",
        "source_coverage_summary.json",
    }
    assert all(stat.S_IMODE(p.stat().st_mode) == 0o600 for p in out.iterdir())
    summary = json.dumps(inventory.aggregate(report))
    assert str(tmp_path) not in summary
    assert "private_field" not in summary
    assert len((out / "source_coverage.csv").read_text().splitlines()) == 55
    with pytest.raises(ValueError):
        inventory.run([root], out)
    with pytest.raises(ValueError):
        inventory.run([root], root / "new-output")
    with pytest.raises(ValueError):
        inventory.run([root], inventory.REPO / "unsafe-output-control")


def test_cli_missing_input_emits_partial_private_report(tmp_path):
    out = tmp_path / "out"
    command = [
        sys.executable,
        str(inventory.REPO / "scripts/inventory_acquisition_sources.py"),
        "--root",
        str(tmp_path / "missing"),
        "--out",
        str(out),
    ]
    result = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    assert result.returncode == 1
    assert '"scan_complete": false' in result.stdout
    assert (out / "acquisition_inventory.json").is_file()
