#!/bin/bash
#SBATCH --job-name=tmem_real_pilot_v2
#SBATCH --time=06:00:00
#SBATCH --cpus-per-task=4
#SBATCH --mem=48g
set -euo pipefail
umask 077
: "${TMEM_KIT:?}"
: "${TMEM_PYTHON:?}"
: "${TMEM_MANIFEST:?Set the actual field or well-mosaic manifest}"
: "${TMEM_PILOT_OUT:?Set a NEW private durable pilot directory}"
: "${TMEM_PILOT_WELL_A:?Set actual first well in manifest}"
: "${TMEM_PILOT_WELL_B:?Set actual second well in manifest}"
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
"$TMEM_PYTHON" -B "$TMEM_KIT/full_dataset.py" pilot \
  --manifest "$TMEM_MANIFEST" --out "$TMEM_PILOT_OUT" \
  --wells "$TMEM_PILOT_WELL_A" "$TMEM_PILOT_WELL_B"
