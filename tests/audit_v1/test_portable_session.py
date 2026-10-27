"""Session packaging and deadline controls, using no microscopy or network."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("portable_session", ROOT / "scripts/finish_portable_session.py")
driver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(driver)


class PortableSessionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.addCleanup(lambda: (self.root.parent / (self.root.name + "_TRANSFER.zip")).unlink(missing_ok=True))
        self.addCleanup(lambda: (self.root.parent / (self.root.name + "_TRANSFER.zip.sha256")).unlink(missing_ok=True))

    def test_package_hash_binding_and_required_files(self):
        hashes = {}
        for name in ["payload.json", "publish_remote.py", "prepare_portable_dataset.py"]:
            data = (name + " CONTROL ONLY").encode()
            (self.root / name).write_bytes(data)
            hashes[name] = hashlib.sha256(data).hexdigest()
        (self.root / "PACKAGE_SHA256.json").write_text(json.dumps(hashes))
        driver.verify_package(self.root)
        (self.root / "payload.json").write_text("changed")
        with self.assertRaisesRegex(ValueError, "changed"):
            driver.verify_package(self.root)

    def test_unsafe_package_path_rejected(self):
        (self.root / "PACKAGE_SHA256.json").write_text(json.dumps({"../escape": "a" * 64}))
        with self.assertRaisesRegex(ValueError, "Unsafe"):
            driver.verify_package(self.root)

    def test_push_receipt_requires_real_commit_shape(self):
        good = dict(status="pushed_verified", commit="a" * 40)
        self.assertEqual(driver.json_receipt("login banner\n" + json.dumps(good)), good)
        with self.assertRaises(ValueError):
            driver.json_receipt(json.dumps(dict(status="pushed_verified", commit="not_a_sha")))
        with self.assertRaises(RuntimeError):
            driver.json_receipt('{"status":"failed"}')

    def test_archive_excludes_environment_git_private_and_links(self):
        session = self.root / "session"
        session.mkdir()
        (session / "note.md").write_text("preserved")
        for directory in ["private", ".git", ".venv", "__pycache__"]:
            (session / directory).mkdir()
            (session / directory / "secret").write_text("must not travel")
        (session / "link").symlink_to(session / "note.md")
        archive, checksum = driver.make_archive(session)
        self.assertEqual(checksum, driver.digest(archive))
        with zipfile.ZipFile(archive) as z:
            self.assertEqual(set(z.namelist()), {"session/note.md", "session/TRANSFER_SHA256.json"})
            inventory = json.loads(z.read("session/TRANSFER_SHA256.json"))
            self.assertEqual(inventory["note.md"], hashlib.sha256(b"preserved").hexdigest())

    def test_session_deadline_does_not_start_more_commands(self):
        session = driver.Session(self.root, 1)
        session.deadline = 0
        with patch.object(driver.subprocess, "run") as run:
            with self.assertRaises(TimeoutError):
                session.command("never", ["must_not_execute"])
            run.assert_not_called()

    def test_command_timeout_is_recorded_without_waiting_for_job(self):
        session = driver.Session(self.root, 1)
        with self.assertRaises(driver.subprocess.TimeoutExpired):
            session.command("timeout", [sys.executable, "-c", "import time;time.sleep(30)"], timeout=0.05)
        state = json.loads(session.state_path.read_text())
        self.assertEqual(state["steps"]["timeout"]["status"], "failed")

    def test_ssh_socket_uses_a_short_private_temporary_directory(self):
        session = driver.Session(self.root, 1)
        with patch.object(driver.tempfile, "mkdtemp", return_value=str(self.root / "socket")) as make:
            options = session.ssh()
        make.assert_called_once_with(prefix="tmemssh_", dir="/tmp")
        self.assertIn("ControlPath=" + str(self.root / "socket/s-%C"), options)

    def test_command_failure_is_preserved_and_raised(self):
        session = driver.Session(self.root, 1)
        with self.assertRaisesRegex(RuntimeError, "returned 3"):
            session.command("fails", [sys.executable, "-c", "raise SystemExit(3)"])
        state = json.loads(session.state_path.read_text())
        self.assertEqual(state["steps"]["fails"]["returncode"], 3)
        self.assertEqual(state["steps"]["fails"]["status"], "failed")

    def test_capture_command_retains_stdout_and_stderr(self):
        session = driver.Session(self.root, 1)
        stdout = session.command("capture", [sys.executable, "-c", "import sys;print('result');print('detail',file=sys.stderr)"], capture=True)
        self.assertEqual(stdout, "result\n")
        self.assertIn("detail", (self.root / "logs/capture.log").read_text())

    def test_session_identity_is_validated(self):
        (self.root / "SESSION_STATE.json").write_text(json.dumps({"session_id": "../../escape"}))
        with self.assertRaisesRegex(ValueError, "identity"):
            driver.Session(self.root, 1)

    def test_offline_session_never_uses_network_and_preserves_partial(self):
        (self.root / "repo").mkdir()
        invoked = []
        def blocked_command(session, name, args, **kwargs):
            invoked.append(args)
            self.assertNotIn(args[0], ["ssh", "scp"])
            raise RuntimeError("CONTROL: no environment installed")
        with patch.object(driver.Session, "command", blocked_command), patch.object(driver.sys, "platform", "linux"):
            result = driver.main(["--offline", "--session", str(self.root), "--minutes", "1"])
        self.assertEqual(result, 1)
        self.assertTrue(invoked)
        self.assertTrue((self.root / "SESSION_RESULTS.md").is_file())
        state = json.loads((self.root / "SESSION_STATE.json").read_text())
        self.assertEqual(state["dataset_status"], "not_transferred")
        self.assertFalse(state["scientific_inference_ready"])

    def test_transferred_bundle_restores_git_without_overwriting_local_edits(self):
        branch = "continuation/portable-20261027_a1b2c3d4"
        fixture = self.root / "fixture"
        fixture.mkdir()
        def git(*args):
            return driver.subprocess.run(["git", "-C", str(fixture), *args], check=True,
                text=True, stdout=driver.subprocess.PIPE, stderr=driver.subprocess.PIPE).stdout.strip()
        git("init")
        git("config", "user.name", "Local control fixture")
        git("config", "user.email", "control@example.invalid")
        (fixture / "note.txt").write_text("committed fixture")
        git("add", "note.txt")
        git("commit", "-m", "Control fixture; no scientific data")
        git("branch", "-M", branch)
        commit = git("rev-parse", "HEAD")
        git("bundle", "create", str(self.root / "code.bundle"), "refs/heads/" + branch)
        repo = self.root / "repo"
        repo.mkdir()
        (repo / "note.txt").write_text("local edit must survive")
        driver.write_json(self.root / "SESSION_STATE.json", dict(session_id="a1b2c3d4", steps={},
            push_receipt=dict(status="pushed_verified", commit=commit, branch=branch),
            real_accepted_ids=[], scientific_inference_ready=False))
        original = driver.Session.command
        def commands(session, name, args, **kwargs):
            self.assertNotIn(args[0], ["ssh", "scp"])
            if name.startswith("restore_git_"):
                return original(session, name, args, **kwargs)
            raise RuntimeError("CONTROL: stop after Git restore")
        with patch.object(driver.Session, "command", commands), patch.object(driver.sys, "platform", "linux"):
            driver.main(["--offline", "--session", str(self.root), "--minutes", "1"])
        self.assertTrue((repo / ".git").is_dir())
        self.assertEqual((repo / "note.txt").read_text(), "local edit must survive")
        actual = driver.subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
            check=True, text=True, stdout=driver.subprocess.PIPE).stdout.strip()
        self.assertEqual(actual, commit)


if __name__ == "__main__":
    unittest.main()
