"""Small integrations prove invalid well support/geometry stop before alignment."""
import csv
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np


SOURCE = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("well_registration_guards", SOURCE / "scripts/register_tmem_well.py")
registration = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(registration)


class StageGuardTests(unittest.TestCase):
    def assembly(self, parent, day, origin):
        root = parent / str(day)
        root.mkdir()
        (root / "geometry.json").write_text(json.dumps({
            "well": "J05", "canvas_yx": [2, 3], "origin_xy": origin, "pixel_size_um": 1.0}))
        (root / "provenance.json").write_text('{"ic_status":"not_applied"}')
        (root / "well_cyx.ome.tif").write_bytes(b"fixture path, pixels supplied by reviewed read_cyx stub")
        return root

    def run_main(self, parent, rows, coverage):
        visits = parent / "visits.csv"
        with visits.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["well", "day", "assembly_directory"])
            writer.writeheader()
            writer.writerows(rows)
        align = Mock(side_effect=AssertionError("Invalid input must never reach registration"))
        class Tiff:
            series = [SimpleNamespace(shape=(3, 2, 3), dtype=np.dtype("float32"))]
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return None
        pixels = np.stack([np.arange(6).reshape(2, 3)] * 3).astype(np.float32)
        modules = {"pandas": SimpleNamespace(),
                   "tifffile": SimpleNamespace(imread=lambda _: coverage, TiffFile=lambda _: Tiff()),
                   "run_260213_longitudinal_pilot": SimpleNamespace(register_stack=align)}
        args = ["register_tmem_well.py", "--visits", str(visits), "--well", "J05",
                "--out", str(parent / "must_not_export"), "--days", *[str(row["day"]) for row in rows]]
        with patch.dict(sys.modules, modules), patch.object(sys, "argv", args), \
             patch.object(registration, "read_cyx", return_value=pixels):
            try:
                registration.main()
            finally:
                align.assert_not_called()
                self.assertFalse((parent / "must_not_export").exists())

    def test_well_registration_rejects_missing_tile_support_before_alignment(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            folder = self.assembly(parent, 8, [0, 0])
            rows = [{"well": "J05", "day": 8, "assembly_directory": str(folder)}]
            with self.assertRaisesRegex(ValueError, "Missing tile support"):
                self.run_main(parent, rows, np.array([[1, 1, 0], [1, 1, 1]], dtype=np.uint32))

    def test_well_registration_rejects_changed_longitudinal_geometry(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent = Path(tmp)
            folders = [self.assembly(parent, 8, [0, 0]), self.assembly(parent, 12, [1, 0])]
            rows = [{"well": "J05", "day": day, "assembly_directory": str(folder)}
                    for day, folder in zip([8, 12], folders)]
            with self.assertRaisesRegex(ValueError, "Different well geometry"):
                self.run_main(parent, rows, np.ones((2, 3), dtype=np.uint32))


if __name__ == "__main__":
    unittest.main()
