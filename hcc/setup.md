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
