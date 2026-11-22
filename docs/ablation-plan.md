# Blackjack ablation plan (decided 2026-11-22)

The terms are defined in `CONTEXT.md`. The reasoning for running everything on HCC is in `docs/adr/0002`.

## Configurations (6 per model)

| Name | Probability tool | Strategy information | Self-evaluation |
|---|---|---|---|
| `baseline` | | | |
| `prob` | ✓ | | |
| `prob_strat` | ✓ | ✓ | |
| `prob_strat_self` | ✓ | ✓ | ✓ |
| `strat` | | ✓ | |
| `self` | | | ✓ |

Memory is poker-only. The models are `qwen2.5:7b` and `qwen2.5:14b`, so there are 12 runs in total. The `qwen2.5:7b` baseline already exists: `runs/hcc_baseline_v3_seed2026` and `runs/hcc_scenarios_v3_seed2026` on HCC.

Every run uses prompt baseline-v3, run seed 2026, 1000 natural hands plus the 330-cell scenario set, temperature 0 with Ollama seed 42, and num_predict 400. All runs are on HCC with `gpu_p100`.

## Probability tool

The harness writes these odds into every decision prompt. The model never calls a function.

1. The chance of busting if the player hits exactly once. It is 0% for soft hands where a hit can't bust.
2. The dealer's final-total distribution for the upcard: 17, 18, 19, 20, 21, bust. When the upcard is a 10 or an Ace it is conditioned on the dealer not having blackjack, because the dealer peeks.
3. Standing now: the chance to win, push and lose.

Compute these exactly from a 6-deck shoe with the visible cards removed (the player's cards and the dealer upcard), matching `blackjack/ev.py`. Do NOT give the EV of each action, because its largest value is basically the answer.

## Strategy information

About 8 plain-English principles, never the full chart. Each principle has to agree with basic strategy on every cell it covers. Every basic strategy cell is labelled covered or uncovered, and accuracy is reported for each group.

## Self-evaluation

1. The model gives its first answer as it does now.
2. The same conversation continues with a generic, content-free re-check prompt. It names the first action and asks the model to re-check that answer against the rules and its cards, then reply with a final `ACTION:`.
3. The final answer is graded.
4. Both answers are logged, and each flip is counted as a fix or a break.
5. If the second reply is invalid, the first answer is kept and the decision is not counted as invalid. A first answer that was invalid stays invalid unless the second reply is valid.

## Statistics

- Each configuration is compared with the baseline for the same model using McNemar's test on the paired first decisions: the same hand and the same scenario cell.
- Scenario cells and natural hands are tested separately and never pooled.
- Holm correction is applied across the comparisons.
- Report the accuracy difference with a 95% CI and the change in EV loss.
- Later decisions in a hand are reported but not tested, because they are unpaired.

## Workflow

1. Build and test on the Mac, with a 20-hand smoke test per configuration.
2. Run an HCC smoke test of every configuration at 20 hands.
3. Ian submits all the full jobs at once.
4. Results are due by 2026-11-29. Presentations start 2026-12-03.

The demo and poker come later.
