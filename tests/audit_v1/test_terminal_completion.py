"""Operating controls; constructed fixtures are not original microscopy evidence."""
from importlib.util import module_from_spec, spec_from_file_location
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[2]
spec = spec_from_file_location("terminal_completion", ROOT / "scripts/run_terminal_completion.py")
runner_module = module_from_spec(spec)
spec.loader.exec_module(runner_module)


def temporary_directory():
    # This sandbox may have no writable system TMPDIR; stay outside source.
    return tempfile.TemporaryDirectory(dir=ROOT.parent)


def header(**sizes):
    return {"sizes": {"C": 3, "Y": 8, "X": 9, **sizes},
            "channel_names": ["405 nm", "561 nm", "488 nm"]}


class TerminalSelectionControls(unittest.TestCase):
    def test_singletons_are_explicitly_reduced_and_channels_retained(self):
        self.assertEqual(runner_module.check_selection(header(P=1, T=1, Z=1), {}),
                         {"position": 0, "time": 0, "z": 0})

    def test_multisite_never_implicitly_selects_zero(self):
        with self.assertRaisesRegex(ValueError, "Explicit position"):
            runner_module.check_selection(header(P=4), {})
        self.assertEqual(runner_module.check_selection(header(P=4), {"position": 2})["position"], 2)

    def test_projection_unsupported_axes_and_false_indices_are_rejected(self):
        for h, selected in [(header(P=1), {"position": True}), (header(S=1), {}),
                            (header(T=2), {"time": 2}), (header(), {"z": 1})]:
            with self.subTest(header=h, selected=selected), self.assertRaises(ValueError):
                runner_module.check_selection(h, selected)

    def test_named_channel_order_must_match_current_pipeline(self):
        h = header()
        h["channel_names"] = ["405", "488", "561"]
        with self.assertRaisesRegex(ValueError, "channel order"):
            runner_module.check_selection(h, {})


class TerminalReceiptControls(unittest.TestCase):
    def test_junit_zero_execution_and_skips_never_pass(self):
        with temporary_directory() as temporary:
            path = Path(temporary) / "tests.xml"
            for tests, skipped in [(0, 0), (3, 1)]:
                path.write_text(f'<testsuites><testsuite tests="{tests}" failures="0" errors="0" skipped="{skipped}"/></testsuites>')
                with self.assertRaises(ValueError):
                    runner_module.junit_counts(path)
            path.write_text('<testsuites><testsuite tests="3" failures="0" errors="0" skipped="0"/></testsuites>')
            self.assertEqual(runner_module.junit_counts(path)["tests"], 3)

    def test_private_output_cannot_overlap_source_or_raw(self):
        with self.assertRaises(ValueError):
            runner_module.require_new_output(ROOT / "outputs/forbidden")
        with temporary_directory() as temporary:
            raw = Path(temporary) / "originals"
            raw.mkdir()
            with self.assertRaises(ValueError):
                runner_module.require_new_output(raw / "analysis", raw)

    def test_packet_must_not_claim_delivery(self):
        with temporary_directory() as temporary:
            path = Path(temporary) / "stress.zip"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("PROVENANCE.json", json.dumps({"delivery_status": "sent"}))
            with self.assertRaises(ValueError):
                runner_module.packet_verified(path)

    def test_actual_child_failure_is_recorded_with_log(self):
        with temporary_directory() as temporary:
            runner = runner_module.Runner(Path(temporary), 10)
            record = runner.step("constructed_failure", [sys.executable, "-c", "print('CONTROL');raise SystemExit(7)"])
            self.assertEqual(record["returncode"], 7)
            self.assertEqual(record["status"], "failed")
            self.assertIn("CONTROL", (Path(temporary) / record["log"]).read_text())


class FakeRunner:
    history = []
    fail_production = False
    fail_graphics = False

    def __init__(self, out, timeout):
        self.out = Path(out)
        self.history = FakeRunner.history

    def step(self, name, command):
        self.history.append(name)
        success = not ((name == "production_unit_then_integration" and self.fail_production)
                       or (name == "workflow_graphics" and self.fail_graphics))
        if name == "production_unit_then_integration" and success:
            directory = self.out / "production_verification"
            directory.mkdir()
            (directory / "verification_status.json").write_text(json.dumps({
                "status": "passed", "unit_tests_passed": True, "integration_tests_passed": True,
                "tests": 4, "skipped": 0, "failures": 0, "errors": 0}))
        return {"status": "passed" if success else "failed", "returncode": 0 if success else 1,
                "command": list(map(str, command)), "log": "logs/constructed.log"}


class TerminalWorkflowControls(unittest.TestCase):
    def setUp(self):
        FakeRunner.history = []
        FakeRunner.fail_production = FakeRunner.fail_graphics = False

    def execute(self, out, hashes=None, extra=None):
        with patch.object(runner_module, "Runner", FakeRunner), \
             patch.object(runner_module, "run_pytest", return_value={"tests": 3, "skipped": 0}), \
             patch.object(runner_module, "graphics_verified"), \
             patch.object(runner_module, "packet_verified"), \
             patch.object(runner_module, "code_hashes", side_effect=hashes or [{"source": "a"}, {"source": "a"}]), \
             patch.object(runner_module, "environment", return_value={"constructed": True}):
            code = runner_module.main(["--out", str(out), *(extra or [])])
        return code, json.loads((out / "RUN_STATUS.json").read_text())

    def test_software_success_without_originals_stays_scientifically_pending(self):
        with temporary_directory() as temporary:
            code, status = self.execute(Path(temporary) / "private")
        self.assertEqual(code, 2)
        self.assertTrue(status["software_checks_passed"])
        self.assertTrue(status["source_unchanged"])
        self.assertFalse(status["original_nd2_used"])
        self.assertFalse(status["whole_well_validation_granted"])
        self.assertFalse(status["scientific_inference_ready"])
        self.assertEqual(status["claire_delivery_status"], "not_sent")

    def test_graphics_and_packet_are_attempted_before_production_failure(self):
        FakeRunner.fail_production = True
        with temporary_directory() as temporary:
            code, status = self.execute(Path(temporary) / "private")
        self.assertEqual(FakeRunner.history[:2], ["workflow_graphics", "claire_stress_packet"])
        self.assertEqual(code, 1)
        self.assertFalse(status["software_checks_passed"])
        self.assertTrue(status["workflow_graphics_generated"])
        self.assertTrue(status["claire_stress_packet_prepared"])

    def test_failed_graphics_does_not_prevent_packet_or_independent_checks(self):
        FakeRunner.fail_graphics = True
        with temporary_directory() as temporary:
            code, status = self.execute(Path(temporary) / "private")
        self.assertEqual(code, 2)
        self.assertTrue(status["software_checks_passed"])
        self.assertFalse(status["workflow_graphics_generated"])
        self.assertTrue(status["claire_stress_packet_prepared"])

    def test_source_change_invalidates_software_certification(self):
        with temporary_directory() as temporary:
            code, status = self.execute(Path(temporary) / "private", [{"source": "a"}, {"source": "b"}])
        self.assertEqual(code, 1)
        self.assertFalse(status["software_checks_passed"])
        self.assertFalse(status["source_unchanged"])
        self.assertIn("changed", status["error"])

    def test_existing_trace_render_does_not_claim_original_pixels_or_rerun_benchmark(self):
        with temporary_directory() as temporary:
            code, status = self.execute(Path(temporary) / "private", extra=["--existing-trace", str(Path(temporary) / "old_trace")])
        self.assertEqual(code, 2)
        self.assertIn("existing_trace_graphics_0", FakeRunner.history)
        self.assertFalse(status["original_nd2_used"])
        self.assertEqual(len(status["existing_trace_graphics"]), 1)
        self.assertFalse(any("benchmark" in step for step in FakeRunner.history))

    def test_same_original_cannot_make_a_trivial_self_alignment(self):
        with self.assertRaisesRegex(ValueError, "distinct original"):
            runner_module.main(["--out", "/unused", "--reference-nd2", "same.nd2", "--moving-nd2", "same.nd2"])


if __name__ == "__main__":
    unittest.main()
