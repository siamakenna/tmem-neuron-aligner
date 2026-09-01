#!/bin/bash
#SBATCH --job-name=tmem_pi_pkg_v2
#SBATCH --partition=norm
#SBATCH --cpus-per-task=2
#SBATCH --mem=8g
#SBATCH --time=01:00:00
#SBATCH --output=/data/%u/tmem106b/logs/tmem_pi_pkg_v2_%j.out
#SBATCH --error=/data/%u/tmem106b/logs/tmem_pi_pkg_v2_%j.err

set -euo pipefail
cd /data/$USER/projects/tmem-neuron-aligner
module purge
module load python/3.11
source .venv/bin/activate
mkdir -p /data/$USER/tmem106b/logs /data/$USER/tmp/matplotlib
export MPLCONFIGDIR=/data/$USER/tmp/matplotlib

python scripts/analyze_neuron_atlas_for_pi_v2.py \
  --atlas-root /data/$USER/tmem106b/processed/multi_neuron_atlas_v2 \
  --pair-root /data/$USER/tmem106b/processed/fixed_support_soma_movies/pair_comparisons \
  --output-root /data/$USER/tmem106b/share/TMEM106B_neuron_atlas_v2_20260831 \
  --days 8 12 16 20 25 29 32 36 39 \
  --alignment-channel 2 \
  --contact-box-size 128 \
  --max-contact-sheets 120
