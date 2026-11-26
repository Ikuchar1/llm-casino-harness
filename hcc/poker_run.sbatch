#!/bin/bash
#SBATCH --job-name=pk_run
#SBATCH --partition=gpu
#SBATCH --gres=gpu:1
#SBATCH --mem=16G
#SBATCH --time=12:00:00
#SBATCH --output=poker_run.%j.out
# Same pinned GPU type as hcc/full_run.sbatch (Tesla P100): temperature-0 replies are
# reproducible only on the same software + hardware stack, so every poker match runs on it too.
#SBATCH --constraint=gpu_p100

# One heads-up poker match on HCC Swan: qwen2.5:7b, one setup, one bot, 500 duplicate seed
# pairs (1000 hands) at seed 2026. hcc/submit_poker.sh submits all 8. Submit from the repo root:
#   sbatch hcc/poker_run.sbatch plain calling_station
#   sbatch --time=12:00:00 hcc/poker_run.sbatch memory rock
#   SETUP=memory BOT=rock sbatch hcc/poker_run.sbatch       # same, through the environment
#   $1 (or SETUP) = harness setup: plain or memory
#   $2 (or BOT)   = opponent bot: calling_station, maniac, rock or control
# Output: results/poker_runs/qwen2.5-7b/<setup>/<bot>/ (decisions.jsonl, hands.jsonl,
# metadata.json), and poker_run.<jobid>.out plus ollama_serve.<jobid>.log in the repo root.
#
# Resuming is a feature here: scripts/run_poker.py resumes when --out already exists, even
# halfway through a seed pair. If the job hits the time limit, resubmit the exact same command
# and it continues where it stopped; a finished match plays 0 new hands.
# (no `set -u`: module scripts may reference unset variables)
set -eo pipefail

SETUP="${1:-${SETUP:-}}"
BOT="${2:-${BOT:-}}"
USAGE="usage: sbatch hcc/poker_run.sbatch <plain|memory> <calling_station|maniac|rock|control> (or SETUP=... BOT=...)"
case "$SETUP" in
    plain|memory) ;;
    *) echo "ERROR: unknown setup '$SETUP'. $USAGE" >&2; exit 2 ;;
esac
case "$BOT" in
    calling_station|maniac|rock|control) ;;
    *) echo "ERROR: unknown bot '$BOT'. $USAGE" >&2; exit 2 ;;
esac
MODEL="qwen2.5:7b"
PAIRS=500
SEED=2026
OUT="results/poker_runs/${MODEL//:/-}/${SETUP}/${BOT}"

cd "$SLURM_SUBMIT_DIR"
echo "model $MODEL, setup $SETUP, bot $BOT, $PAIRS pairs, seed $SEED -> $OUT"
source hcc/start_ollama.sh
if [ ! -x "$PY" ]; then
    echo "ERROR: $PY not found or not executable. Create the env first (see hcc/setup.md)." >&2
    exit 1
fi
"$PY" --version
# Fail fast (before the model loads) if the env predates the poker code.
if ! "$PY" -c "import pokerkit" 2> /dev/null; then
    echo "ERROR: pokerkit is not installed in $NRDSTOR/envs/bj. On the login node run:" >&2
    echo "  $PY -m pip install -r requirements.txt" >&2
    exit 1
fi
pull_if_missing "$MODEL"

echo "=== poker: $PAIRS pairs ($((2 * PAIRS)) hands) at $(date) ==="
"$PY" scripts/run_poker.py --model "$MODEL" --bot "$BOT" --pairs "$PAIRS" --seed "$SEED" --setup "$SETUP" --out "$OUT"
ollama ps  # "100% GPU" means the model ran on the GPU
echo "=== done at $(date) ==="
