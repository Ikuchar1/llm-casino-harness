#!/bin/bash
#SBATCH --job-name=bj_smoke_cfg
#SBATCH --partition=gpu
#SBATCH --gres=gpu:1
#SBATCH --mem=16G
#SBATCH --time=01:30:00
#SBATCH --output=bj_smoke_cfg.%j.out
# Same pinned GPU type as hcc/full_run.sbatch.
#SBATCH --constraint=gpu_p100

# Smoke test of every harness config on one model: for each config, 20 natural hands and the
# first 10 scenario cells, seed 2026. hcc/submit_all.sh --smoke submits this once per model.
# Submit from the repo root:
#   sbatch hcc/smoke_configs.sbatch qwen2.5:14b          # all six configs
#   sbatch hcc/smoke_configs.sbatch qwen2.5:7b self      # only the listed configs
# Outputs (model with ':' -> '-'):
#   runs/hcc_smoke_<config>_<model>/            20 natural hands
#   runs/hcc_smoke_scenarios_<config>_<model>/  first 10 scenarios
# Re-using an output folder resumes it (0 new hands if finished): delete runs/hcc_smoke_* for a fresh smoke.
# (no `set -u`: module scripts may reference unset variables)
set -eo pipefail

MODEL="${1:?usage: sbatch hcc/smoke_configs.sbatch <model tag> [config ...]}"
shift
CONFIGS=("$@")
if [ ${#CONFIGS[@]} -eq 0 ]; then
    CONFIGS=(baseline prob prob_strat prob_strat_self strat self)
fi
HANDS=20
SCENARIOS=10
SEED=2026
TAG="${MODEL//:/-}"

cd "$SLURM_SUBMIT_DIR"
source hcc/start_ollama.sh
if [ ! -x "$PY" ]; then
    echo "ERROR: $PY not found or not executable. Create the env first (see hcc/setup.md)." >&2
    exit 1
fi
"$PY" --version
pull_if_missing "$MODEL"

for CONFIG in "${CONFIGS[@]}"; do
    echo "=== $CONFIG: $HANDS hands at $(date) ==="
    "$PY" scripts/run_baseline.py --hands "$HANDS" --seed "$SEED" --model "$MODEL" --config "$CONFIG" \
        --out "runs/hcc_smoke_${CONFIG}_${TAG}"
    echo "=== $CONFIG: $SCENARIOS scenarios at $(date) ==="
    "$PY" scripts/run_scenarios.py --seed "$SEED" --model "$MODEL" --config "$CONFIG" --limit "$SCENARIOS" \
        --out "runs/hcc_smoke_scenarios_${CONFIG}_${TAG}"
done
ollama ps  # "100% GPU" means the model ran on the GPU
echo "=== done at $(date) ==="
