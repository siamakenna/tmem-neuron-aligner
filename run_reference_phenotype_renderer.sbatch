#!/bin/bash
#SBATCH --job-name=tmem_ref_pheno
#SBATCH --partition=norm
#SBATCH --cpus-per-task=2
#SBATCH --mem=8g
#SBATCH --time=00:45:00
#SBATCH --output=/data/%u/tmem106b/logs/tmem_ref_pheno_%j.out
#SBATCH --error=/data/%u/tmem106b/logs/tmem_ref_pheno_%j.err

set -euo pipefail
cd /data/$USER/projects/tmem-neuron-aligner
module purge
module load python/3.11
source .venv/bin/activate
mkdir -p /data/$USER/tmem106b/logs /data/$USER/tmp/matplotlib
export MPLCONFIGDIR=/data/$USER/tmp/matplotlib

ATLAS=/data/$USER/tmem106b/processed/multi_neuron_atlas_v2
CUR=/data/$USER/tmem106b/share/TMEM106B_neuron_atlas_curated_v1_20260831
OUT=$CUR/04_VIDEOS/phenotype_reference_test

mkdir -p "$OUT"

python scripts/render_curated_neuron_phenotypes.py \
  --atlas-root "$ATLAS" \
  --output-root "$OUT" \
  --neuron-ids J05_N015 N05_N011 F05_N025 E05_N071 \
  --days 8 12 16 20 25 29 32 36 39 \
  --alignment-channel 2 \
  --mcherry-channel 1 \
  --bbox-size 128 \
  --identity-consensus-fraction 0.60 \
  --phenotype-dilation 1 \
  --min-core-area 80 \
  --max-core-area 2500 \
  --segmentation-min-area 180 \
  --background-exclusion 8 \
  --puncta-min-size 6 \
  --secondary-search-radius 52 \
  --secondary-min-distance 14 \
  --secondary-peak-ratio-threshold 0.55 \
  --secondary-area-ratio-threshold 0.30 \
  --secondary-score-threshold 0.40 \
  --fps 10 \
  --hold-seconds 1.0
