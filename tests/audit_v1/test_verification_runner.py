"""An empty, skipped or failed test phase cannot authorize the push gate."""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from scripts import verify_stage_pipeline as runner


class VerificationGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def xml(self, counts, *, path=None):
        path = path or self.root / "result.xml"
        path.write_text('<testsuites><testsuite ' + ' '.join(
            f'{key}="{value}"' for key, value in counts.items()) + ' /></testsuites>')
        return path

    def phase(self, counts, returncode=0):
        def completed(args, **kwargs):
            report = Path(next(value.split("=", 1)[1] for value in args
                               if value.startswith("--junitxml=")))
            self.xml(counts, path=report)
            return SimpleNamespace(returncode=returncode)
        with patch.object(runner.subprocess, "run", side_effect=completed):
            return runner.run_phase("unit", ["tests/audit_v1/test_stage_trace.py"], self.root)

    def test_actual_junit_counters_are_parsed(self):
        path = self.xml(dict(tests=9, failures=1, errors=2, skipped=3))
        self.assertEqual(runner.junit_counts(path), dict(tests=9, failures=1, errors=2, skipped=3))

    def test_nested_suite_totals_are_summed_once(self):
        path = self.root / "suites.xml"
        path.write_text('<testsuites tests="10"><testsuite tests="4" failures="0" />'
                        '<testsuite tests="6" errors="1" /></testsuites>')
        self.assertEqual(runner.junit_counts(path), dict(tests=10, failures=0, errors=1, skipped=0))

    def test_empty_and_malformed_reports_fail(self):
        path = self.root / "bad.xml"
        path.write_text('<testsuites />')
        with self.assertRaises(ValueError):
            runner.junit_counts(path)
        path.write_text('truncated <')
        with self.assertRaises(Exception):
            runner.junit_counts(path)

    def test_required_tests_cannot_be_silently_skipped_or_empty(self):
        for counts in [dict(tests=0, failures=0, errors=0, skipped=0),
                       dict(tests=4, failures=0, errors=0, skipped=1),
                       dict(tests=4, failures=1, errors=0, skipped=0),
                       dict(tests=4, failures=0, errors=1, skipped=0)]:
            with self.subTest(counts=counts), self.assertRaises(RuntimeError):
                self.phase(counts)

    def test_nonzero_runner_exit_cannot_be_hidden_by_a_clean_report(self):
        with self.assertRaises(RuntimeError):
            self.phase(dict(tests=4, failures=0, errors=0, skipped=0), returncode=2)

    def test_passing_phase_retains_its_actual_test_count(self):
        actual = self.phase(dict(tests=7, failures=0, errors=0, skipped=0))
        self.assertEqual(actual["tests"], 7)
        self.assertEqual(json.loads((self.root / "unit_result.json").read_text())["returncode"], 0)


if __name__ == "__main__":
    unittest.main()
