#!/bin/bash
#SBATCH --job-name=tmem_atlas_v2
#SBATCH --partition=norm
#SBATCH --cpus-per-task=2
#SBATCH --mem=16g
#SBATCH --time=02:00:00
#SBATCH --output=/data/%u/tmem106b/logs/tmem_atlas_v2_%j.out
#SBATCH --error=/data/%u/tmem106b/logs/tmem_atlas_v2_%j.err

set -euo pipefail
cd /data/$USER/projects/tmem-neuron-aligner
module purge
module load python/3.11
source .venv/bin/activate
mkdir -p /data/$USER/tmem106b/logs /data/$USER/tmp/matplotlib
export MPLCONFIGDIR=/data/$USER/tmp/matplotlib

python scripts/build_multi_neuron_longitudinal_atlas_v2.py \
  --processed-root /data/$USER/tmem106b/processed \
  --output-root /data/$USER/tmem106b/processed/multi_neuron_atlas_v2 \
  --wells E05 F05 I05 J05 M05 N05 \
  --days 8 12 16 20 25 29 32 36 39 \
  --alignment-channel 2 \
  --mcherry-channel 1 \
  --pixel-size-um 0.647675729 \
  --bbox-size 128 \
  --template-size 64 \
  --search-radius 48 \
  --max-videos 25 \
  --min-valid-days-for-video 8 \
  --fps 10 \
  --hold-seconds 0.8 \
  --write-xlsx
