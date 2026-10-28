"""Portable transfer contract tests use tiny text fixtures, never microscopy data."""
from __future__ import annotations

import csv
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "prepare_portable_dataset.py"
SPEC = importlib.util.spec_from_file_location("portable_dataset", SCRIPT)
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


class PortableDataset(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.sources = self.root / "processed"
        self.sources.mkdir()
        self.master = self.sources / "master.csv"
        self.rows = []
        for well in module.WELLS:
            path = self.sources / f"{well}_registered_common_overlap_tcyx.ome.tif"
            path.write_bytes((well + " fixture, not an image").encode())
            for index, day in enumerate(module.DAYS):
                self.rows.append({"well": well, "neuron_id": well + "_N001",
                    "day": str(day), "time_index": str(index),
                    "source_registered_stack": str(path),
                    "anchor_y": "64", "anchor_x": "64", "tracking_valid": "True"})
        self.write_master()

    def write_master(self):
        out = io.StringIO(newline="")
        writer = csv.DictWriter(out, fieldnames=list(self.rows[0]))
        writer.writeheader()
        writer.writerows(self.rows)
        self.master.write_text(out.getvalue())
        self.sha = hashlib.sha256(self.master.read_bytes()).hexdigest()

    def manifest(self):
        return module.build_remote_manifest(self.master,
            expected_master_sha256=self.sha, allowed_roots=[self.sources])

    def portable(self):
        manifest = self.manifest()
        out = self.root / "dataset"
        out.mkdir()
        for record in [manifest["master"], *manifest["stacks"].values()]:
            target = out / record["path"]
            target.parent.mkdir(exist_ok=True)
            shutil.copyfile(record["source_path"], target)
        (out / "dataset_manifest.json").write_text(json.dumps(manifest))
        return out, manifest

    def update_manifest(self, out, manifest):
        (out / "dataset_manifest.json").write_text(json.dumps(manifest))

    def test_round_trip_has_all_six_wells_and_no_scientific_approval(self):
        out, manifest = self.portable()
        result = module.verify_local_dataset(out, expected_master_sha256=self.sha)
        self.assertEqual(result["status"], "verified")
        self.assertEqual(result["files_verified"], 7)
        self.assertEqual(result["master_rows"], 54)
        self.assertEqual(set(manifest["stacks"]), set(module.WELLS))
        self.assertFalse(result["scientific_inference_ready"])
        self.assertEqual(result["real_accepted_ids"], [])

    def test_remote_frozen_master_mismatch_blocks_selection(self):
        with self.assertRaisesRegex(ValueError, "checksum"):
            module.build_remote_manifest(self.master, allowed_roots=[self.sources])

    def test_source_outside_processed_roots_is_blocked(self):
        outside = self.root / "E05_registered_common_overlap_tcyx.ome.tif"
        outside.write_bytes(b"outside")
        for row in self.rows[:9]:
            row["source_registered_stack"] = str(outside)
        self.write_master()
        with self.assertRaisesRegex(ValueError, "outside"):
            self.manifest()

    def test_source_symlink_is_blocked(self):
        path = self.sources / "E05_registered_common_overlap_tcyx.ome.tif"
        moved = self.sources / "original.tif"
        path.rename(moved)
        path.symlink_to(moved)
        with self.assertRaisesRegex(ValueError, "non-symlink"):
            self.manifest()

    def test_missing_ninth_visit_is_blocked(self):
        self.rows.pop()
        self.write_master()
        with self.assertRaisesRegex(ValueError, "nine"):
            self.manifest()

    def test_duplicate_visit_is_blocked(self):
        self.rows.append(dict(self.rows[0]))
        self.write_master()
        with self.assertRaisesRegex(ValueError, "nine"):
            self.manifest()

    def test_missing_well_is_blocked(self):
        self.rows = [row for row in self.rows if row["well"] != "N05"]
        self.write_master()
        with self.assertRaisesRegex(ValueError, "N05"):
            self.manifest()

    def test_multiple_stacks_per_well_are_blocked(self):
        self.rows[0]["source_registered_stack"] = str(self.sources / "different.tif")
        self.write_master()
        with self.assertRaisesRegex(ValueError, "one registered"):
            self.manifest()

    def test_source_basename_mismatch_is_blocked(self):
        incorrect = self.sources / "wrong.tif"
        incorrect.write_bytes(b"wrong")
        for row in self.rows[:9]:
            row["source_registered_stack"] = str(incorrect)
        self.write_master()
        with self.assertRaisesRegex(ValueError, "basename"):
            self.manifest()

    def test_download_mutation_is_blocked(self):
        out, _ = self.portable()
        (out / "stacks/E05.ome.tif").write_bytes(b"tampered")
        with self.assertRaisesRegex(ValueError, "checksum/size"):
            module.verify_local_dataset(out, expected_master_sha256=self.sha)

    def test_local_path_traversal_is_blocked(self):
        out, manifest = self.portable()
        manifest["stacks"]["E05"]["path"] = "../processed/E05_registered_common_overlap_tcyx.ome.tif"
        self.update_manifest(out, manifest)
        with self.assertRaisesRegex(ValueError, "relative path"):
            module.verify_local_dataset(out, expected_master_sha256=self.sha)

    def test_local_symlink_is_blocked(self):
        out, _ = self.portable()
        path = out / "stacks/E05.ome.tif"
        path.unlink()
        path.symlink_to(self.sources / "E05_registered_common_overlap_tcyx.ome.tif")
        with self.assertRaisesRegex(ValueError, "symlinks"):
            module.verify_local_dataset(out, expected_master_sha256=self.sha)

    def test_missing_local_well_is_blocked(self):
        out, manifest = self.portable()
        del manifest["stacks"]["N05"]
        self.update_manifest(out, manifest)
        with self.assertRaisesRegex(ValueError, "six wells"):
            module.verify_local_dataset(out, expected_master_sha256=self.sha)

    def test_local_master_baseline_mismatch_is_blocked(self):
        out, _ = self.portable()
        with self.assertRaisesRegex(ValueError, "frozen baseline"):
            module.verify_local_dataset(out)

    def test_channel_order_mismatch_is_blocked(self):
        out, manifest = self.portable()
        manifest["channels"] = ["488", "561", "405"]
        self.update_manifest(out, manifest)
        with self.assertRaisesRegex(ValueError, "channel order"):
            module.verify_local_dataset(out, expected_master_sha256=self.sha)

    def test_provenance_mismatch_is_blocked(self):
        out, manifest = self.portable()
        manifest["stacks"]["E05"]["source_path"] = "/invented/source.tif"
        self.update_manifest(out, manifest)
        with self.assertRaisesRegex(ValueError, "provenance mismatch"):
            module.verify_local_dataset(out, expected_master_sha256=self.sha)

    def test_no_empty_stack_can_be_exported(self):
        (self.sources / "E05_registered_common_overlap_tcyx.ome.tif").write_bytes(b"")
        with self.assertRaisesRegex(ValueError, "empty"):
            self.manifest()

    def test_changes_during_hashing_are_blocked(self):
        path = self.sources / "E05_registered_common_overlap_tcyx.ome.tif"
        with patch.object(module, "_snapshot", side_effect=[(1, 2, 3, 4), (1, 2, 3, 5)]):
            with self.assertRaisesRegex(ValueError, "changed while hashing"):
                module._digest(path)

    def test_cli_remote_stdout_is_json_only(self):
        with patch.object(module, "build_remote_manifest", return_value=self.manifest()), \
             patch("sys.stdout", new_callable=io.StringIO) as output:
            self.assertEqual(module.main(["--remote-manifest"]), 0)
            self.assertEqual(json.loads(output.getvalue())["schema_version"], module.SCHEMA)


if __name__ == "__main__":
    unittest.main()
