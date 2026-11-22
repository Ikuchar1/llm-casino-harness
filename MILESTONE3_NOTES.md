# Milestone 3 Notes

Findings log for the paper writers, newest at the bottom. Plain language; numbers are exact.
Milestone 2 material lives in `NOTES_FOR_PAPER.md` (frozen).

## 2026-11-22

### HCC setup works
- Ollama on UNL HCC Swan via the module `ollama-gpu/0.15` (server version 0.15.6).
- Model `qwen2.5:7b`, digest `845dbda0ea48` (same as on the Mac).
- The HCC smoke runs ran on a **Tesla P100-PCIE-16GB** GPU (got one immediately).
- Speed: about 2.3 s per decision on the HCC GPU vs about 3.7 s on the M2 Mac.

### Mac vs HCC on the same 20 hands: DIVERGES
- Same everything we control: seed 2026, prompt baseline-v2, temperature 0, Ollama seed 42.
- 9 of 22 comparable first actions differ; only 1 of 22 replies is word-for-word identical.
- Mac: 50.0% accuracy (11/22), payout +0. HCC: 55.6% (15/27), payout +6.
- Causes are confounded: different Ollama version (0.35.0 on the Mac vs 0.15.6 on HCC) and
  different hardware/backend (Apple Metal vs NVIDIA CUDA). We cannot say which one matters.

### HCC vs HCC rerun: IDENTICAL
- Two HCC smoke runs (both on a P100) agree on 27/27 actions and 27/27 reply texts.

### Decision: all final runs on HCC, one pinned GPU type
- Every final run (baseline and every ablation config) runs on HCC with the same GPU type
  (pinned in `hcc/full_run.sbatch` and `hcc/smoke.sbatch`: `gpu_p100`) and the same Ollama module.
- The Mac is used only for development and testing.
- The Milestone 2 numbers (Mac, prompt v2) stay as reported for Milestone 2 and are not mixed
  with the final runs.

### Decision: final runs use prompt baseline-v3
- v3 adds one line under 10-value and ace upcards: "Dealer checked for blackjack: no blackjack."
  (the dealer peeks, so at any player decision the dealer is known not to have blackjack).
- A v3 HCC baseline is rerun and is the reference for all ablation configs.

### Worth discussing in the paper: reproducibility
- Temperature 0 is deterministic for a given software + hardware stack, not across stacks.
  Reproducing our numbers requires pinning the Ollama version and the hardware, not only the
  model digest, seed and temperature. Run metadata now records hostname, OS, GPU names and the
  SLURM job id for this reason.
