# All final runs on one pinned HCC GPU type

Every run that goes into the final results (all ablation configurations, both models, including the reference baseline) runs on UNL HCC Swan with the GPU type pinned to `gpu_p100` and the same Ollama module (`ollama-gpu/0.15`, server 0.15.6). The Mac is used only for development and smoke tests. On 2026-11-22 the same 20 hands at temperature 0 with a fixed seed gave different actions on the Mac (Ollama 0.35.0, Metal) and on HCC (Ollama 0.15.6, CUDA) in 9 of 22 comparable decisions. Two HCC runs on the P100 matched exactly, 27 of 27. If configurations ran on different machines, part of every measured difference would come from the machine and not from the harness component.

## Consequences

- The Milestone 2 numbers (Mac, prompt v2) are not mixed with final results. The HCC prompt-v3 baseline is the reference instead.
- Changing the GPU type, the Ollama version, or the model digest partway through means rerunning every configuration for that model.
- Run metadata records the hostname, the GPU and the SLURM job ID, so a run on the wrong hardware can be caught.
