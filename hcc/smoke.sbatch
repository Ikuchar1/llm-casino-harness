#!/bin/bash
#SBATCH --job-name=bj_smoke
#SBATCH --partition=gpu
#SBATCH --gres=gpu:1
#SBATCH --mem=16G
#SBATCH --time=01:00:00
#SBATCH --output=bj_smoke.%j.out
# To pin a GPU type, add a line like this (see `sinfo -p gpu -o "%N %f"` for features):
##SBATCH --constraint=gpu_l40s

# 20-hand smoke test of the blackjack baseline on HCC Swan.
# Submit from the repo root:  sbatch hcc/smoke.sbatch
# (no `set -u`: module scripts may reference unset variables)
set -eo pipefail

cd "$SLURM_SUBMIT_DIR"

module purge
# Check the available versions with `module avail ollama` (HCC docs also mention ollama/0.11).
module load ollama-gpu/0.15

echo "=== job $SLURM_JOB_ID on $(hostname) at $(date) ==="
nvidia-smi
ollama --version || true  # warns that no server is running yet; the client version is what we want

# Keep model weights on $NRDSTOR ($HOME is small).
# Alternative: `module load mldata/1.0` for HCC's pre-downloaded models (it sets the models path itself;
# then drop this export and the `ollama pull` below if qwen2.5:7b is already there).
export OLLAMA_MODELS=$NRDSTOR/OLLAMA_MODELS
mkdir -p "$OLLAMA_MODELS"

# Per-job port so two jobs on one node don't collide. The ollama CLI and the
# harness (agent/ollama_client.py) both read OLLAMA_HOST.
PORT=$((20000 + SLURM_JOB_ID % 20000))
export OLLAMA_HOST=127.0.0.1:$PORT

SERVE_LOG="ollama_serve.$SLURM_JOB_ID.log"
ollama serve > "$SERVE_LOG" 2>&1 &
OLLAMA_PID=$!
trap 'kill $OLLAMA_PID 2>/dev/null || true' EXIT

echo "Waiting for ollama serve on $OLLAMA_HOST (log: $SERVE_LOG)"
for _ in $(seq 1 60); do  # 60 x 2 s = 2 minutes
    if curl -sf "http://$OLLAMA_HOST/api/tags" > /dev/null; then
        READY=1
        break
    fi
    if ! kill -0 "$OLLAMA_PID" 2>/dev/null; then
        echo "ERROR: ollama serve exited early. Last lines of $SERVE_LOG:" >&2
        tail -n 30 "$SERVE_LOG" >&2
        exit 1
    fi
    sleep 2
done
if [ -z "${READY:-}" ]; then
    echo "ERROR: ollama serve not ready after 2 minutes. Last lines of $SERVE_LOG:" >&2
    tail -n 30 "$SERVE_LOG" >&2
    exit 1
fi
echo "ollama serve is up"

ollama pull qwen2.5:7b

# Call the env's python by absolute path instead of `conda activate`. sbatch copies
# the submitting shell's environment, so if bj was active at submit time conda sees
# CONDA_PREFIX already set and skips fixing PATH after `module purge`; bare `python`
# then resolves to anaconda base (wrong version, no `requests`).
PY="$NRDSTOR/envs/bj/bin/python"
if [ ! -x "$PY" ]; then
    echo "ERROR: $PY not found or not executable. Create the env first (see hcc/setup.md)." >&2
    exit 1
fi
"$PY" --version

# Note: re-using --out resumes the run, so a second smoke job with this same
# directory plays 0 new hands. Delete runs/hcc_smoke_seed2026 to start fresh.
"$PY" scripts/run_baseline.py --hands 20 --seed 2026 --model qwen2.5:7b --out "${1:-runs/hcc_smoke_seed2026}"

# Shows whether the model ran on the GPU ("100% GPU") or fell back to CPU.
ollama ps
echo "=== done at $(date) ==="
