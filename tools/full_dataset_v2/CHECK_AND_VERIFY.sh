#!/bin/bash
set -euo pipefail
umask 077
tmem_kit="$(cd "$(dirname "$0")" && pwd)"
if [[ -f "$tmem_kit/config.env" ]]; then source "$tmem_kit/config.env"; fi
: "${TMEM_REPO:?Copy config.env.example to config.env and set the actual current checkout}"
: "${TMEM_RAW_ROOT:?Set the original ND2 source directory on this device}"
: "${TMEM_PYTHON:?Set the tested environment python executable}"
: "${TMEM_PRIVATE_BASE:?Set a private output parent outside repo and raw source}"
[[ -f "$TMEM_REPO/pyproject.toml" && -d "$TMEM_REPO/src/tmem_align" ]] || { printf 'STOP: actual project checkout not found: %s\n' "$TMEM_REPO" >&2; exit 2; }
[[ -d "$TMEM_RAW_ROOT" && -x "$TMEM_PYTHON" ]] || { printf 'STOP: original source or tested Python not found; correct config.env.\n' >&2; exit 2; }
"$TMEM_PYTHON" - "$TMEM_PRIVATE_BASE" "$TMEM_REPO" "$TMEM_RAW_ROOT" <<'PY'
from pathlib import Path
import sys
out, repo, raw = map(lambda s: Path(s).expanduser().resolve(), sys.argv[1:])
for source in [repo, raw]:
    if out.is_relative_to(source) or source.is_relative_to(out):
        raise SystemExit("STOP: private output parent must be disjoint from repo and original ND2 root")
PY
mkdir -p "$TMEM_PRIVATE_BASE"
tmem_session="$(mktemp -d "$TMEM_PRIVATE_BASE/source_and_tests_XXXXXXXX")"
printf 'SESSION=%s\n' "$tmem_session"
tmem_stage="scientific_python_imports"
trap 'printf "{\"status\":\"failed\",\"stage\":\"%s\"}\n" "$tmem_stage" > "$tmem_session/SESSION_STATUS.json"; printf "STOPPED during %s. Keep: %s\n" "$tmem_stage" "$tmem_session" >&2' ERR
"$TMEM_PYTHON" -c 'import sys; assert sys.version_info >= (3,11); import numpy, PIL, nd2, skimage, tifffile, scipy, pandas, pytest, imageio; print("Scientific Python imports: PASS", sys.executable)'
tmem_stage="github_source_capture"
git -C "$TMEM_REPO" rev-parse HEAD > "$tmem_session/LOCAL_HEAD.txt"
git -C "$TMEM_REPO" status --short --branch > "$tmem_session/LOCAL_STATUS.txt"
if git -C "$TMEM_REPO" fetch --prune origin > "$tmem_session/GITHUB_FETCH.log" 2>&1; then
  git -C "$TMEM_REPO" rev-parse origin/main > "$tmem_session/FRESH_ORIGIN_MAIN.txt"
  printf 'GitHub references freshly fetched. Local science files preserved.\n'
else
  printf 'GitHub fetch failed; details: %s/GITHUB_FETCH.log\n' "$tmem_session"
fi
"$TMEM_PYTHON" -B "$tmem_kit/full_dataset.py" source --repo "$TMEM_REPO" --out "$tmem_session/SOURCE_PRIVATE.json" > "$tmem_session/source_capture.log"
printf 'Local source status:\n'
cat "$tmem_session/LOCAL_STATUS.txt"
tmem_stage="project_verification"
"$TMEM_PYTHON" -B "$tmem_kit/verify_project.py" --repo "$TMEM_REPO" --out "$tmem_session/verification" "$@"
printf '{"status":"passed","stage":"project_verification"}\n' > "$tmem_session/SESSION_STATUS.json"
printf '\nVERIFICATION=%s/verification/VERIFICATION_PRIVATE.json\n' "$tmem_session"
printf 'Next: inventory original ND2 headers using README.md. No plate job was started.\n'
