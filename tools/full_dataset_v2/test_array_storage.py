"""Lossless output storage contracts; all arrays and ND2 readers are synthetic."""
from copy import deepcopy
import gzip
from pathlib import Path
import unittest

import numpy as np

import full_dataset as f
import project_adapter as a
from test_full_dataset import Fixture


class ArrayStorageTests(Fixture):
    def test_uint16_gzip_roundtrip_retains_shape_dtype_and_maximum(self):
        values = np.array([[[0, 1, 65535], [32768, 50000, 42]], [[65535, 0, 3], [9, 17, 65000]]], dtype=np.uint16)
        before = values.copy()
        path = a.save_quantitative_array(self.root / "exact.npy", values, "npy.gz")
        with gzip.open(path, "rb") as stream:
            restored = np.load(stream, allow_pickle=False)
        self.assertEqual(restored.dtype, np.uint16)
        self.assertEqual(restored.shape, values.shape)
        np.testing.assert_array_equal(restored, before)
        np.testing.assert_array_equal(values, before)

    def test_compressed_bytes_deterministic_across_directory_and_filename(self):
        values = np.random.default_rng(1234).integers(0, 65536, (3, 13, 17), dtype=np.uint16)
        (self.root / "one").mkdir()
        (self.root / "two").mkdir()
        first = a.save_quantitative_array(self.root / "one/first.npy", values, "npy.gz")
        second = a.save_quantitative_array(self.root / "two/another.npy", values, "npy.gz")
        self.assertEqual(first.read_bytes(), second.read_bytes())
        self.assertEqual(f.digest(first), f.digest(second))

    def test_default_npy_filename_and_exact_values_unchanged(self):
        values = np.array([[0, 65535]], dtype=np.uint16)
        requested = self.root / "day08_preprocessed.npy"
        path = a.save_quantitative_array(requested, values)
        self.assertEqual(path, requested)
        self.assertFalse(requested.with_name(requested.name + ".gz").exists())
        np.testing.assert_array_equal(np.load(path, allow_pickle=False), values)

    def test_planner_refuses_unknown_array_storage(self):
        profile = deepcopy(self.profile)
        profile["processing"]["array_storage"] = "uint8-lossy"
        with self.assertRaisesRegex(ValueError, "array_storage must"):
            f.make_plan(self.inv, self.mapping, profile, self.repo, self.root / "rejected")

    def test_planner_binds_explicit_lossless_storage(self):
        profile = deepcopy(self.profile)
        profile["processing"]["array_storage"] = "npy.gz"
        manifest = f.make_plan(self.inv, self.mapping, profile, self.repo, self.root / "compressed")
        self.assertEqual(manifest["profile"]["processing"]["array_storage"], "npy.gz")
        self.assertNotEqual(manifest["manifest_sha256"], self.manifest["manifest_sha256"])

    def test_output_receipts_hash_compressed_file_and_detect_tampering(self):
        artifacts = self.root / "artifacts"
        artifacts.mkdir()
        path = a.save_quantitative_array(artifacts / "day08_registered.npy", np.array([[65535]], np.uint16), "npy.gz")
        receipt = {"status": "completed", "outputs": f.output_records(artifacts)}
        f.verify_completed(self.root, receipt)
        self.assertEqual(set(receipt["outputs"]), {"day08_registered.npy.gz"})
        with path.open("ab") as stream:
            stream.write(b"changed")
        with self.assertRaisesRegex(ValueError, "Missing or modified result"):
            f.verify_completed(self.root, receipt)


if __name__ == "__main__":
    unittest.main(verbosity=2)
