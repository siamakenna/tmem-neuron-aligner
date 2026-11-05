#!/bin/bash
#SBATCH --job-name=tmem_headers_v2
#SBATCH --time=04:00:00
#SBATCH --cpus-per-task=2
#SBATCH --mem=16g
set -euo pipefail
umask 077
: "${TMEM_KIT:?Set the actual unpacked kit directory}"
: "${TMEM_RAW_ROOT:?Set the actual original ND2 directory on Biowulf}"
: "${TMEM_OUT_ROOT:?Set a NEW private inventory directory}"
: "${TMEM_PYTHON:?Set a validated Python executable on Biowulf}"
[[ -d "$TMEM_RAW_ROOT" && -f "$TMEM_KIT/full_dataset.py" && -x "$TMEM_PYTHON" ]]
case "$TMEM_OUT_ROOT" in /data/*|/vf/users/*) ;; *) printf 'STOP: use durable private /data output.\n' >&2; exit 2;; esac
"$TMEM_PYTHON" -B "$TMEM_KIT/full_dataset.py" inventory \
  --root "$TMEM_RAW_ROOT" --out "$TMEM_OUT_ROOT" \
  --profile "$TMEM_KIT/february.profile.json" --expect-february-counts
