# Run comparison

| run_id | prompt_version | Harness config | Model | Hands | Decisions | Accuracy (95% CI) | Invalid rate (95% CI) | Mean return/hand (95% CI) |
|---|---|---|---|---|---|---|---|---|
| `baseline_qwen2.5-7b_seed2026_20261122-093657` | not logged | baseline (components on: none) | `qwen2.5:7b` | 20 | 28 | 64.3% (18/28; 95% CI 45.8%-79.3%) | 0.0% (0/28; 95% CI 0.0%-12.1%) | -0.200 units/hand (95% CI -0.887 to +0.487; n = 20 hands) |
| `baseline_qwen2.5-7b_seed2026_20261122-093942` | baseline-v2 | baseline (components on: none) | `qwen2.5:7b` | 20 | 22 | 50.0% (11/22; 95% CI 30.7%-69.3%) | 0.0% (0/22; 95% CI 0.0%-14.9%) | +0.000 units/hand (95% CI -0.735 to +0.735; n = 20 hands) |

Accuracy and invalid-rate CIs are Wilson 95% intervals; return CIs are normal-approximation 95% intervals. Each run's full breakdown is in its own subfolder.

- `comparison_accuracy.png`: decision accuracy per run with Wilson 95% CIs; n = decisions.
