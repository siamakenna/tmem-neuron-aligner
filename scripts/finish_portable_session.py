#!/usr/bin/env python3
"""Checkpoint code, copy six wells, run bounded local work, and package a session.

Normal mode makes a final NIH transfer; --offline never contacts NIH. Scientific
calculations run only through the existing verified processing commands. The
one-hour workflow preserves partial results rather than granting approvals.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile
import time
import uuid
import zipfile

BASE = "a978ac54c943d5e28a01a4d92fa989b6e4760684"
REPO_URL = "https://github.com/siamakenna/tmem-neuron-aligner.git"
REMOTE_PYTHON = "/data/rodriguezmak/tmem106b/envs/tmem-audit-v1_0TX0IAS4/bin/python"
PRIOR_RUN = "/data/rodriguezmak/tmem106b/processed/18_tmem_stage_implementation_20261027_n9oz6u94"
PRIOR_ZIP = "TMEM106B_stage_implementation_results_20261027.zip"
PRIOR_SHA = "297e049cb7db0e6d93446a86dc7cdb9a83f53b910233ebc11e8f9c99ba0819bd"
CONTROL_TESTS = ["test_portable_dataset.py", "test_portable_benchmark.py",
                 "test_stage_evidence.py", "test_portable_session.py"]


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    temporary.replace(path)


def record(content):
    return dict(content_b64=base64.b64encode(content).decode(),
                sha256=hashlib.sha256(content).hexdigest(), mode=0o644)


def json_receipt(output):
    # Login banners may precede the publisher's one-line JSON receipt.
    for line in reversed(output.splitlines()):
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict) and value.get("status") == "pushed_verified":
            if not re.fullmatch(r"[0-9a-f]{40}", value.get("commit", "")):
                raise ValueError("Malformed pushed commit receipt")
            return value
    raise RuntimeError("No verified Git push receipt; inspect the saved log")


def verify_package(package):
    manifest = json.loads((package / "PACKAGE_SHA256.json").read_text())
    for relative, expected in manifest.items():
        path = Path(relative)
        if path.is_absolute() or ".." in path.parts or not path.parts:
            raise ValueError("Unsafe package path")
        target = package / path
        if target.is_symlink() or not target.is_file() or digest(target) != expected:
            raise ValueError("Package file changed: " + relative)
    for name in ["payload.json", "publish_remote.py", "prepare_portable_dataset.py"]:
        if name not in manifest:
            raise ValueError("Missing required package binding: " + name)


def make_archive(session):
    """No environments, SSH sockets, credentials, or arbitrary symlinks travel."""
    destination = session.parent / (session.name + "_TRANSFER.zip")
    temporary = destination.with_suffix(".zip.part")
    inventory = {}
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_STORED,
                         allowZip64=True) as archive:
        for path in sorted(session.rglob("*")):
            rel = path.relative_to(session)
            if any(part in {".git", ".venv", "private", "__pycache__", ".pytest_cache"}
                   for part in rel.parts):
                continue
            if path.is_symlink():
                continue
            if path.is_file():
                key = rel.as_posix()
                inventory[key] = digest(path)
                archive.write(path, session.name + "/" + key)
        archive.writestr(session.name + "/TRANSFER_SHA256.json",
                         json.dumps(inventory, indent=2) + "\n")
    temporary.replace(destination)
    checksum = digest(destination)
    destination.with_suffix(".zip.sha256").write_text(checksum + "  " + destination.name + "\n")
    return destination, checksum


class Session:
    def __init__(self, root, minutes):
        self.root = root.resolve()
        self.deadline = time.monotonic() + minutes * 60
        self.logs = self.root / "logs"
        self.logs.mkdir(parents=True, exist_ok=True)
        self.state_path = self.root / "SESSION_STATE.json"
        self.socket_directory = None
        self.state = json.loads(self.state_path.read_text()) if self.state_path.exists() else {
            "schema_version": 1, "session_id": uuid.uuid4().hex[:8],
            "steps": {}, "real_accepted_ids": [], "scientific_inference_ready": False}
        if not re.fullmatch(r"[0-9a-f]{8}", self.state.get("session_id", "")):
            raise ValueError("Invalid portable session identity")
        self.save()

    def save(self):
        write_json(self.state_path, self.state)

    def remaining(self, reserve=0):
        return max(0, self.deadline - time.monotonic() - reserve)

    def command(self, name, args, timeout=300, capture=False, cwd=None):
        limit = min(timeout, self.remaining())
        if self.remaining() < 2 or limit <= 0:
            raise TimeoutError("Session time budget exhausted before " + name)
        log = self.logs / (name + ".log")
        started = time.monotonic()
        self.state["steps"][name] = {"status": "running"}
        self.save()
        try:
            group = os.name == "posix" and Path(args[0]).name not in {"ssh", "scp"}
            env = dict(os.environ, OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1",
                       MKL_NUM_THREADS="1", NUMEXPR_NUM_THREADS="1", PYTHONDONTWRITEBYTECODE="1")
            with log.open("w") as stream:
                process = subprocess.Popen(args, cwd=cwd, text=True,
                    stdout=subprocess.PIPE if capture else stream,
                    stderr=stream if capture else subprocess.STDOUT,
                    start_new_session=group, env=env)
                try:
                    output, _ = process.communicate(timeout=limit)
                except BaseException:
                    try:
                        if group:
                            os.killpg(process.pid, signal.SIGKILL)
                        else:
                            process.kill()
                    except ProcessLookupError:
                        pass
                    process.communicate()
                    raise
            result = subprocess.CompletedProcess(args, process.returncode, output)
            if capture:
                (self.logs / (name + ".stdout")).write_text(result.stdout)
            self.state["steps"][name] = {"status": "passed" if result.returncode == 0 else "failed",
                "returncode": result.returncode, "seconds": round(time.monotonic() - started, 2),
                "log": str(log.relative_to(self.root))}
            self.save()
            if result.returncode:
                raise RuntimeError(f"{name} returned {result.returncode}; see {log}")
            return result.stdout if capture else ""
        except Exception as error:
            self.state["steps"][name].update(status="failed", error=str(error))
            self.save()
            raise

    def ssh(self, host="biowulf.nih.gov"):
        # macOS Unix socket paths are short; Downloads/session paths exceed the
        # platform limit once %C expands. Keep this temporary socket outside ZIPs.
        if self.socket_directory is None:
            self.socket_directory = Path(tempfile.mkdtemp(prefix="tmemssh_", dir="/tmp"))
        socket = self.socket_directory / "s-%C"
        return ["-o", "ConnectTimeout=20", "-o", "ServerAliveInterval=15",
                "-o", "ServerAliveCountMax=2", "-o", "ControlMaster=auto",
                "-o", "ControlPersist=300", "-o", "ControlPath=" + str(socket)]

    def remote(self, name, command, **kwargs):
        return self.command(name, ["ssh", *self.ssh(), "rodriguezmak@biowulf.nih.gov",
                                   command], **kwargs)

    def copy(self, name, remote_path, local_path, **kwargs):
        Path(local_path).parent.mkdir(parents=True, exist_ok=True)
        last_error = None
        for attempt, host in enumerate(["helix.nih.gov", "helix.nih.gov", "biowulf.nih.gov"], 1):
            try:
                return self.command(name + f"_attempt{attempt}", ["scp", *self.ssh(),
                    "rodriguezmak@" + host + ":" + remote_path, str(local_path)], **kwargs)
            except Exception as error:
                last_error = error
                if self.remaining() < 10:
                    break
        raise last_error


def summary_markdown(state, dataset, benchmark):
    pushed = state.get("push_receipt", {})
    return ("# Portable TMEM106B session\n\n"
        f"- Code push: {pushed.get('status', 'not_verified')}\n"
        f"- Branch: `{pushed.get('branch', 'unknown')}`\n"
        f"- Commit before this results checkpoint: `{pushed.get('commit', 'unknown')}`\n"
        f"- Dataset: {dataset}\n"
        f"- Local verification: {state.get('steps', {}).get('local_verification', {}).get('status', 'not_run')}\n"
        f"- Benchmark: {benchmark}\n"
        "- Raw IC/registration experimental validation: blocked; matching raw inputs and detector-coordinate fields were not exported.\n"
        "- Newly accepted biological tracks: 0.\n\n"
        "Read `docs/continuation_20261027/CODEX_NEXT.md` in the repository. "
        "Partial/deferred runs remain incomplete; the recorded code checkpoint is usable independently.\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-dir", type=Path)
    parser.add_argument("--session", type=Path)
    parser.add_argument("--minutes", type=float, default=40)
    parser.add_argument("--offline", action="store_true", help="No NIH connections; use the transferred repository and data")
    parser.add_argument("--no-data", action="store_true", help="Publish/package code and notes; omit the six image stacks")
    args = parser.parse_args(argv)
    if not 1 <= args.minutes <= 60:
        parser.error("--minutes must be between 1 and 60")
    if sys.version_info < (3, 9):
        parser.error("Python 3.9+ is required for transfer; Python 3.11+ runs the microscopy environment")
    if args.offline and args.session is None:
        parser.error("--offline requires --session PATH from the transferred folder")
    (Path.home() / "Downloads").mkdir(exist_ok=True)
    root = (args.session or Path(tempfile.mkdtemp(prefix="TMEM106B_portable_20261027_",
                                                  dir=Path.home() / "Downloads"))).resolve()
    root.mkdir(parents=True, exist_ok=True)
    session = Session(root, args.minutes)
    repo = root / "repo"
    dataset = root / "dataset"
    package = args.package_dir.resolve() if args.package_dir else root / "private" / "package"
    dataset_status, benchmark_status = "not_transferred", "not_run"
    transfer = None
    errors = []
    try:
        if not args.offline:
            verify_package(package)
            if package != root / "private" / "package":
                shutil.copytree(package, root / "private" / "package", dirs_exist_ok=True)
                package = root / "private" / "package"
            sid = session.state["session_id"]
            remote_dir = "/data/rodriguezmak/tmem106b/portable_20261027_" + sid
            session.state["remote_directory"] = remote_dir
            session.save()
            print("Publishing the portable code/notes checkpoint first. NIH password prompts may appear.", flush=True)
            session.remote("remote_directory", "mkdir -p " + shlex.quote(remote_dir))
            session.command("upload_helpers", ["scp", *session.ssh(),
                str(package / "publish_remote.py"), str(package / "payload.json"),
                str(package / "prepare_portable_dataset.py"),
                "rodriguezmak@biowulf.nih.gov:" + remote_dir + "/"])
            publish = " ".join(map(shlex.quote, [REMOTE_PYTHON, remote_dir + "/publish_remote.py",
                "--session", remote_dir, "--payload", remote_dir + "/payload.json"]))
            receipt = json_receipt(session.remote("publish_code", publish, capture=True))
            session.state["push_receipt"] = receipt
            session.save()
            write_json(root / "PUSH_RECEIPT.json", receipt)
            print("GITHUB PUSH VERIFIED: " + receipt["commit"] + "\n" + receipt.get("url", receipt.get("remote_url", "")), flush=True)
            if not repo.exists():
                # A Git bundle preserves actual history and avoids requiring Mac GitHub authentication.
                bundle = remote_dir + "/code.bundle"
                command = " ".join(map(shlex.quote, ["git", "-C", receipt["worktree"], "bundle", "create", bundle,
                    "refs/heads/" + receipt["branch"]]))
                session.remote("make_code_bundle", command)
                session.copy("download_code_bundle", bundle, root / "code.bundle")
                session.command("clone_local_code", ["git", "clone", "--branch", receipt["branch"],
                    str(root / "code.bundle"), str(repo)])
                session.command("set_github_origin", ["git", "-C", str(repo), "remote", "set-url", "origin", REPO_URL])
            if not args.no_data:
                if shutil.disk_usage(root).free < 8 * 1024**3:
                    raise OSError("Code is pushed; six-well transfer deferred because less than 8 GiB is free")
                print("Copying registered stacks from all six wells; no new cluster jobs will run.", flush=True)
                remote_manifest = remote_dir + "/dataset_manifest.json"
                command = " ".join(map(shlex.quote, [REMOTE_PYTHON, remote_dir + "/prepare_portable_dataset.py",
                    "--remote-manifest", "--out", remote_manifest]))
                command = "if [ ! -f " + shlex.quote(remote_manifest) + " ]; then " + command + "; fi"
                session.remote("describe_six_well_dataset", command, timeout=300)
                session.copy("download_dataset_manifest", remote_manifest, dataset / "dataset_manifest.json")
                manifest = json.loads((dataset / "dataset_manifest.json").read_text())
                entries = [("master", manifest["master"]), *sorted(manifest["stacks"].items())]
                for name, entry in entries:
                    if session.remaining(reserve=300) < 15:
                        raise TimeoutError("Transfer stopped at budget; completed files are preserved")
                    relative = Path(entry["path"])
                    source = entry["source_path"]
                    if relative.is_absolute() or ".." in relative.parts or not re.fullmatch(r"/(data/rodriguezmak|vf/users/rodriguezmak)/tmem106b/processed/[A-Za-z0-9_./-]+", source):
                        raise ValueError("Unexpected dataset source or destination path")
                    target = dataset / relative
                    if target.is_file() and digest(target) == entry["sha256"]:
                        continue
                    part = target.with_name(target.name + ".part")
                    session.copy("download_" + name, source, part,
                                 timeout=min(600, session.remaining(reserve=240)))
                    if part.stat().st_size != entry["bytes"] or digest(part) != entry["sha256"]:
                        raise ValueError("Transferred file checksum mismatch: " + name)
                    part.replace(target)
                evidence = root / "evidence" / PRIOR_ZIP
                if not evidence.is_file() or digest(evidence) != PRIOR_SHA:
                    session.copy("download_prior_evidence", PRIOR_RUN + "/" + PRIOR_ZIP,
                                 evidence.with_suffix(".zip.part"), timeout=120)
                    part = evidence.with_suffix(".zip.part")
                    if digest(part) != PRIOR_SHA:
                        raise ValueError("Previous evidence archive checksum mismatch")
                    part.replace(evidence)
        if not repo.is_dir():
            raise FileNotFoundError("No local repository was transferred; inspect publish/transfer logs")
        if args.offline and not (repo / ".git").exists() and (root / "code.bundle").is_file():
            branch = session.state.get("push_receipt", {}).get("branch", "")
            if not re.fullmatch(r"continuation/portable-20261027_[0-9a-f]{8}", branch):
                raise ValueError("Missing safe branch binding for the transferred Git bundle")
            # The archive deliberately excludes .git. Restore only the index and
            # history from its bundle; preserve every working-tree file.
            session.command("restore_git_init", ["git", "init", str(repo)], timeout=30)
            session.command("restore_git_fetch", ["git", "-C", str(repo), "fetch",
                str(root / "code.bundle"), "refs/heads/" + branch], timeout=60)
            session.command("restore_git_index", ["git", "-C", str(repo), "reset", "--mixed", "FETCH_HEAD"], timeout=30)
            session.command("restore_git_branch", ["git", "-C", str(repo), "branch", "-M", branch], timeout=30)
            session.command("restore_git_origin", ["git", "-C", str(repo), "remote", "add", "origin", REPO_URL], timeout=30)
        if not args.no_data and (dataset / "dataset_manifest.json").is_file():
            session.command("verify_local_dataset", [sys.executable, str(repo / "scripts/prepare_portable_dataset.py"),
                                                      "--verify-local", str(dataset)], timeout=180)
            dataset_status = "verified_all_six_wells"
        print("Checking portable transfer/control tests.", flush=True)
        for name in CONTROL_TESTS:
            session.command("control_" + name[:-3], [sys.executable, str(repo / "tests/audit_v1" / name)], timeout=60, cwd=repo)
        if sys.version_info < (3, 11):
            raise RuntimeError("Code/data transfer completed; local microscopy is deferred until Python 3.11+ is available")
        if session.remaining(reserve=180) < 60:
            raise TimeoutError("Local environment/benchmark deferred at time budget")
        venv = root / ".venv"
        python = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        if not python.is_file():
            session.command("create_local_environment", [sys.executable, "-m", "venv", str(venv)], timeout=60)
        session.command("install_local_dependencies", [str(python), "-m", "pip", "install", "--disable-pip-version-check",
            "--only-binary=:all:", "-r", str(repo / "requirements-portable.txt")],
            timeout=min(480, session.remaining(reserve=180)))
        # Verification CLI sets its own import path; no project installation/GUI stack is needed.
        verification = root / "verification" / time.strftime("local_%Y%m%d_%H%M%S")
        session.command("local_verification", [str(python), str(repo / "scripts/verify_stage_pipeline.py"),
            "--out", str(verification)], timeout=min(300, session.remaining(reserve=180)), cwd=repo)
        session.state["local_verification_path"] = str(verification.relative_to(root))
        session.save()
        freeze = session.command("record_environment", [str(python), "-m", "pip", "freeze"], capture=True, timeout=30)
        (root / "LOCAL_REQUIREMENTS_RESOLVED.txt").write_text(freeze)
        if dataset_status == "verified_all_six_wells" and session.remaining(reserve=180) > 60:
            minutes = min(22, session.remaining(reserve=180) / 60)
            output = root / "benchmarks" / time.strftime("six_well_%Y%m%d_%H%M%S")
            print(f"Running two diagnostic candidates per well, two workers, up to {minutes:.1f} minutes.", flush=True)
            try:
                session.command("six_well_benchmark", [str(python), str(repo / "scripts/run_portable_benchmark.py"),
                    "--dataset", str(dataset), "--out", str(output), "--minutes", str(minutes),
                    "--workers", "2", "--tracks-per-well", "2", "--case-timeout-minutes", "10"],
                    timeout=minutes * 60 + 15, cwd=repo)
                benchmark_status = "completed"
            except Exception as error:
                benchmark_status = "partial_or_failed"
                errors.append(str(error))
            session.state["benchmark_path"] = str(output.relative_to(root))
            session.save()
        elif args.no_data:
            benchmark_status = "deferred_no_data_requested"
    except Exception as error:
        errors.append(str(error))
        print("Preserving the completed checkpoint and partial work: " + str(error), flush=True)
    finally:
        session.state.update(dataset_status=dataset_status, benchmark_status=benchmark_status, errors=errors)
        session.save()
        markdown = summary_markdown(session.state, dataset_status, benchmark_status)
        (root / "SESSION_RESULTS.md").write_text(markdown)
        result_files = {
            "docs/continuation_20261027/session/SESSION_RESULTS.json": record(session.state_path.read_bytes()),
            "docs/continuation_20261027/session/SESSION_RESULTS.md": record(markdown.encode()),
        }
        verify_path = session.state.get("local_verification_path")
        if verify_path and (root / verify_path / "verification_status.json").is_file():
            result_files["docs/continuation_20261027/session/LOCAL_VERIFICATION.json"] = record(
                (root / verify_path / "verification_status.json").read_bytes())
        benchmark_path = session.state.get("benchmark_path")
        if benchmark_path and (root / benchmark_path / "benchmark_summary.json").is_file():
            result_files["docs/continuation_20261027/session/BENCHMARK_SUMMARY.json"] = record(
                (root / benchmark_path / "benchmark_summary.json").read_bytes())
        if not args.offline and session.state.get("push_receipt") and session.remaining() > 15:
            try:
                result_payload = root / "private" / "result_payload.json"
                write_json(result_payload, {"files": result_files})
                remote_dir = session.state["remote_directory"]
                session.command("upload_results_checkpoint", ["scp", *session.ssh(), str(result_payload),
                    "rodriguezmak@biowulf.nih.gov:" + remote_dir + "/result_payload.json"], timeout=45)
                command = " ".join(map(shlex.quote, [REMOTE_PYTHON, remote_dir + "/publish_remote.py",
                    "--session", remote_dir, "--append-results", remote_dir + "/result_payload.json"]))
                final = json_receipt(session.remote("publish_results", command, capture=True, timeout=60))
                session.state["push_receipt"] = final
                write_json(root / "PUSH_RECEIPT.json", final)
                print("RESULTS PUSH VERIFIED: " + final["commit"], flush=True)
                if repo.is_dir() and session.remaining() > 25:
                    bundle = remote_dir + "/code_with_results.bundle"
                    command = " ".join(map(shlex.quote, ["git", "-C", final["worktree"], "bundle", "create", bundle,
                        "refs/heads/" + final["branch"]]))
                    session.remote("make_final_code_bundle", command, timeout=45)
                    session.copy("download_final_code_bundle", bundle, root / "code.bundle.part", timeout=60)
                    (root / "code.bundle.part").replace(root / "code.bundle")
                    session.command("fetch_final_local_checkpoint", ["git", "-C", str(repo), "fetch",
                        str(root / "code.bundle"), "refs/heads/" + final["branch"]], timeout=30)
                    session.command("update_final_local_checkpoint", ["git", "-C", str(repo), "merge",
                        "--ff-only", "FETCH_HEAD"], timeout=30)
            except Exception as error:
                session.state["results_push_error"] = str(error)
        session.save()
        # Save standalone next-device commands; local data remains beside the repo.
        (root / "CONTINUE_ON_OTHER_DEVICE.md").write_text(
            "# Continue locally without NIH\n\nCopy/extract this whole folder to the other device.\n\n"
            "```bash\ncd /path/to/TMEM106B_portable_folder\n"
            "python3 repo/scripts/finish_portable_session.py --offline --session \"$PWD\" --minutes 40\n"
            "```\n\nOpen `repo` in Codex and read `docs/continuation_20261027/CODEX_NEXT.md`. "
            "Code/history is also in `code.bundle`; image data is in `dataset`. "
            "A Python virtual environment must be recreated on the second device.\n")
        (root / "CONTINUE_LOCAL.sh").write_text(
            '#!/usr/bin/env bash\nset -euo pipefail\n'
            'tmem_root="$(cd "$(dirname "$0")" && pwd)"\n'
            'for tmem_python in python3.12 python3.11 python3.13 python3.14 python3; do\n'
            '  if command -v "$tmem_python" >/dev/null 2>&1 && "$tmem_python" -c "import sys;raise SystemExit(sys.version_info < (3,11))"; then\n'
            '    exec "$tmem_python" "$tmem_root/repo/scripts/finish_portable_session.py" --offline --session "$tmem_root" --minutes 40\n'
            '  fi\ndone\nprintf "Install Python 3.11+ on this device, then rerun this file.\\n" >&2\nexit 1\n')
        (root / "START_CODEX.sh").write_text(
            '#!/usr/bin/env bash\nset -euo pipefail\n'
            'tmem_root="$(cd "$(dirname "$0")" && pwd)"\n'
            'cd "$tmem_root/repo"\n'
            'if [[ -f "$tmem_root/.venv/bin/activate" ]]; then source "$tmem_root/.venv/bin/activate"; fi\n'
            'if command -v codex >/dev/null 2>&1; then\n'
            '  exec codex "Read docs/continuation_20261027/CODEX_NEXT.md and the session results, then continue the remaining local work. This device has no NIH access. The dataset is in ../dataset and benchmark outputs are in ../benchmarks."\n'
            'fi\nprintf "Open this repo folder in Codex and paste the prompt from docs/continuation_20261027/CODEX_NEXT.md.\\n"\n'
            'printf "%s\\n" "$PWD"\n')
        print("Packaging the transferable folder; no virtual environment or SSH sockets are included.", flush=True)
        try:
            transfer, checksum = make_archive(root)
            print("TRANSFER_ZIP=" + str(transfer) + "\nTRANSFER_SHA256=" + checksum, flush=True)
        except Exception as error:
            print("ZIP creation failed; copy the preserved folder: " + str(error), flush=True)
        print("SESSION_FOLDER=" + str(root), flush=True)
        print("SESSION_STATUS=" + ("complete" if not errors and benchmark_status == "completed" else "partial_preserved"), flush=True)
        if session.state.get("push_receipt"):
            print("GITHUB_BRANCH=" + session.state["push_receipt"].get("url", ""), flush=True)
        if sys.platform == "darwin":
            subprocess.run(["open", "-R", str(transfer or root)], check=False)
        if session.socket_directory:
            for host in ["biowulf.nih.gov", "helix.nih.gov"]:
                try:
                    subprocess.run(["ssh", *session.ssh(), "-O", "exit", "rodriguezmak@" + host],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5, check=False)
                except Exception:
                    pass
            shutil.rmtree(session.socket_directory, ignore_errors=True)
    return 0 if session.state.get("push_receipt") else 1


if __name__ == "__main__":
    raise SystemExit(main())
