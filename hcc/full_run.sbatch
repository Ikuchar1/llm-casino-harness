#!/bin/bash
#SBATCH --job-name=bj_full
#SBATCH --partition=gpu
#SBATCH --gres=gpu:1
#SBATCH --mem=16G
#SBATCH --time=08:00:00
#SBATCH --output=bj_full.%j.out
# Pinned GPU type: Tesla P100 (the bit-identical HCC smoke pair ran on a
# Tesla P100-PCIE-16GB). ALL final runs (baseline and every ablation config) must use
# this same GPU type: temperature-0 replies are reproducible only on the same
# software + hardware stack. Verify the feature name on Swan with
#   sinfo -p gpu -o "%f" | tr ',' '\n' | sort -u
# Alternatives: gpu_t4, gpu_v100, gpu_a30, gpu_l40s, gpu_h200. Change it only if you
# rerun everything on the new type.
#SBATCH --constraint=gpu_p100

# Full blackjack run on HCC Swan: 1000-hand baseline, then the 330-cell scenario set.
# Submit from the repo root:
#   sbatch hcc/full_run.sbatch                 # label v3, model qwen2.5:7b
#   sbatch hcc/full_run.sbatch v3 qwen2.5:7b   # same, explicit
# $1 = label (default v3), $2 = Ollama model tag (default qwen2.5:7b).
# Outputs: runs/hcc_baseline_<label>_seed2026 and runs/hcc_scenarios_<label>_seed2026
# (with _<model> appended, ':' replaced by '-', when a non-default model is given).
#
# Resuming is a feature here: both scripts resume when --out already exists (hands
# already in hands.jsonl are skipped). If the job hits the time limit, resubmit the
# exact same command and it continues where it stopped; a finished baseline plays 0
# new hands and the job moves straight on to the scenarios.
# (no `set -u`: module scripts may reference unset variables)
set -eo pipefail

LABEL="${1:-v3}"
MODEL="${2:-qwen2.5:7b}"
SEED=2026
SUFFIX=""
if [ "$MODEL" != "qwen2.5:7b" ]; then
    SUFFIX="_${MODEL//:/-}"
fi
BASELINE_OUT="runs/hcc_baseline_${LABEL}_seed${SEED}${SUFFIX}"
SCENARIOS_OUT="runs/hcc_scenarios_${LABEL}_seed${SEED}${SUFFIX}"

cd "$SLURM_SUBMIT_DIR"

module purge
# Check the available versions with `module avail ollama`. Keep this fixed across all final runs.
module load ollama-gpu/0.15

echo "=== job $SLURM_JOB_ID on $(hostname) at $(date) ==="
echo "label $LABEL, model $MODEL, seed $SEED"
echo "baseline -> $BASELINE_OUT"
echo "scenarios -> $SCENARIOS_OUT"
nvidia-smi
ollama --version || true  # warns that no server is running yet; the client version is what we want

# Keep model weights on $NRDSTOR ($HOME is small).
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

ollama pull "$MODEL"

# Call the env's python by absolute path instead of `conda activate` (see hcc/smoke.sbatch:
# a conda env active at submit time leaves bare `python` pointing at anaconda base).
PY="$NRDSTOR/envs/bj/bin/python"
if [ ! -x "$PY" ]; then
    echo "ERROR: $PY not found or not executable. Create the env first (see hcc/setup.md)." >&2
    exit 1
fi
"$PY" --version

echo "=== baseline: 1000 hands at $(date) ==="
"$PY" scripts/run_baseline.py --hands 1000 --seed "$SEED" --model "$MODEL" --out "$BASELINE_OUT"
ollama ps  # shows whether the model ran on the GPU ("100% GPU") or fell back to CPU

echo "=== scenarios: 330 cells at $(date) ==="
"$PY" scripts/run_scenarios.py --seed "$SEED" --model "$MODEL" --out "$SCENARIOS_OUT"
ollama ps

echo "=== done at $(date) ==="
