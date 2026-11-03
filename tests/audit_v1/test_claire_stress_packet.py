"""Compact packet integrity controls; these do not execute microscopy."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("claire_packet", ROOT / "scripts/package_claire_stress_tests.py")
packet = importlib.util.module_from_spec(spec)
spec.loader.exec_module(packet)


class ClaireStressPacketTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_packet_is_compact_checksummed_and_not_sent_or_executed(self):
        result = packet.package(self.root / "packet.zip")
        self.assertEqual(result["status"], "prepared_not_sent")
        self.assertEqual(result["synthetic_cases"], 9)
        self.assertLess(result["bytes"], 250000)
        with zipfile.ZipFile(result["path"]) as z:
            for name, expected in json.loads(z.read("MANIFEST.json")).items():
                self.assertEqual(hashlib.sha256(z.read(name)).hexdigest(), expected)
            self.assertFalse(any(n.lower().endswith((".nd2", ".tif", ".tiff", ".npy", ".npz")) for n in z.namelist()))
            provenance = json.loads(z.read("PROVENANCE.json"))
            self.assertFalse(provenance["packet_creation_runs_microscopy"])
            self.assertEqual(provenance["recipient_identity"], "unresolved")
            self.assertEqual(provenance["provided_verification"], "none_not_run")
            self.assertEqual(json.loads(z.read("RESULTS.template.json"))["status"], "not_run")

    def test_actual_source_files_and_configuration_are_bound(self):
        result = packet.package(self.root / "packet.zip")
        with zipfile.ZipFile(result["path"]) as z:
            provenance = json.loads(z.read("PROVENANCE.json"))
            for name, expected in provenance["source_sha256"].items():
                self.assertEqual(expected, packet.sha((ROOT / name).read_bytes()))
            declared = json.loads(z.read("DECLARED_PARAMETERS.json"))
            self.assertEqual(declared["configuration"], json.loads((ROOT / "configs/tmem_stage_diagnostics.json").read_text()))

    def test_run_order_and_real_source_limit_are_explicit(self):
        result = packet.package(self.root / "packet.zip")
        with zipfile.ZipFile(result["path"]) as z:
            script = z.read("RUN_STRESS.sh").decode()
            self.assertLess(script.index("scripts/verify_stage_pipeline.py --out"), script.index("scripts/exercise_stress_pipeline.py --out"))
            plan = json.loads(z.read("STRESS_CASE_PLAN.json"))
            real = [case for case in plan if case["original_nd2"]]
            self.assertEqual(len(real), 3)
            self.assertTrue(all(case["status"] == "blocked_pending_original_source_run" for case in real))

    def test_git_identity_is_not_invented_for_a_source_snapshot(self):
        context = packet.git_context(self.root)
        self.assertFalse(context["git_identity_available"])
        self.assertIsNone(context["commit"])

    def test_stress_launcher_rejects_wrong_checkout_before_running_tests(self):
        result = packet.package(self.root / "packet.zip")
        extracted = self.root / "packet"
        with zipfile.ZipFile(result["path"]) as z:
            z.extractall(extracted)
        checkout = self.root / "checkout"
        (checkout/"scripts").mkdir(parents=True)
        for name in ["verify_stage_pipeline.py", "exercise_stress_pipeline.py"]:
            (checkout/"scripts"/name).write_text("raise AssertionError('must not execute')")
        import os,sys
        run = subprocess.run(["bash", str(extracted/"RUN_STRESS.sh")],
            env=dict(os.environ,TMEM_REPO=str(checkout),TMEM_PYTHON=sys.executable),
            text=True,capture_output=True)
        self.assertNotEqual(run.returncode,0)
        self.assertIn("STOP: missing stress source:",run.stderr)
        self.assertNotIn("must not execute",run.stderr)

    def test_existing_packet_is_preserved(self):
        out = self.root / "packet.zip"
        out.write_bytes(b"existing")
        with self.assertRaises(FileExistsError):
            packet.package(out)
        self.assertEqual(out.read_bytes(), b"existing")

    def test_unsafe_or_linked_source_paths_are_blocked(self):
        for name in ["../escape.py", "/absolute.py", "scripts/../README.md"]:
            with self.assertRaises(ValueError):
                packet.source_path(ROOT, name)
        (self.root / "target.py").write_text("control")
        (self.root / "linked.py").symlink_to(self.root / "target.py")
        with self.assertRaisesRegex(ValueError, "Linked"):
            packet.source_path(self.root, "linked.py")

    def test_failed_empty_skipped_or_source_mismatched_verification_is_rejected(self):
        path = self.root / "verification_status.json"
        value = dict(status="passed", unit_tests_passed=True, integration_tests_passed=True,
            tests=2, failures=0, errors=0, skipped=0,
            phases={name:dict(tests=1, failures=0, errors=0, skipped=0, returncode=0) for name in ["unit", "integration"]},
            source_file_sha256={"source.py": packet.sha(b"source")})
        (self.root / "source.py").write_bytes(b"source")
        path.write_text(json.dumps(value))
        summary = packet.verified_run_summary(path, self.root)
        self.assertEqual(summary["source_bindings_verified"], 1)
        for updates in [{"tests": 0}, {"skipped": 1}, {"status": "failed"}, {"phases": {}}]:
            path.write_text(json.dumps({**value, **updates}))
            with self.assertRaises(ValueError):
                packet.verified_run_summary(path, self.root)
        path.write_text(json.dumps(value))
        (self.root / "source.py").write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "no longer matches"):
            packet.verified_run_summary(path, self.root)


if __name__ == "__main__":
    unittest.main()
