"""Portable orchestration contracts without recursively invoking the full suite."""
import ast
import csv
import importlib.util
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch


SOURCE = Path(__file__).resolve().parents[2]
SCRIPT = SOURCE / "scripts/run_claire_verification.py"
SPEC = importlib.util.spec_from_file_location("claire_verifier_under_test", SCRIPT)
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


def write_manifest(root):
    entries = sorted(p for p in root.rglob("*")
                     if p.is_file() and p.name != "SHA256SUMS"
                     and not runner.generated_file(p.relative_to(root)))
    (root / "SHA256SUMS").write_text("".join(
        f"{runner.digest(p)}  {p.relative_to(root).as_posix()}\n" for p in entries))


def fixture(root):
    for name in ["source/pyproject.toml", "source/scripts/run_tmem_audit.py",
                 "source/scripts/export_reviewed_metrics.py",
                 "source/configs/tmem_review_v6.json", "review/manual_review_template.json"]:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}\n")
    shutil.copyfile(SCRIPT, root / "source/scripts/run_claire_verification.py")
    with (root / "stress_results.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["case", "mode", "availability_status", "test_node"])
        writer.writeheader()
        writer.writerows([
            {"case": "automatic", "mode": "automated", "availability_status": "runnable",
             "test_node": "tests/test_fake.py::Checks::test_pass"},
            {"case": "human", "mode": "manual", "availability_status": "runnable", "test_node": ""},
            {"case": "original_stitch", "mode": "manual", "availability_status": "blocked_missing_real_input",
             "test_node": ""},
        ])
    matrix = root / "source/docs/audit_v1/claire_stress_cases.csv"
    matrix.parent.mkdir(parents=True)
    shutil.copyfile(root / "stress_results.csv", matrix)
    write_manifest(root)


def fake_stage(name, command, source, out, env, stages, expected_exit=0):
    stages.append({"stage": name, "command": command, "returncode": expected_exit,
                   "expected_returncode": expected_exit, "passed": True})
    (out / f"{name}.log").write_text("1 passed in 0.01s\n")
    if name == "all_tests":
        (out / "all_tests.xml").write_text('<testsuites><testsuite tests="1" failures="0" '
            'errors="0" skipped="0"><testcase classname="tests.test_fake.Checks" '
            'name="test_pass"/></testsuite></testsuites>')
    if name == "synthetic":
        root = out / "synthetic"
        root.mkdir()
        (root / "status.json").write_text('{"core_fixture":"PASS","reference_integrations":"PASS"}')
        for folder in ["01_preprocessing", "02_alignment", "03_phenotype", "05_stitching"]:
            path = root / folder
            path.mkdir()
            for filename in ["slides.html", "diagnostics.json", "stages.json"]:
                (path / filename).write_text("{}")
    if name == "stress_examples":
        path = out / "stress_examples"
        path.mkdir()
        (path / "index.html").write_text("Synthetic only")
        (path / "manifest.json").write_text('{"cases":[{"case":"fixture"}]}')
    if name == "historical_ic":
        (out / "historical_ic_fixture_checks.json").write_text(json.dumps({
            "supplied_patch_arithmetic": "PASS", "patches_checked": 5,
            "physical_calibration_validated": False, "empirical_ic_adopted": False}))
    if name == "production_stress":
        path = out / "production_stress"
        path.mkdir()
        cases = []
        for index in range(9):
            relative = f"case_{index}/observations.json"
            target = path / relative
            target.parent.mkdir()
            target.write_text('{"production_detector_result":"COMPUTED"}')
            cases.append({"observations": relative})
        (path / "status.json").write_text(json.dumps({"cases_executed": 9,
            "unexpected_software_errors": 0, "execution_complete": True, "cases": cases}))
    if name == "pending_export":
        path = out / "pending_export_check"
        path.mkdir()
        (path / "review_verdicts.json").write_text('{"accepted_ids":[]}')
    return expected_exit


class PortableRunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.parent = Path(self.tmp.name)
        self.root = self.parent / "handoff with spaces"
        self.root.mkdir()
        fixture(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_verify_only_needs_neither_git_nor_microscopy_dependencies(self):
        (self.parent / ".git").mkdir()
        with patch.object(runner.subprocess, "run", side_effect=AssertionError("No subprocess needed")):
            self.assertEqual(runner.verify(self.root, self.parent / "hash_check", verify_only=True), 0)
        state = json.loads((self.parent / "hash_check/status.json").read_text())
        self.assertEqual(state["status"], "hashes_verified_only")
        self.assertFalse(state["tests_executed"])
        snapshot = json.loads((self.parent / "hash_check/source_snapshot.json").read_text())
        self.assertFalse(snapshot["git_required"])

    def test_unchanged_package_can_move_without_invalidating_hashes(self):
        destination = self.parent / "moved"
        shutil.copytree(self.root, destination)
        self.assertEqual(runner.verify_manifest(self.root)["manifest_sha256"],
                         runner.verify_manifest(destination)["manifest_sha256"])

    def test_changed_listed_file_fails_before_any_tests(self):
        (self.root / "source/pyproject.toml").write_text("changed")
        with patch.object(runner, "run_stage", side_effect=AssertionError("Must not execute")):
            self.assertEqual(runner.verify(self.root, self.parent / "failed"), 1)
        state = json.loads((self.parent / "failed/status.json").read_text())
        self.assertEqual(state["status"], "failed")
        self.assertIn("Checksum mismatch", state["error"])

    def test_added_active_code_is_rejected_but_generated_metadata_is_recorded(self):
        cache = self.root / "source/src/project.egg-info/PKG-INFO"
        cache.parent.mkdir(parents=True)
        cache.write_text("generated install metadata")
        result = runner.verify_manifest(self.root)
        self.assertIn("source/src/project.egg-info/PKG-INFO", result["ignored_generated_files"])
        (self.root / "source/scripts/unlisted.py").write_text("print('changed')")
        with self.assertRaisesRegex(ValueError, "Unmanifested"):
            runner.verify_manifest(self.root)

    def test_duplicate_unsafe_paths_and_symbolic_inputs_are_rejected(self):
        text = (self.root / "SHA256SUMS").read_text()
        (self.root / "SHA256SUMS").write_text(text + text.splitlines()[0] + "\n")
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            runner.verify_manifest(self.root)
        (self.root / "SHA256SUMS").write_text("0" * 64 + "  ../outside\n")
        with self.assertRaisesRegex(ValueError, "Unsafe"):
            runner.verify_manifest(self.root)
        (self.root / "SHA256SUMS").write_text(text)
        target = self.root / "source/configs/tmem_review_v6.json"
        target.unlink()
        outside = self.parent / "outside.json"
        outside.write_text("{}\n")
        target.symlink_to(outside)
        with self.assertRaisesRegex(ValueError, "nonlocal"):
            runner.verify_manifest(self.root)

    def test_new_outputs_must_be_outside_package_and_never_overwrite(self):
        with self.assertRaisesRegex(ValueError, "outside"):
            runner.reserve_output(self.root, self.root / "new_results")
        existing = self.parent / "existing"
        existing.mkdir()
        with self.assertRaises(FileExistsError):
            runner.reserve_output(self.root, existing)

    def test_aliased_roots_cannot_allow_outputs_inside_immutable_package(self):
        alias = self.parent / "handoff alias with spaces"
        alias.symlink_to(self.root.resolve(), target_is_directory=True)
        physical = self.root.resolve()
        for root, out in [
            (alias, physical / "results"),
            (physical, alias / "results"),
            (alias, alias / "results"),
            (self.root, physical / "results"),
            (alias, physical),
        ]:
            with self.subTest(root=str(root), out=str(out)):
                with self.assertRaisesRegex(ValueError, "outside"):
                    runner.reserve_output(root, out)
        self.assertFalse((physical / "results").exists())
        external = self.parent / "legitimate external output"
        created = runner.reserve_output(alias, external)
        self.assertTrue(created.samefile(external))
        with self.assertRaises(FileExistsError):
            runner.reserve_output(alias, external)

    def test_full_workflow_runs_all_current_tests_and_expected_pending_rejection(self):
        out = self.parent / "full"
        with patch.object(runner, "environment_record", return_value=True), \
             patch.object(runner, "run_stage", side_effect=fake_stage) as mocked, \
             patch.dict(os.environ, {"PYTHONPATH": "/unrelated/old/repository"}):
            self.assertEqual(runner.verify(self.root, out, execution_role="pre_handoff_verification"), 0)
        self.assertEqual([call.args[0] for call in mocked.call_args_list],
                         ["all_tests", "synthetic", "stress_examples", "production_stress", "historical_ic", "pending_export"])
        pytest_command = mocked.call_args_list[0].args[1]
        self.assertEqual(pytest_command[1:5], ["-m", "pytest", "tests", "-p"])
        for call in mocked.call_args_list:
            self.assertNotIn("/unrelated/old/repository", call.args[4]["PYTHONPATH"])
            self.assertEqual(call.args[4]["PYTHONDONTWRITEBYTECODE"], "1")
        state = json.loads((out / "status.json").read_text())
        self.assertEqual(state["status"], "passed")
        self.assertFalse(state["full_pipeline_complete"])
        self.assertFalse(state["claire_independent_stress_complete"])
        self.assertFalse((out / "pending_export_check/accepted_neuron_metrics.csv").exists())
        with (out / "stress_execution.csv").open(newline="") as handle:
            rows = {r["case"]: r for r in csv.DictReader(handle)}
        self.assertEqual(rows["automatic"]["execution_status"], "automated_checks_passed")
        self.assertEqual(rows["human"]["execution_status"], "manual_pending")
        self.assertEqual(rows["original_stitch"]["execution_status"], "blocked_missing_real_input")
        self.assertTrue(all(r["reviewer"] == "" for r in rows.values()))

    def test_test_failure_stops_downstream_and_preserves_failed_status(self):
        def fail(name, command, source, out, env, stages, expected_exit=0):
            stages.append({"stage": name, "passed": False, "returncode": 1})
            return 1
        with patch.object(runner, "environment_record", return_value=True), \
             patch.object(runner, "run_stage", side_effect=fail) as mocked:
            self.assertEqual(runner.verify(self.root, self.parent / "failure"), 1)
        self.assertEqual(mocked.call_count, 1)
        self.assertEqual(json.loads((self.parent / "failure/status.json").read_text())["status"], "failed")

    def test_pending_wrong_exit_or_accidental_csv_never_claims_success(self):
        for scenario in ["wrong_exit", "csv"]:
            def wrong(name, command, source, out, env, stages, expected_exit=0):
                result = fake_stage(name, command, source, out, env, stages, expected_exit)
                if name == "pending_export":
                    if scenario == "wrong_exit":
                        return 1
                    (out / "pending_export_check/accepted_neuron_metrics.csv").write_text("unexpected")
                return result
            with patch.object(runner, "environment_record", return_value=True), \
                 patch.object(runner, "run_stage", side_effect=wrong):
                out = self.parent / scenario
                self.assertEqual(runner.verify(self.root, out), 1)
                self.assertEqual(json.loads((out / "status.json").read_text())["status"], "failed")

    def test_green_process_without_numeric_artifacts_is_not_success(self):
        def missing(name, command, source, out, env, stages, expected_exit=0):
            result = fake_stage(name, command, source, out, env, stages, expected_exit)
            if name == "synthetic":
                (out / "synthetic/01_preprocessing/slides.html").unlink()
            return result
        with patch.object(runner, "environment_record", return_value=True), \
             patch.object(runner, "run_stage", side_effect=missing):
            self.assertEqual(runner.verify(self.root, self.parent / "missing_artifact"), 1)

    def test_junit_subtests_are_not_reported_as_extra_ordinary_tests(self):
        log = self.parent / "tests.log"
        xml = self.parent / "tests.xml"
        log.write_text("270 passed, 30 subtests passed in 16.38s\n")
        xml.write_text('<testsuite tests="300" failures="0" errors="0" skipped="0"/>')
        summary = runner.test_summary(xml, log)
        self.assertEqual(summary["ordinary_tests_passed"], 270)
        self.assertEqual(summary["subtests_passed"], 30)
        self.assertEqual(summary["junit_counts_including_subtests"]["tests"], 300)

    def test_per_case_pass_requires_the_actual_mapped_junit_assertion(self):
        xml = self.parent / "cases.xml"
        xml.write_text('<testsuite><testcase classname="tests.test_fake.Checks" name="test_other"/></testsuite>')
        with self.assertRaisesRegex(ValueError, "not executed"):
            runner.mapped_case_results(self.root, xml)
        xml.write_text('<testsuite><testcase classname="tests.test_fake.Checks" name="test_pass"><skipped/></testcase></testsuite>')
        with self.assertRaisesRegex(ValueError, "did not pass"):
            runner.mapped_case_results(self.root, xml)
        xml.write_text('<testsuite><testcase classname="tests.test_fake.Checks" name="test_pass[param]"/></testsuite>')
        result = runner.mapped_case_results(self.root, xml)
        self.assertEqual(result[0]["case"], "automatic")
        self.assertTrue(result[0]["mapped_assertions_passed"])

    def test_changed_or_removed_stress_recipe_cannot_inherit_a_green_suite(self):
        xml = self.parent / "cases.xml"
        xml.write_text('<testsuite><testcase classname="tests.test_fake.Checks" name="test_pass"/></testsuite>')
        with (self.root / "stress_results.csv").open(newline="") as handle:
            rows = list(csv.DictReader(handle))
        with (self.root / "stress_results.csv").open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows[:1])
        with self.assertRaisesRegex(ValueError, "recipes differ"):
            runner.mapped_case_results(self.root, xml)

    def test_only_exact_optional_node_check_may_be_skipped_when_node_is_absent(self):
        xml = self.parent / "optional.xml"
        xml.write_text('<testsuite><testcase classname="tests.audit_v1.test_review_workspace.WorkspaceTests" '
            'name="test_offline_controls_save_resume_and_stale_rejection"><skipped '
            'message="Node is optional for the offline UI workflow check"/></testcase></testsuite>')
        with patch.object(runner.shutil, "which", return_value=None):
            policy = runner.skip_policy(xml)
        self.assertEqual(len(policy["allowed_optional_browser_skips"]), 1)
        self.assertFalse(policy["unexpected_skips"])
        with patch.object(runner.shutil, "which", return_value="/usr/bin/node"):
            self.assertEqual(len(runner.skip_policy(xml)["unexpected_skips"]), 1)
        xml.write_text('<testsuite><testcase classname="test_reference.AlignmentIntegration" '
            'name="test_translation_sign_and_channel_separation"><skipped message="missing dependency"/>'
            '</testcase></testsuite>')
        with patch.object(runner.shutil, "which", return_value=None):
            self.assertEqual(len(runner.skip_policy(xml)["unexpected_skips"]), 1)

    def test_every_declared_case_node_names_an_existing_assertion(self):
        with (SOURCE / "docs/audit_v1/claire_stress_cases.csv").open(newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 23)
        for row in rows:
            node = row["test_node"]
            if not node:
                self.assertTrue(row["mode"] == "manual" or row["availability_status"] == "blocked_missing_real_input")
                continue
            parts = node.split("::")
            file = SOURCE / parts[0]
            self.assertTrue(file.is_file(), node)
            scope = ast.parse(file.read_text()).body
            for name in parts[1:]:
                matched = [entry for entry in scope if isinstance(entry, (ast.ClassDef, ast.FunctionDef)) and entry.name == name]
                self.assertEqual(len(matched), 1, node)
                scope = matched[0].body
            self.assertTrue(parts[-1].startswith("test_"), node)


if __name__ == "__main__":
    unittest.main()
