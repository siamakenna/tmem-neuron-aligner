#!/usr/bin/env bash
# Portable verification. No Git checkout or particular working directory needed.
set -euo pipefail
: "${1:?Usage: bash scripts/run_claire_audit.sh NEW_OUTPUT_DIRECTORY [--handoff-root HANDOFF]}"
tmem_claire_out="$1"
shift
tmem_script_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
exec "${TMEM_PYTHON:-python}" "$tmem_script_dir/run_claire_verification.py" \
    --out "$tmem_claire_out" "$@"
