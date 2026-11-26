# Running the harness on HCC Swan

**SLURM** is the job scheduler on HCC clusters: you don't run heavy work in the shell, you submit a
job script and SLURM runs it on a GPU node when one is free. **sbatch** submits a script, **squeue**
lists your queued and running jobs. `$NRDSTOR` is your large work storage (use it instead of `$HOME`).

## One-time setup

1. In Open OnDemand, open **Clusters > Swan Shell Access**.
2. Go to work storage: `cd $NRDSTOR`
3. Get the code (the branch must be pushed to GitHub first):
   ```bash
   git clone https://github.com/Ikuchar1/llm-casino-harness.git
   cd llm-casino-harness
   git checkout worktree-ablation-phase
   ```
   Alternative: zip the repo locally, upload it with OnDemand **Files**, and `unzip` it in `$NRDSTOR`.
4. Create the Python environment (once):
   ```bash
   module load anaconda
   conda create -p $NRDSTOR/envs/bj python=3.11 -y
   conda activate $NRDSTOR/envs/bj
   pip install -r requirements.txt
   python -m pytest -q   # optional: all tests should pass (no Ollama needed)
   ```

## Run the 20-hand smoke test

From the repo root (`cd $NRDSTOR/llm-casino-harness`):

```bash
sbatch hcc/smoke.sbatch      # prints "Submitted batch job <jobid>"; works with or without the env active
squeue -u $USER              # ST column: PD = waiting for a GPU, R = running; gone = finished
```

When it finishes, read the logs in the repo root:

```bash
less bj_smoke.<jobid>.out        # the job's output
less ollama_serve.<jobid>.log    # the Ollama server's own log, if something went wrong
```

## What success looks like

- `bj_smoke.<jobid>.out` shows `nvidia-smi`, `ollama serve is up`, the model pull, then 20 progress
  lines `hand    1 (1/20) ...` through `hand   20 (20/20) ...`, then `ollama ps` with `100% GPU`.
- `runs/hcc_smoke_seed2026/` has `hands.jsonl` with 20 lines (`wc -l runs/hcc_smoke_seed2026/hands.jsonl`),
  plus `decisions.jsonl` and `metadata.json`. In `metadata.json`, `ollama_url` is
  `http://127.0.0.1:<port>` and the last session's `status` is `completed`.

Rerunning with the same `--out` resumes instead of starting over, so delete
`runs/hcc_smoke_seed2026` before a fresh smoke test.

## GPU type

Both `smoke.sbatch` and `full_run.sbatch` pin `#SBATCH --constraint=gpu_p100` (Tesla P100; the
bit-identical smoke pair ran on one). All final runs must use the same GPU type. Check the feature
names Swan offers with:

```bash
sinfo -p gpu -o "%f" | tr ',' '\n' | sort -u
```

## Full run

From the repo root:

```bash
sbatch hcc/full_run.sbatch                          # label v3, model qwen2.5:7b, config baseline
sbatch hcc/full_run.sbatch v3b                      # another label (e.g. a rerun), same model
sbatch hcc/full_run.sbatch v3 qwen2.5:7b prob       # an ablation config
sbatch hcc/full_run.sbatch v3 qwen2.5:14b prob      # the same config on the 14b model
```

The arguments are positional: `$1` label (default `v3`), `$2` Ollama model tag (default
`qwen2.5:7b`), `$3` harness config (default `baseline`; one of `baseline`, `prob`, `prob_strat`,
`prob_strat_self`, `strat`, `self`, see `docs/ablation-plan.md`). To pass a config, give the label
and model too.

The job runs the 1000 natural hands, then the 330-cell scenario set, both with seed 2026 and the
chosen config. Outputs:

- `runs/hcc_baseline_<label>[_<config>]_seed2026[_<model>]/` and
  `runs/hcc_scenarios_<label>[_<config>]_seed2026[_<model>]/`. `_<config>` is added for every
  config except `baseline`, and `_<model>` (with `:` replaced by `-`) for every model except
  `qwen2.5:7b`. The defaults therefore give exactly `runs/hcc_baseline_v3_seed2026/` and
  `runs/hcc_scenarios_v3_seed2026/` (the existing 7b baseline); `v3 qwen2.5:7b prob` gives
  `runs/hcc_baseline_v3_prob_seed2026/`.
- `bj_full.<jobid>.out` (progress lines) and `ollama_serve.<jobid>.log` in the repo root

**After a timeout** (8 hour limit), resubmit the exact same command. Both scripts resume from the
existing `--out` folder: finished hands are skipped and new ones appended, so a finished baseline
plays 0 hands and the job moves on to the scenarios. Check the last session's `status` in each
`metadata.json` (`completed` when done). Use a new label to start from scratch instead.

## All ablation runs at once (`hcc/submit_all.sh`)

`hcc/submit_all.sh` submits every remaining final run: the 7b baseline already exists, so that is
5 configs on `qwen2.5:7b` (`prob`, `prob_strat`, `prob_strat_self`, `strat`, `self`) and all 6 on
`qwen2.5:14b`, 11 jobs. Run it on the login node from the repo root, after `git pull`:

```bash
cd $NRDSTOR/llm-casino-harness
git pull
hcc/submit_all.sh --smoke --dry-run   # print the sbatch commands only
hcc/submit_all.sh --smoke             # smoke first: every config on both models
squeue -u $USER
```

It first submits one `hcc/pull_model.sbatch` job per model. That job pulls the model into
`$NRDSTOR/OLLAMA_MODELS` only if `ollama show <model>` doesn't find it (`qwen2.5:14b` is ~9 GB at
q4 and fits a P100's 16 GB), so six jobs never download it at the same time. Every other job waits
for its model's pull job (`--dependency=afterok`). The run jobs also pull only if missing now,
because an unconditional pull can fetch new weights behind the same tag (a changed digest stops
a resume). If a pull job fails, the jobs waiting on it stay pending with `DependencyNeverSatisfied`:
`scancel` them, fix the pull, and submit again.

**Smoke** (`--smoke`): one `hcc/smoke_configs.sbatch` job per model (1.5 h limit) that runs every
config for 20 natural hands and the first 10 scenarios, seed 2026, into
`runs/hcc_cfgsmoke_<config>_<model>/` and `runs/hcc_cfgsmoke_scenarios_<config>_<model>/` (`:` in the
model becomes `-`, e.g. `runs/hcc_cfgsmoke_self_qwen2.5-14b/`). Check each one:

```bash
less bj_smoke_cfg.<jobid>.out
wc -l runs/hcc_cfgsmoke_*/hands.jsonl          # 20 per natural folder, 10 per scenario folder
grep -c '"invalid": true' runs/hcc_cfgsmoke_*/decisions.jsonl
```

Delete `runs/hcc_cfgsmoke_*` before another smoke (re-using a folder resumes it).

**Full runs**, once the smoke looks right:

```bash
hcc/submit_all.sh --dry-run     # check the 11 commands
hcc/submit_all.sh               # label v3; `hcc/submit_all.sh v3b` for a fresh label
```

It prints one job id per run. The outputs are the `full_run.sbatch` folders, e.g.
`runs/hcc_baseline_v3_prob_seed2026/` (7b) and `runs/hcc_baseline_v3_self_seed2026_qwen2.5-14b/`.

Time limits: 8 h for every job except the two 14b self-evaluation configs (`self`,
`prob_strat_self`), which get 16 h. The 7b baseline took ~1.1 h for 1000 hands on a P100
(~2.3 s/decision); the 14b is roughly twice as slow, and self-evaluation makes a second model call
per decision, so those two can approach 8 h. A longer limit can wait longer in the queue.

**After a timeout**, resubmit just that run with the same arguments; it resumes from its folders:

```bash
sbatch --time=16:00:00 hcc/full_run.sbatch v3 qwen2.5:14b self
```

## Poker headline runs (`hcc/submit_poker.sh`)

Eight matches, one SLURM job each: `qwen2.5:7b`, setups `plain` and `memory` against the bots
`calling_station`, `maniac`, `rock` and `control`, 500 seed pairs (1000 hands) each at seed 2026,
so both setups are dealt the same seeds. Each job is `hcc/poker_run.sbatch <setup> <bot>`, which
calls `scripts/run_poker.py --model qwen2.5:7b --bot <bot> --pairs 500 --seed 2026 --setup <setup>`
with `--out results/poker_runs/qwen2.5-7b/<setup>/<bot>`. Logs: `poker_run.<jobid>.out` and
`ollama_serve.<jobid>.log` in the repo root. Like `submit_all.sh`, it first submits one
`hcc/pull_model.sbatch` job and every match waits for it.

On the login node:

```bash
cd $NRDSTOR/llm-casino-harness
git pull
$NRDSTOR/envs/bj/bin/python -m pip install -r requirements.txt   # adds pokerkit==0.7.8 to the bj env
$NRDSTOR/envs/bj/bin/python -c "import pokerkit; print(pokerkit.__name__, 'ok')"
hcc/submit_poker.sh --dry-run    # print the 9 sbatch commands (1 pull + 8 matches) only
hcc/submit_poker.sh              # submit them
squeue -u $USER
tail -n 3 poker_run.*.out        # latest progress line of each match (hands done, bb/100, ETA)
```

`hcc/poker_run.sbatch` checks `import pokerkit` before loading the model and stops with the pip
command above if the env lacks it. A filter limits what is submitted: a setup (`plain`, `memory`), a
bot, or both, e.g. `hcc/submit_poker.sh memory`, `hcc/submit_poker.sh rock`,
`hcc/submit_poker.sh memory rock`.

Time limits: 8 h for `plain`, 12 h for `memory`. The Mac smoke run took ~20 s/hand (~4 decisions at
~5 s), so 1000 hands is ~5.6 h even at Mac speed; blackjack ran ~2.3 s/decision on the P100 against
~3.7 s on the Mac, which puts a plain match nearer 3.5 h. Memory adds a rewrite call every 5 hands
(~200 longer calls) and a longer prompt, hence 12 h.

**After a timeout**, resubmit just that match with the same command; `run_poker.py` resumes from
its folder, even halfway through a seed pair (a finished match plays 0 hands):

```bash
hcc/submit_poker.sh memory rock
# or, without the pull job:
sbatch --time=12:00:00 hcc/poker_run.sbatch memory rock
```

A match is done when its `hands.jsonl` has 1000 lines and the last session's `status` in
`metadata.json` is `completed`:

```bash
wc -l results/poker_runs/qwen2.5-7b/*/*/hands.jsonl
```

**Analysis**, once all eight are done (from the repo root):

```bash
$NRDSTOR/envs/bj/bin/python scripts/analyze_poker.py \
    results/poker_runs/qwen2.5-7b/plain/calling_station results/poker_runs/qwen2.5-7b/plain/maniac \
    results/poker_runs/qwen2.5-7b/plain/rock results/poker_runs/qwen2.5-7b/plain/control \
    results/poker_runs/qwen2.5-7b/memory/calling_station results/poker_runs/qwen2.5-7b/memory/maniac \
    results/poker_runs/qwen2.5-7b/memory/rock results/poker_runs/qwen2.5-7b/memory/control \
    --out results/poker
$NRDSTOR/envs/bj/bin/python scripts/analyze_poker.py --compare results/poker_runs/qwen2.5-7b/plain/calling_station results/poker_runs/qwen2.5-7b/memory/calling_station --out results/poker/compare_calling_station
$NRDSTOR/envs/bj/bin/python scripts/analyze_poker.py --compare results/poker_runs/qwen2.5-7b/plain/maniac results/poker_runs/qwen2.5-7b/memory/maniac --out results/poker/compare_maniac
$NRDSTOR/envs/bj/bin/python scripts/analyze_poker.py --compare results/poker_runs/qwen2.5-7b/plain/rock results/poker_runs/qwen2.5-7b/memory/rock --out results/poker/compare_rock
$NRDSTOR/envs/bj/bin/python scripts/analyze_poker.py --compare results/poker_runs/qwen2.5-7b/plain/control results/poker_runs/qwen2.5-7b/memory/control --out results/poker/compare_control
```

The first writes `results/poker/summary.json` and `summary.csv` for all eight. Each `--compare`
gets its own folder because it writes `comparison.json` (memory minus plain on the same seed pairs)
and would otherwise overwrite the previous bot's.
