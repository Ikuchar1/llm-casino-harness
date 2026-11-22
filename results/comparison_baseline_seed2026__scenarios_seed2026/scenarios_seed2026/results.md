# Results: scenarios_seed2026

- **Run id:** `scenarios_baseline_qwen2.5-7b_seed2026_20261122-105805`
- **Model:** `qwen2.5:7b` (digest `845dbda0ea48ed749caafd9e6037047aa19acfcfd82e704d7ca97d631a0b697e`), Ollama 0.35.0
- **Prompt version:** baseline-v2
- **Harness config:** baseline (components on: none)
- **Rule set:** 6 decks, dealer stands on soft 17, double after split allowed, max 1 split, split aces get one card, no surrender, no insurance, dealer peeks, blackjack pays 3:2, flat 1-unit bet
- **Sampling:** temperature 0, Ollama seed 42, num_predict 400
- **Run seed:** 2026
- **Run type:** scenario set (scenarios-v1)  |  **Scenario hands:** 330  |  **Graded scenario cells:** 330  |  **Follow-up decisions (not graded as cells):** 187
- **Date:** 2026-11-22 (started 2026-11-22T10:58:05-06:00)

## Headline numbers

> **Scenario run:** every cell metric below (accuracy, invalid actions, breakdowns, confusion matrix, action frequency, mistakes, EV loss, heatmaps) uses only the graded scenario cells, the first decision of each forced hand (is_scenario_cell = true). Later decisions in the same hands are reported only on the "Follow-up decisions" line. Returns are not reported: the forced hands are not a natural sample.

| Metric | Value |
|---|---|
| Decision accuracy on scenario cells (primary metric) | 40.9% (135/330; 95% CI 35.7%-46.3%) |
| Invalid-action rate (scenario cells) | 2.7% (9/330; 95% CI 1.4%-5.1%) |
| Secondary: follow-up decisions (is_scenario_cell = false; not chart cells, not in any other number here) | 30.5% (57/187; 95% CI 24.3%-37.4%); 0 invalid |
| Decisions per hand (all logged decisions) | 1.57 |
| Mean latency per decision | 3.74 s |
| Mean tokens generated per decision (eval_count) | 56.8 |

## Invalid actions by reason

| invalid_reason | Count |
|---|---|
| no_action | 9 |

## Accuracy by hand type

| Hand type | n | Correct | Accuracy | 95% CI | Flag |
|---|---|---|---|---|---|
| hard | 150 | 58 | 38.7% | 31.2%-46.7% |  |
| soft | 80 | 27 | 33.8% | 24.3%-44.6% |  |
| pair | 100 | 50 | 50.0% | 40.4%-59.6% |  |

"small sample" = fewer than 30 decisions.

Pair = splitting was legal at that decision; pairs that could not be split are counted by their hard/soft total.

## Accuracy by dealer upcard

| Upcard | n | Correct | Accuracy | 95% CI | Flag |
|---|---|---|---|---|---|
| 2 | 33 | 11 | 33.3% | 19.8%-50.4% |  |
| 3 | 33 | 15 | 45.5% | 29.8%-62.0% |  |
| 4 | 33 | 13 | 39.4% | 24.7%-56.3% |  |
| 5 | 33 | 21 | 63.6% | 46.6%-77.8% |  |
| 6 | 33 | 21 | 63.6% | 46.6%-77.8% |  |
| 7 | 33 | 15 | 45.5% | 29.8%-62.0% |  |
| 8 | 33 | 8 | 24.2% | 12.8%-41.0% |  |
| 9 | 33 | 12 | 36.4% | 22.2%-53.4% |  |
| 10 | 33 | 11 | 33.3% | 19.8%-50.4% |  |
| A | 33 | 8 | 24.2% | 12.8%-41.0% |  |

"small sample" = fewer than 30 decisions.

J, Q and K are counted as 10.

## Confusion matrix (rows: basic-strategy action, columns: model's chosen action)

| Basic strategy \ Model | hit | stand | double | split | invalid | Total |
|---|---|---|---|---|---|---|
| **hit** | 29 | 14 | 72 | 22 | 5 | 142 |
| **stand** | 5 | 29 | 51 | 3 | 1 | 89 |
| **double** | 7 | 4 | 28 | 8 | 0 | 47 |
| **split** | 0 | 0 | 0 | 49 | 3 | 52 |

"invalid" = invalid action (the engine stood as a fallback; that stand is not counted as a stand choice).

## Action frequency (model vs basic strategy, same decisions)

| Action | Model count | Model % | Basic strategy count | Basic strategy % |
|---|---|---|---|---|
| hit | 41 | 12.4% | 142 | 43.0% |
| stand | 47 | 14.2% | 89 | 27.0% |
| double | 151 | 45.8% | 47 | 14.2% |
| split | 82 | 24.8% | 52 | 15.8% |
| invalid | 9 | 2.7% | 0 | 0.0% |

- The model chose hit on 12.4% of decisions; basic strategy calls for hit on 43.0%.
- The model chose stand on 14.2% of decisions; basic strategy calls for stand on 27.0%.
- The model chose double on 45.8% of decisions; basic strategy calls for double on 14.2%.
- The model chose split on 24.8% of decisions; basic strategy calls for split on 15.8%.

## Mistakes

195 of 330 scenario cells were incorrect. Each cell is played once, so there is no by-count ranking: see the confusion matrix above for mistake types, the costliest mistakes below, and `accuracy_heatmap.png` for which cells were wrong.

## EV loss (secondary metric)

EV loss = EV(basic-strategy action) - EV(action played), in units per 1-unit initial bet; a correct decision has EV loss 0. EVs are exact for 6 decks with the player's cards and the dealer's upcard removed, given the dealer has no blackjack (blackjack/ev.py). Invalid actions are charged for the stand the engine played as a fallback. A few composition-dependent decisions (e.g. a three-card 16 vs 10) have a slightly negative loss when the model deviated from the chart; losses are not clipped. Scenario run: only the graded scenario cell of each hand is counted (is_scenario_cell = true). 

| Metric | Value |
|---|---|
| Total EV loss | 87.607 units over 330 decisions |
| Mean EV loss per decision | 0.2655 units |
| Mean EV loss per hand | 0.2655 units (n = 330 hands) |
| Mean EV loss per mistake | 0.4493 units (n = 195 incorrect decisions) |
| Of which invalid actions | 1.771 units over 9 decisions (mean 0.1968) |
| Decisions where the model beat the chart | 0 (total 0.0000 units) |

### EV loss by hand type

| Hand type | n | Total EV loss | Mean EV loss |
|---|---|---|---|
| hard | 150 | 42.296 | 0.2820 |
| soft | 80 | 12.583 | 0.1573 |
| pair | 100 | 32.729 | 0.3273 |

### Costliest mistakes (top 10 by total EV loss)

| # | Mistake | n | Total EV loss | Mean EV loss |
|---|---|---|---|---|
| 1 | doubled pair 10,10 vs 8 (optimal: stand) | 1 | 2.491 | 2.4908 |
| 2 | doubled pair 10,10 vs 7 (optimal: stand) | 1 | 2.473 | 2.4728 |
| 3 | doubled pair 10,10 vs 9 (optimal: stand) | 1 | 2.455 | 2.4548 |
| 4 | doubled pair 10,10 vs 6 (optimal: stand) | 1 | 2.408 | 2.4076 |
| 5 | doubled pair 10,10 vs 5 (optimal: stand) | 1 | 2.377 | 2.3772 |
| 6 | doubled pair 10,10 vs A (optimal: stand) | 1 | 2.368 | 2.3683 |
| 7 | doubled pair 10,10 vs 4 (optimal: stand) | 1 | 2.366 | 2.3656 |
| 8 | doubled pair 10,10 vs 3 (optimal: stand) | 1 | 2.355 | 2.3555 |
| 9 | doubled pair 10,10 vs 2 (optimal: stand) | 1 | 2.346 | 2.3460 |
| 10 | doubled hard 19 vs 4 (optimal: stand) | 1 | 1.870 | 1.8695 |

## Charts

- `accuracy_by_hand_type.png`: Decision accuracy for hard, soft and pair decisions; whiskers are Wilson 95% CIs, n = decisions.
- `confusion_matrix.png`: Basic-strategy action (rows) vs the action the model chose (columns); outlined diagonal = correct decisions.
- `accuracy_heatmap.png`: Scenario set: the model's action in each basic-strategy cell (one graded decision per cell); blue = correct, orange = incorrect with the basic-strategy action in brackets. Sized for full text width (figure*).
- `action_frequency.png`: Share of decisions on which the model chose each action vs the basic-strategy action at the same decisions; bar labels are counts.
- `ev_loss_heatmap.png`: Scenario set: EV loss of the model's action in each cell (units per 1-unit bet; one graded decision per cell); grey cells are not in the scenario set. Sized for full text width (figure*).
