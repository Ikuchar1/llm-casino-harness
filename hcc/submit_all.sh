#!/bin/bash
# Submits every remaining final blackjack run on HCC Swan (the 7b baseline already exists as
# runs/hcc_baseline_v3_seed2026). Run it on the login node, from anywhere in the repo:
#
#   hcc/submit_all.sh                # 11 full runs, label v3
#   hcc/submit_all.sh v3b            # same, another label (fresh output folders)
#   hcc/submit_all.sh --smoke        # smoke: every config on both models, 20 hands + 10 scenarios
#   hcc/submit_all.sh --dry-run      # print the sbatch commands without submitting (also with --smoke)
#
# First it submits one hcc/pull_model.sbatch job per model; every run job waits for its
# model's pull job (--dependency=afterok), so the 14b weights (~9 GB) are downloaded once,
# not by six jobs at the same time. If a pull job fails, the jobs waiting on it never start
# (squeue shows "DependencyNeverSatisfied"): fix it, `scancel` them, and submit again.
#
# Full runs (hcc/full_run.sbatch: 1000 natural hands, then the 330 scenarios):
#   qwen2.5:7b   prob prob_strat prob_strat_self strat self
#   qwen2.5:14b  baseline prob prob_strat prob_strat_self strat self
# Time limits: 08:00:00 (the sbatch default) for everything except the two 14b
# self-evaluation configs, which get 16:00:00. The 7b baseline took about 1.1 h for the 1000
# hands on a P100 (~2.3 s/decision); the 14b is roughly 2x slower and self-evaluation makes
# a second call per decision, so 14b self / prob_strat_self can approach 8 h.
#
# A run that hits its time limit resumes: resubmit that one run with the exact same command,
# e.g. `sbatch --time=16:00:00 hcc/full_run.sbatch v3 qwen2.5:14b self` (finished hands are
# skipped; no pull dependency needed then since the model is already there).
set -euo pipefail

cd "$(dirname "$0")/.."

SMOKE=0
DRY_RUN=0
LABEL="v3"
for arg in "$@"; do
    case "$arg" in
        --smoke) SMOKE=1 ;;
        --dry-run) DRY_RUN=1 ;;
        -*) echo "unknown option $arg" >&2; exit 2 ;;
        *) LABEL="$arg" ;;
    esac
done

submit() {  # prints the job id
    if [ "$DRY_RUN" -eq 1 ]; then
        echo "sbatch $*" >&2
        echo "DRYRUN"  # placeholder job id
    else
        sbatch --parsable "$@" | cut -d';' -f1
    fi
}

# Plain variables, not an associative array, so --dry-run also works with macOS bash 3.2.
PULL_7B=$(submit --job-name=bj_pull_qwen2.5-7b hcc/pull_model.sbatch qwen2.5:7b)
echo "pull   qwen2.5:7b -> job $PULL_7B"
PULL_14B=$(submit --job-name=bj_pull_qwen2.5-14b hcc/pull_model.sbatch qwen2.5:14b)
echo "pull   qwen2.5:14b -> job $PULL_14B"
pull_job() { if [ "$1" = "qwen2.5:14b" ]; then echo "$PULL_14B"; else echo "$PULL_7B"; fi; }

if [ "$SMOKE" -eq 1 ]; then
    for MODEL in qwen2.5:7b qwen2.5:14b; do
        JOB=$(submit --dependency="afterok:$(pull_job "$MODEL")" --job-name="bj_smoke_${MODEL//:/-}" \
            hcc/smoke_configs.sbatch "$MODEL")
        echo "smoke  $MODEL (all 6 configs) -> job $JOB  (runs/hcc_cfgsmoke_<config>_${MODEL//:/-})"
    done
    exit 0
fi

RUNS=(
    "qwen2.5:7b prob"
    "qwen2.5:7b prob_strat"
    "qwen2.5:7b prob_strat_self"
    "qwen2.5:7b strat"
    "qwen2.5:7b self"
    "qwen2.5:14b baseline"
    "qwen2.5:14b prob"
    "qwen2.5:14b prob_strat"
    "qwen2.5:14b prob_strat_self"
    "qwen2.5:14b strat"
    "qwen2.5:14b self"
)
for RUN in "${RUNS[@]}"; do
    read -r MODEL CONFIG <<< "$RUN"
    TIME=08:00:00
    if [ "$MODEL" = "qwen2.5:14b" ] && [[ "$CONFIG" == *self ]]; then
        TIME=16:00:00
    fi
    JOB=$(submit --dependency="afterok:$(pull_job "$MODEL")" --time="$TIME" \
        --job-name="bj_${CONFIG}_${MODEL//:/-}" hcc/full_run.sbatch "$LABEL" "$MODEL" "$CONFIG")
    echo "full   $MODEL $CONFIG (time $TIME) -> job $JOB"
done
echo "Watch with: squeue -u \$USER"
