"""Synthetic TIFF contracts plus integration with bound production functions."""
from copy import deepcopy
import csv
from pathlib import Path
import tempfile
import unittest

import numpy as np
import tifffile

import full_dataset as f
import preview_cellpaint_tiff as c


class CellPaintTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.inputs = self.root / "inputs"
        self.inputs.mkdir()
        self.repo = f.HERE.parents[1]
        metadata = self.inputs / "roles.csv"
        row = {"Metadata_Plate": "synthetic_plate", "Metadata_Well": "A01", "Metadata_Site": "1", "Metadata_AbsTime": "synthetic-time"}
        images = []
        for index, role in enumerate(c.ROLES):
            source_name = f"synthetic_ch{5-index}.tiff"
            path = self.inputs / source_name
            plane = np.full((16, 18), 100 * (index + 1), dtype=np.uint16)
            plane[6:10, 7:11] += 700
            tifffile.imwrite(path, plane, metadata={"axes": "YX"})
            row["FileName_Orig" + role] = source_name
            images.append({"role": role, "path": str(path), "sha256": f.digest(path), "mapping_column": "FileName_Orig" + role, "source_filename": source_name})
        # Reverse the file declaration order; reader must use explicit role labels.
        images.reverse()
        with metadata.open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(row))
            writer.writeheader()
            writer.writerow(row)
        acquisition = self.inputs / "acquisition.tsv"
        acquisition.write_text("Plate\tTimes_imaged\nsynthetic_plate\t1\n")
        self.manifest = {"schema": c.SCHEMA, "acquisition_count": 1,
            "role_metadata": {"path": str(metadata), "sha256": f.digest(metadata)},
            "acquisition_metadata": {"path": str(acquisition), "sha256": f.digest(acquisition), "delimiter": "\t", "selector": {"Plate": "synthetic_plate"}},
            "fields": [{"id": "synthetic_A01_site1", "metadata_selector": {"Metadata_Plate": "synthetic_plate", "Metadata_Well": "A01", "Metadata_Site": "1"},
                "acquisition_time": "synthetic-time", "shape_yx": [16, 18], "images": images}],
            "luts": {role: [0, 2000] for role in c.ROLES}, "processing": {"background_radius": 3, "trace_arrays": True}}

    def field(self):
        return self.manifest["fields"][0]

    def rewrite(self, array, *, axes):
        spec = self.field()["images"][0]
        tifffile.imwrite(spec["path"], array, metadata={"axes": axes})
        spec["sha256"] = f.digest(spec["path"])

    def test_explicit_role_remap_reads_every_plane(self):
        c.validate_manifest(self.manifest)
        raw = c.read_field(self.field())
        self.assertEqual(raw.shape, (5, 16, 18))
        np.testing.assert_array_equal(raw[:, 0, 0], [100, 200, 300, 400, 500])

    def test_source_hash_mismatch_rejected(self):
        Path(self.field()["images"][0]["path"]).write_bytes(b"changed original")
        with self.assertRaisesRegex(ValueError, "Source hash mismatch"):
            c.validate_manifest(self.manifest)

    def test_missing_role_rejected(self):
        self.field()["images"].pop()
        with self.assertRaisesRegex(ValueError, "five roles"):
            c.validate_manifest(self.manifest)

    def test_duplicate_role_rejected(self):
        self.field()["images"][0]["role"] = self.field()["images"][1]["role"]
        with self.assertRaisesRegex(ValueError, "five roles"):
            c.validate_manifest(self.manifest)

    def test_role_metadata_disagreement_rejected(self):
        self.field()["images"][0]["source_filename"] = "unverified_filename.tiff"
        with self.assertRaisesRegex(ValueError, "mapping disagrees"):
            c.validate_manifest(self.manifest)

    def test_shape_disagreement_rejected(self):
        self.rewrite(np.zeros((15, 18), np.uint16), axes="YX")
        with self.assertRaisesRegex(ValueError, "axes/shape"):
            c.read_field(self.field())

    def test_multidimensional_input_rejected(self):
        self.rewrite(np.zeros((2, 16, 18), np.uint16), axes="ZYX")
        with self.assertRaisesRegex(ValueError, "axes/shape"):
            c.read_field(self.field())

    def test_lzw_uint16_pixels_decode_exactly_without_dependency_install(self):
        from PIL import Image
        expected = []
        for index, role in enumerate(c.ROLES):
            spec = next(s for s in self.field()["images"] if s["role"] == role)
            plane = (np.arange(16 * 18, dtype=np.uint16).reshape(16, 18) * 137 + index).astype(np.uint16)
            Image.fromarray(plane).save(spec["path"], compression="tiff_lzw")
            spec["sha256"] = f.digest(spec["path"])
            expected.append(plane)
        c.validate_manifest(self.manifest)
        raw, backends = c.read_field(self.field(), with_backends=True)
        np.testing.assert_array_equal(raw, np.stack(expected))
        self.assertEqual(raw.dtype, np.uint16)
        self.assertEqual([r["role"] for r in backends], c.ROLES)
        self.assertTrue(all(r["backend"] == "tifffile" or "Pillow/libtiff LZW" in r["backend"] for r in backends))

    def test_multiple_acquisitions_rejected(self):
        self.manifest["acquisition_count"] = 9
        with self.assertRaisesRegex(ValueError, "single-acquisition"):
            c.validate_manifest(self.manifest)

    def test_metadata_multiple_imaging_passes_rejected(self):
        spec = self.manifest["acquisition_metadata"]
        Path(spec["path"]).write_text("Plate\tTimes_imaged\nsynthetic_plate\t2\n")
        spec["sha256"] = f.digest(spec["path"])
        with self.assertRaisesRegex(ValueError, "one imaging pass"):
            c.validate_manifest(self.manifest)

    def test_repeated_physical_field_cannot_become_temporal_visit(self):
        duplicate = deepcopy(self.field())
        duplicate["id"] += "_second_visit"
        self.manifest["fields"].append(duplicate)
        with self.assertRaisesRegex(ValueError, "physical field appears once"):
            c.validate_manifest(self.manifest)

    def test_actual_preprocess_and_render_integration(self):
        c.validate_manifest(self.manifest)
        result = c.process_field(self.manifest, self.field(), self.repo, self.root / "actual_science")
        raw = np.load(self.root / "actual_science/RAW_CYX.npy")
        processed = np.load(self.root / "actual_science/PREPROCESSED_CYX.npy")
        from tmem_align.preprocess import preprocess_image
        np.testing.assert_array_equal(processed, preprocess_image(raw, background_radius=3))
        self.assertFalse(np.array_equal(raw, processed))
        self.assertEqual(len(result["previews"]), 10)
        self.assertTrue(result["quantitative_arrays_unchanged_by_rendering"])
        stages = f.load(self.root / "actual_science/stages/STAGES.json")
        self.assertTrue(any(s.get("status") == "skipped" for s in stages))
        self.assertEqual({s["channel"] for s in stages if s.get("render_function")}, set(c.ROLES))
        self.assertTrue(all(s.get("source_provenance") for s in stages))

    def test_failure_receipt_retains_diagnostic(self):
        manifest_path = self.inputs / "manifest.json"
        self.field()["images"][0]["sha256"] = "0" * 64
        f.atomic_json(manifest_path, self.manifest)
        out = self.root / "failed_run"
        with self.assertRaisesRegex(ValueError, "Source hash mismatch"):
            c.run(manifest_path, self.repo, out)
        receipt = f.load(out / "FAILED_PRIVATE.json")
        self.assertIn("Source hash mismatch", receipt["error"])

    def test_two_distinct_fields_serial_and_two_worker_outputs_agree(self):
        second = deepcopy(self.field())
        second["id"] = "synthetic_A02_site1"
        second["metadata_selector"]["Metadata_Well"] = "A02"
        second["acquisition_time"] = "synthetic-second-field-time"
        rows, _ = c.metadata_rows(self.manifest["role_metadata"])
        second_row = dict(rows[0], Metadata_Well="A02", Metadata_AbsTime=second["acquisition_time"])
        for spec in second["images"]:
            original = Path(spec["path"])
            path = original.with_name("second_" + original.name)
            path.write_bytes(original.read_bytes())
            spec.update(path=str(path), source_filename=path.name, sha256=f.digest(path))
            second_row[spec["mapping_column"]] = path.name
        metadata = Path(self.manifest["role_metadata"]["path"])
        with metadata.open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows([rows[0], second_row])
        self.manifest["role_metadata"]["sha256"] = f.digest(metadata)
        self.manifest["fields"].append(second)
        manifest_path = self.inputs / "manifest.json"
        f.atomic_json(manifest_path, self.manifest)
        result = c.run(manifest_path, self.repo, self.root / "compared_run", compare_workers=True)
        self.assertEqual(result["status"], "passed")
        self.assertEqual(len(result["serial_two_worker_comparisons"]), 2)
        self.assertTrue(all(r["byte_equal_all_artifacts_and_results"] for r in result["serial_two_worker_comparisons"]))

    def test_outputs_must_be_disjoint_from_original_parent(self):
        manifest_path = self.inputs / "manifest.json"
        f.atomic_json(manifest_path, self.manifest)
        with self.assertRaisesRegex(ValueError, "disjoint"):
            c.run(manifest_path, self.repo, self.inputs / "forbidden-output")
        self.assertFalse((self.inputs / "forbidden-output").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
