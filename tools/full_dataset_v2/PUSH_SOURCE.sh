#!/bin/bash
# Publish new source-only tools on an isolated branch. No originals or private reports.
set -euo pipefail
umask 077
tmem_kit="$(cd "$(dirname "$0")" && pwd)"
if [[ -f "$tmem_kit/config.env" ]]; then source "$tmem_kit/config.env"; fi
: "${TMEM_REPO:?Set the actual Git checkout}"
: "${TMEM_PYTHON:?Set the validated Python executable}"
: "${TMEM_PRIVATE_BASE:?Set private outputs outside repo}"
tmem_origin="$(git -C "$TMEM_REPO" remote get-url origin)"
case "$tmem_origin" in
  https://github.com/siamakenna/tmem-neuron-aligner|https://github.com/siamakenna/tmem-neuron-aligner.git|git@github.com:siamakenna/tmem-neuron-aligner|git@github.com:siamakenna/tmem-neuron-aligner.git) ;;
  *) printf 'STOP: origin is not the requested siamakenna/tmem-neuron-aligner repository.\n' >&2; exit 2;;
esac
"$TMEM_PYTHON" - "$TMEM_PRIVATE_BASE" "$TMEM_REPO" "${TMEM_RAW_ROOT:-}" <<'PY'
from pathlib import Path
import sys
out = Path(sys.argv[1]).expanduser().resolve()
for value in filter(None, sys.argv[2:]):
    source = Path(value).expanduser().resolve()
    if out.is_relative_to(source) or source.is_relative_to(out):
        raise SystemExit("STOP: publication output parent must be disjoint from repository and original inputs")
PY
git -C "$TMEM_REPO" fetch origin
git -C "$TMEM_REPO" show-ref --verify --quiet refs/remotes/origin/main
mkdir -p "$TMEM_PRIVATE_BASE"
if [[ -n "${TMEM_PUBLICATION_SESSION:-}" ]]; then
  tmem_session="$TMEM_PUBLICATION_SESSION"
  "$TMEM_PYTHON" - "$tmem_session" "$TMEM_PRIVATE_BASE" <<'PY'
from pathlib import Path
import sys
target,base = (Path(s).expanduser().resolve() for s in sys.argv[1:])
if target == base or not target.is_relative_to(base):
    raise SystemExit("STOP: publication session must be a new child of the private output parent")
PY
  [[ ! -e "$tmem_session" ]]
  mkdir -m 700 "$tmem_session"
else
  tmem_session="$(mktemp -d "$TMEM_PRIVATE_BASE/publish_XXXXXXXX")"
fi
tmem_tag="$("$TMEM_PYTHON" -c 'import hashlib,sys; print(hashlib.sha256(sys.argv[1].encode()).hexdigest()[:8])' "$tmem_session")"
tmem_branch="completion/full-dataset-v2-$(date -u +%Y%m%dT%H%M%SZ)-$tmem_tag"
tmem_checkout="$tmem_session/source"
printf 'PUBLICATION_SESSION=%s\n' "$tmem_session"
trap 'printf "Publication stopped. Preserve: %s\n" "$tmem_session" >&2' ERR
git -C "$TMEM_REPO" worktree add -b "$tmem_branch" "$tmem_checkout" origin/main
tmem_target="$tmem_checkout/tools/full_dataset_v2"
[[ ! -e "$tmem_target" ]] || { printf 'STOP: target already exists on current main; reconcile the existing implementation.\n' >&2; exit 2; }
mkdir -p "$tmem_target"
# Explicit allowlist: config.env, private images/data/reports and old outputs cannot enter Git.
for tmem_file in full_dataset.py project_adapter.py preview_originals.py prepare_site_map.py render_coverage.py reconcile_legacy.py verify_project.py check_project_adapter.py test_full_dataset.py february.profile.json cellpaint.profile.TEMPLATE.json geometry.TEMPLATE.json config.env.example submit_inventory.sbatch submit_pilot.sbatch README.md STATUS.md SOURCE_REVIEW.md CLAIRE_PACKET_CHECKLIST.md CHECK_AND_VERIFY.sh PUSH_SOURCE.sh full_dataset_v2.workflow.yml; do
  cp "$tmem_kit/$tmem_file" "$tmem_target/$tmem_file"
done
mkdir -p "$tmem_checkout/.github/workflows"
[[ ! -e "$tmem_checkout/.github/workflows/full_dataset_v2.yml" ]]
cp "$tmem_kit/full_dataset_v2.workflow.yml" "$tmem_checkout/.github/workflows/full_dataset_v2.yml"
"$TMEM_PYTHON" -B "$tmem_target/verify_project.py" --repo "$tmem_checkout" --out "$tmem_session/verification"
git -C "$tmem_checkout" add -- tools/full_dataset_v2 .github/workflows/full_dataset_v2.yml
git -C "$tmem_checkout" diff --cached --check
git -C "$tmem_checkout" --no-pager diff --cached --stat
git -C "$tmem_checkout" commit -m "Add source-bound ND2 full-dataset diagnostics and resumable task receipts"
git -C "$tmem_checkout" push --set-upstream origin "HEAD:refs/heads/$tmem_branch"
tmem_expected="$(git -C "$tmem_checkout" rev-parse HEAD)"
tmem_actual="$(git -C "$tmem_checkout" ls-remote --heads origin "refs/heads/$tmem_branch" | awk '{print $1}')"
[[ "$tmem_actual" == "$tmem_expected" ]]
printf 'PUSH VERIFIED: %s %s\n' "$tmem_branch" "$tmem_expected"
"$TMEM_PYTHON" - "$tmem_session/PUBLICATION_RECEIPT.json" "$tmem_branch" "$tmem_expected" "$tmem_checkout" <<'PY'
from pathlib import Path
import json,sys
Path(sys.argv[1]).write_text(json.dumps({"repository":"siamakenna/tmem-neuron-aligner","branch":sys.argv[2],"remote_sha":sys.argv[3],"checkout":sys.argv[4],"push_verified":True,"original_data_executed":False},indent=2)+"\n")
PY
cat > "$tmem_session/PR_BODY.md" <<'BODY'
Adds private, source-bound original-ND2 inventory, per-visit channel remapping, durable well/site task receipts and exact-source resume. A separate authenticated-geometry path assembles each visit's fields before well-level registration. Executed stage observers export real-image flowcharts and display-only LUT box comparisons; failed QC is retained.

Includes unit/integration fixtures and a real two-well serial-versus-two-worker pilot gate before generating Swarm commands. A five-channel Cell Paint profile is a usability template; original-batch portability and whole-well/biological validation remain pending. No raw data or private measurements are included.

Validation: new contract tests and affected existing project tests run before publication; exact local logs remain in the publication session. Original-image pilot execution and independent scientific acceptance are separate gates.
BODY
if command -v gh >/dev/null 2>&1 && gh auth status --hostname github.com >/dev/null 2>&1; then
  if ! gh pr create --repo siamakenna/tmem-neuron-aligner --base main --head "$tmem_branch" --draft \
    --title "Add resumable original-ND2 batch diagnostics and actual-image stage exports" \
    --body-file "$tmem_session/PR_BODY.md"; then
    printf 'Source remains pushed. Draft PR: https://github.com/siamakenna/tmem-neuron-aligner/compare/main...%s?expand=1\n' "$tmem_branch"
  fi
else
  printf 'Create the draft PR: https://github.com/siamakenna/tmem-neuron-aligner/compare/main...%s?expand=1\n' "$tmem_branch"
fi
printf 'Publication logs: %s\n' "$tmem_session"
