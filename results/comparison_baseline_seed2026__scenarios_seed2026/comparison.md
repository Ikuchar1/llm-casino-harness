# Run comparison

| run_id | Run type | prompt_version | Harness config | Model | Hands | Decisions | Accuracy (95% CI) | Invalid rate (95% CI) | Mean return/hand (95% CI) | EV loss/decision | EV loss/hand |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `baseline_qwen2.5-7b_seed2026_20261122-094750` | natural | baseline-v2 | baseline (components on: none) | `qwen2.5:7b` | 1000 | 1147 | 41.7% (478/1147; 95% CI 38.9%-44.6%) | 0.8% (9/1147; 95% CI 0.4%-1.5%) | -0.330 units/hand (95% CI -0.424 to -0.236; n = 1000 hands) | 0.3280 | 0.3762 |
| `scenarios_baseline_qwen2.5-7b_seed2026_20261122-105805` | scenario | baseline-v2 | baseline (components on: none) | `qwen2.5:7b` | 330 | 330 | 40.9% (135/330; 95% CI 35.7%-46.3%) | 2.7% (9/330; 95% CI 1.4%-5.1%) | not reported (scenario run) | 0.2655 | 0.2655 |

Runs of different types are shown side by side and not pooled. A natural run weights each basic-strategy cell by how often it is dealt; the scenario set grades every cell exactly once, so the two accuracies answer different questions and are never combined into one number.

For scenario runs, Decisions and every accuracy, invalid and EV-loss figure count only the graded scenario cells (is_scenario_cell = true); follow-up decisions are in comparison.csv (follow_up_decisions, follow_up_accuracy) and in the run's results.md.

Accuracy and invalid-rate CIs are Wilson 95% intervals; return CIs are normal-approximation 95% intervals. EV loss is in units per 1-unit bet (0 = every decision matched basic strategy). Each run's full breakdown is in its own subfolder.

- `comparison_accuracy.png`: decision accuracy per run with Wilson 95% CIs; n = decisions.
