#!/bin/bash
#SBATCH --job-name=bj_pull
#SBATCH --partition=gpu
#SBATCH --gres=gpu:1
#SBATCH --mem=16G
#SBATCH --time=01:00:00
#SBATCH --output=bj_pull.%j.out
#SBATCH --constraint=gpu_p100

# Makes sure one Ollama model is in $NRDSTOR/OLLAMA_MODELS (pulls it only if missing), then
# prints its digest. hcc/submit_all.sh runs this once per model and makes the run jobs wait
# for it (--dependency=afterok), so several jobs never download the same model at once.
# Submit from the repo root:
#   sbatch hcc/pull_model.sbatch qwen2.5:14b
# (no `set -u`: module scripts may reference unset variables)
set -eo pipefail

MODEL="${1:?usage: sbatch hcc/pull_model.sbatch <model tag>}"
cd "$SLURM_SUBMIT_DIR"
source hcc/start_ollama.sh

pull_if_missing "$MODEL"
ollama list
curl -s "http://$OLLAMA_HOST/api/tags"; echo
echo "=== done at $(date) ==="
