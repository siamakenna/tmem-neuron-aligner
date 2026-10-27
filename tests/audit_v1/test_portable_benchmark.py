"""Control/selection tests; synthetic control fixtures do not test microscopy."""
import csv
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("portable_benchmark", ROOT / "scripts" / "run_portable_benchmark.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class PortableBenchmarkTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def rows(self, well="E05", count=3):
        return [dict(neuron_id=f"{well}_N{number:03d}", well=well, day=day, time_index=i,
                     anchor_y=100, anchor_x=100, tracking_valid="False", phenotype_mean=10000 - number)
                for number in range(101, 101 + count) for i, day in enumerate(runner.DAYS)]

    def dataset(self):
        root = self.root / "dataset"
        root.mkdir()
        master = root / "master.csv"
        rows = [row for well in runner.WELLS for row in self.rows(well)]
        with master.open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        def record(path):
            return dict(path=path.name, sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        stacks = {}
        for well in runner.WELLS:
            path = root / (well + ".tif")
            path.write_bytes(b"CONTROL FIXTURE: not an image")
            stacks[well] = record(path)
        manifest = dict(schema_version="tmem.portable_dataset.v1", master=record(master), stacks=stacks,
                        days=list(runner.DAYS), channels=["405", "561", "488"])
        (root / "dataset_manifest.json").write_text(json.dumps(manifest))
        return root

    def test_selection_is_balanced_and_reproducible_without_phenotype_ranking(self):
        rows = [row for w in runner.WELLS for row in self.rows(w)]
        original = runner.select_panel(rows, 2, set())[0]
        for row in rows:
            row["phenotype_mean"] = -999
        self.assertEqual(original, runner.select_panel(list(reversed(rows)), 2, set())[0])
        self.assertEqual([n.split("_")[0] for n in original[:6]], list(runner.WELLS))
        self.assertEqual(len(original), 12)

    def test_frozen_invalid_tracking_flags_are_not_selected_away(self):
        selected, _, _ = runner.select_panel(self.rows(), 2, set())
        self.assertEqual(len(selected), 2)

    def test_exclusions_and_missing_visits_are_explicit(self):
        rows = self.rows()
        rows = [r for r in rows if not (r["neuron_id"] == "E05_N102" and r["day"] == 12)]
        selected, counts, bad = runner.select_panel(rows, 2, {"E05_N101"})
        self.assertEqual(selected, ["E05_N103"])
        self.assertEqual(counts["E05"], 1)
        self.assertIn("E05_N102", bad)

    def test_mentioned_ids_are_excluded_without_reading_binary_files(self):
        (self.root / "docs").mkdir()
        (self.root / "docs" / "history.md").write_text("Reviewed E05_N101 and N05_N221")
        (self.root / "docs" / "binary.png").write_bytes(b"F05_N123")
        excluded = runner.mentioned_ids(self.root)
        self.assertIn("N05_N221", excluded)
        self.assertIn("E05_N006", excluded)
        self.assertNotIn("F05_N123", excluded)

    def test_dataset_checksum_and_six_well_contract(self):
        dataset = self.dataset()
        _, files, rows = runner.load_dataset(dataset)
        self.assertEqual(set(files), set(runner.WELLS) | {"master"})
        self.assertEqual(len(rows), 162)
        (dataset / "E05.tif").write_bytes(b"tamper")
        with self.assertRaisesRegex(ValueError, "checksum"):
            runner.load_dataset(dataset)

    def test_public_cli_requires_frozen_real_dataset_contract(self):
        with self.assertRaises(ValueError):
            runner.verify_frozen_dataset(self.dataset())
        with patch.object(runner, "verify_frozen_dataset", side_effect=ValueError("not frozen")), \
                patch.object(runner, "execute") as execute, self.assertRaises(SystemExit) as stopped:
            runner.main(["--dataset", str(self.root), "--out", str(self.root / "output")])
        self.assertEqual(stopped.exception.code, 2)
        execute.assert_not_called()

    def test_unsafe_dataset_paths_and_symbolic_links_rejected(self):
        for value in ["../master.csv", "/tmp/master.csv", ""]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                runner.local_file(self.root, value)
        outside = self.root / "outside"
        outside.write_text("x")
        link = self.root / "link"
        link.symlink_to(outside)
        with self.assertRaisesRegex(ValueError, "symbolic"):
            runner.local_file(self.root, "link")

    def fake_case(self, nid, files, out, config, timeout):
        return dict(neuron_id=nid, status="software_completed", diagnostics=dict(valid_488_visit_count=9, core_area_px=100))

    def test_complete_execution_preserves_no_scientific_acceptance(self):
        dataset = self.dataset()
        config = self.root / "config.json"
        config.write_text("{}")
        result = runner.execute(dataset, self.root / "output", minutes=1, tracks_per_well=1,
                                config=config, case_runner=self.fake_case)
        self.assertEqual(result["status"], "completed_pending_scientific_review")
        self.assertEqual(result["execution_counts"], {"software_completed": 6})
        self.assertTrue(result["all_requested_wells_represented"])
        self.assertEqual(result["completed_well_coverage"], {well: 1 for well in runner.WELLS})
        self.assertEqual(result["real_accepted_ids"], [])
        self.assertIs(result["scientific_inference_ready"], False)
        self.assertTrue((self.root / "output" / "BENCHMARK_RESULTS.md").is_file())
        self.assertIn("prior-review history incomplete", result["panel_scope"])

    def test_one_failure_does_not_hide_other_completed_cases(self):
        dataset = self.dataset()
        config = self.root / "config.json"
        config.write_text("{}")
        def mixed(nid, *args):
            if nid.startswith("E05"):
                raise RuntimeError("deliberate CONTROL failure")
            return self.fake_case(nid, *args)
        result = runner.execute(dataset, self.root / "output", minutes=1, tracks_per_well=1,
                                config=config, case_runner=mixed)
        self.assertEqual(result["status"], "partial_or_blocked")
        self.assertEqual(result["execution_counts"], {"failed": 1, "software_completed": 5})
        self.assertTrue(result["all_selected_wells_represented"])
        self.assertFalse(result["all_requested_wells_represented"])
        self.assertEqual(result["completed_well_coverage"]["E05"], 0)

    def test_budget_defers_remaining_cases_without_submitting_them(self):
        dataset = self.dataset()
        config = self.root / "config.json"
        config.write_text("{}")
        called = []
        def slow(nid, *args):
            called.append(nid)
            time.sleep(0.08)
            return self.fake_case(nid, *args)
        # Remaining budget <1 second means no case is launched, by design.
        result = runner.execute(dataset, self.root / "output", minutes=.001, tracks_per_well=1,
                                config=config, case_runner=slow)
        self.assertEqual(called, [])
        self.assertEqual(result["execution_counts"], {"deferred_budget": 6})

    def test_run_case_timeout_is_recorded_and_partial_output_retained(self):
        class Process:
            returncode = -9
            def __init__(self): self.killed = False
            def wait(self, timeout=None):
                if not self.killed:
                    raise runner.subprocess.TimeoutExpired("CONTROL", timeout)
                return self.returncode
            def kill(self): self.killed = True
        files = {"E05": {"path": "CONTROL.tif"}, "master": {"path": "CONTROL.csv"}}
        process = Process()
        with patch.object(runner.subprocess, "Popen", return_value=process):
            result = runner.run_case("E05_N101", files, self.root, self.root / "config.json", 0.01)
        self.assertEqual(result["status"], "timeout")
        self.assertTrue(process.killed)
        self.assertEqual(result["real_accepted_ids"], [])

    def test_existing_output_is_never_overwritten(self):
        dataset = self.dataset()
        config = self.root / "config.json"
        config.write_text("{}")
        output = self.root / "output"
        output.mkdir()
        marker = output / "keep"
        marker.write_text("original")
        with self.assertRaises(FileExistsError):
            runner.execute(dataset, output, config=config, case_runner=self.fake_case)
        self.assertEqual(marker.read_text(), "original")


if __name__ == "__main__":
    unittest.main()
