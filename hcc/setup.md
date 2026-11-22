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
sbatch hcc/smoke.sbatch      # prints "Submitted batch job <jobid>"
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
