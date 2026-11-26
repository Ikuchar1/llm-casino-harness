#!/bin/bash
# Submits the poker headline runs on HCC Swan: qwen2.5:7b, {plain, memory} x {calling_station,
# maniac, rock, control}, 500 seed pairs (1000 hands) each at seed 2026, so every setup is dealt
# the same seeds; the tools and tools_memory setups (full tools) only when named. Run it on the login node, from anywhere in the repo:
#
#   hcc/submit_poker.sh                  # all 8 plain and memory matches
#   hcc/submit_poker.sh memory           # only the 4 memory matches
#   hcc/submit_poker.sh rock             # only the 2 matches against the rock
#   hcc/submit_poker.sh memory rock      # just that one match
#   hcc/submit_poker.sh --dry-run        # print the sbatch commands without submitting (any filter)
#   hcc/submit_poker.sh tools            # opt-in: the 4 full-tools matches
#   hcc/submit_poker.sh tools_memory rock  # opt-in: full tools plus memory against the rock
#
# A filter word is a setup (plain, memory, tools, tools_memory) or a bot (calling_station,
# maniac, rock, control); setups and bots given are each a subset, so `plain maniac rock` is 2
# matches. With no setup word only plain and memory are submitted: tools and tools_memory run
# only when named.
#
# First it submits one hcc/pull_model.sbatch job for qwen2.5:7b; every match waits for it
# (--dependency=afterok), so the model is pulled once, not by eight jobs at the same time.
# If the pull job fails, the matches waiting on it stay pending with "DependencyNeverSatisfied":
# `scancel` them, fix the pull, and submit again.
#
# Outputs (hcc/poker_run.sbatch): results/poker_runs/qwen2.5-7b/<setup>/<bot>/
#
# Time limits: 08:00:00 for plain, 12:00:00 for memory, 24:00:00 for tools and tools_memory. The Mac smoke run took about 20 s/hand
# (~4 decisions at ~5 s), so 1000 hands is ~5.6 h even at Mac speed; a P100 ran blackjack at
# ~2.3 s/decision vs ~3.7 s on the Mac, which puts a plain match nearer 3.5 h. Memory adds one
# rewrite call every 5 hands (~200 longer calls) and a longer prompt, so it gets 12 h. The tools
# setups make two calls per decision (the answer, then the re-check) with a longer prompt, about
# twice memory's time, so they get 24 h.
#
# A match that hits its time limit resumes, even halfway through a pair: resubmit just that
# match with this script and a filter (e.g. `hcc/submit_poker.sh memory rock`) or directly with
# `sbatch --time=12:00:00 hcc/poker_run.sbatch memory rock`. Same command, same output folder.
set -euo pipefail

cd "$(dirname "$0")/.."

MODEL="qwen2.5:7b"
ALL_SETUPS=(plain memory tools tools_memory)
DEFAULT_SETUPS=(plain memory)  # what runs when no setup word is given
ALL_BOTS=(calling_station maniac rock control)

DRY_RUN=0
SETUPS=()
BOTS=()
for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY_RUN=1 ;;
        plain|memory|tools|tools_memory) SETUPS+=("$arg") ;;
        calling_station|maniac|rock|control) BOTS+=("$arg") ;;
        *) echo "unknown argument $arg (expected --dry-run, a setup: ${ALL_SETUPS[*]}, or a bot: ${ALL_BOTS[*]})" >&2
           exit 2 ;;
    esac
done
# No bot word means every bot; no setup word means DEFAULT_SETUPS. (Filled before any "${X[*]}": an empty array
# counts as unset under `set -u` in macOS bash 3.2, which --dry-run also runs on.)
if [ ${#SETUPS[@]} -eq 0 ]; then SETUPS=("${DEFAULT_SETUPS[@]}"); fi
if [ ${#BOTS[@]} -eq 0 ]; then BOTS=("${ALL_BOTS[@]}"); fi

submit() {  # prints the job id
    if [ "$DRY_RUN" -eq 1 ]; then
        echo "sbatch $*" >&2
        echo "DRYRUN"  # placeholder job id
    else
        sbatch --parsable "$@" | cut -d';' -f1
    fi
}

PULL=$(submit --job-name="pk_pull_${MODEL//:/-}" hcc/pull_model.sbatch "$MODEL")
echo "pull   $MODEL -> job $PULL"

# Same order as the list in the header: setups outer, bots inner (ALL_* order, not argument order).
for SETUP in "${ALL_SETUPS[@]}"; do
    [[ " ${SETUPS[*]} " == *" $SETUP "* ]] || continue
    TIME=08:00:00
    case "$SETUP" in
        memory) TIME=12:00:00 ;;
        tools|tools_memory) TIME=24:00:00 ;;
    esac
    for BOT in "${ALL_BOTS[@]}"; do
        [[ " ${BOTS[*]} " == *" $BOT "* ]] || continue
        JOB=$(submit --dependency="afterok:$PULL" --time="$TIME" --job-name="pk_${SETUP}_${BOT}" \
            hcc/poker_run.sbatch "$SETUP" "$BOT")
        echo "poker  $MODEL $SETUP vs $BOT (time $TIME) -> job $JOB  (results/poker_runs/${MODEL//:/-}/$SETUP/$BOT)"
    done
done
echo "Watch with: squeue -u \$USER"
