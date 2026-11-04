"""Selection guards, including the actual legacy entry points; no pixel mocks."""
import ast
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from tmem_align.audit_v1.nd2_contracts import add_unique_well_visit, require_legacy_single_observation


def actual_function(relative, name, namespace=None):
    parsed = ast.parse((ROOT / relative).read_text())
    node = next(item for item in parsed.body if isinstance(item, ast.FunctionDef) and item.name == name)
    source = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), node], type_ignores=[])
    ast.fix_missing_locations(source)
    context = dict(namespace or {})
    exec(compile(source, str(ROOT / relative), "exec"), context)
    return context[name]


class LegacyND2Guards(unittest.TestCase):
    def test_single_observation_preserves_legacy_support(self):
        require_legacy_single_observation({"P": 1, "T": 1, "Z": 1, "C": 3, "Y": 128, "X": 128}, 1)

    def test_multiple_observation_axes_cannot_be_silently_reduced(self):
        for axis in ["P", "T", "Z"]:
            with self.subTest(axis=axis), self.assertRaisesRegex(ValueError, "Refusing implicit"):
                require_legacy_single_observation({axis: 2}, 1)

    def test_invalid_max_sites_and_axis_counts_are_rejected(self):
        for value in [0, 2, True, 1.0]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                require_legacy_single_observation({}, value)
        for value in [0, -1, True, 1.5]:
            with self.subTest(size=value), self.assertRaises(ValueError):
                require_legacy_single_observation({"P": value}, 1)

    def test_duplicate_well_day_keeps_original_and_reports_both(self):
        inventory = {}
        add_unique_well_visit(inventory, "E05", 8, "first.nd2")
        with self.assertRaisesRegex(ValueError, "first.nd2 and second.nd2"):
            add_unique_well_visit(inventory, "E05", 8, "second.nd2")
        self.assertEqual(inventory["E05"][8], "first.nd2")

    def test_actual_loader_stops_before_any_dask_or_pixel_read(self):
        class ND2:
            sizes = {"P": 2, "T": 1, "C": 3, "Y": 128, "X": 128}
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def to_dask(self): raise AssertionError("Pixel access must not happen")
        loader = actual_function("scripts/run_260213_longitudinal_pilot.py", "load_nd2_cyx")
        with patch.dict(sys.modules, {"nd2": types.SimpleNamespace(ND2File=lambda path: ND2())}):
            with self.assertRaisesRegex(ValueError, "Refusing implicit P"):
                loader(Path("CONTROL.nd2"), 1, 100)

    def test_actual_selector_rejects_duplicate_files_and_selects_unique_days(self):
        selector = actual_function("scripts/run_260213_all_wells_batch.py", "select_all_well_files",
            {"infer_day": lambda name: int(name.split("_")[0]), "infer_well": lambda name: "E05"})
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "8_first.nd2").touch()
            (root / "12_first.nd2").touch()
            self.assertEqual(len(selector(root, [8, 12])["E05"]), 2)
            (root / "8_second.nd2").touch()
            with self.assertRaisesRegex(ValueError, "Multiple ND2 files"):
                selector(root, [8, 12])


if __name__ == "__main__":
    unittest.main()
