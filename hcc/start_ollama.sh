# Sourced (not run) by hcc/pull_model.sbatch and hcc/smoke_configs.sbatch, from the repo root
# inside a SLURM job: loads the pinned Ollama module, starts `ollama serve` on a per-job port
# and waits for it. Same steps as hcc/full_run.sbatch.

module purge
# Keep this fixed across all final runs (same version as hcc/full_run.sbatch).
module load ollama-gpu/0.15

echo "=== job $SLURM_JOB_ID on $(hostname) at $(date) ==="
nvidia-smi || true
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
READY=""
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
if [ -z "$READY" ]; then
    echo "ERROR: ollama serve not ready after 2 minutes. Last lines of $SERVE_LOG:" >&2
    tail -n 30 "$SERVE_LOG" >&2
    exit 1
fi
echo "ollama serve is up"

# Pull only if missing (see hcc/full_run.sbatch): a pull can change the weights behind a tag.
pull_if_missing() {
    if ollama show "$1" > /dev/null 2>&1; then
        echo "model $1 already in $OLLAMA_MODELS"
    else
        echo "pulling $1 into $OLLAMA_MODELS"
        ollama pull "$1"
    fi
}

# Call the env's python by absolute path instead of `conda activate` (see hcc/smoke.sbatch).
PY="$NRDSTOR/envs/bj/bin/python"
