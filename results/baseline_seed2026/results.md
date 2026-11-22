# Results: baseline_seed2026

- **Run id:** `baseline_qwen2.5-7b_seed2026_20261122-094750`
- **Model:** `qwen2.5:7b` (digest `845dbda0ea48ed749caafd9e6037047aa19acfcfd82e704d7ca97d631a0b697e`), Ollama 0.35.0
- **Prompt version:** baseline-v2
- **Harness config:** baseline (components on: none)
- **Rule set:** 6 decks, dealer stands on soft 17, double after split allowed, max 1 split, split aces get one card, no surrender, no insurance, dealer peeks, blackjack pays 3:2, flat 1-unit bet
- **Sampling:** temperature 0, Ollama seed 42, num_predict 400
- **Run seed:** 2026
- **Hands:** 1000  |  **Decisions:** 1147
- **Date:** 2026-11-22 (started 2026-11-22T09:47:50-06:00)

## Headline numbers

| Metric | Value |
|---|---|
| Decision accuracy (primary metric) | 41.7% (478/1147; 95% CI 38.9%-44.6%) |
| Invalid-action rate | 0.8% (9/1147; 95% CI 0.4%-1.5%) |
| Mean return per hand | -0.330 units/hand (95% CI -0.424 to -0.236; n = 1000 hands) |
| Net result | -330.000 units over 1000 hands |
| Reference: basic-strategy return | -0.457% per hand (exact, computed; not from this run). A 3,000,000-hand simulation of the same strategy (scripts/sanity_house_edge.py) gave -0.425% (95% CI -0.555% to -0.296%). |
| Decisions per hand | 1.15 |
| Mean latency per decision | 3.67 s |
| Mean tokens generated per decision (eval_count) | 57.4 |

> **Note on returns:** at this sample size, return per hand is dominated by card variance: the 95% CI half-width is ±0.094 units/hand, against a basic-strategy return of -0.00457 units/hand. Decision accuracy is the meaningful number; returns are reported for completeness.

## Invalid actions by reason

| invalid_reason | Count |
|---|---|
| no_action | 6 |
| illegal | 3 |

## Accuracy by hand type

| Hand type | n | Correct | Accuracy | 95% CI | Flag |
|---|---|---|---|---|---|
| hard | 887 | 371 | 41.8% | 38.6%-45.1% |  |
| soft | 109 | 46 | 42.2% | 33.4%-51.6% |  |
| pair | 151 | 61 | 40.4% | 32.9%-48.4% |  |

"small sample" = fewer than 30 decisions.

Pair = splitting was legal at that decision; pairs that could not be split are counted by their hard/soft total.

## Accuracy by dealer upcard

| Upcard | n | Correct | Accuracy | 95% CI | Flag |
|---|---|---|---|---|---|
| 2 | 83 | 44 | 53.0% | 42.4%-63.4% |  |
| 3 | 108 | 49 | 45.4% | 36.3%-54.8% |  |
| 4 | 93 | 40 | 43.0% | 33.4%-53.2% |  |
| 5 | 109 | 48 | 44.0% | 35.1%-53.4% |  |
| 6 | 92 | 43 | 46.7% | 36.9%-56.9% |  |
| 7 | 95 | 44 | 46.3% | 36.6%-56.3% |  |
| 8 | 93 | 37 | 39.8% | 30.4%-49.9% |  |
| 9 | 75 | 37 | 49.3% | 38.3%-60.4% |  |
| 10 | 329 | 109 | 33.1% | 28.3%-38.4% |  |
| A | 70 | 27 | 38.6% | 28.0%-50.3% |  |

"small sample" = fewer than 30 decisions.

J, Q and K are counted as 10.

## Confusion matrix (rows: basic-strategy action, columns: model's chosen action)

| Basic strategy \ Model | hit | stand | double | split | invalid | Total |
|---|---|---|---|---|---|---|
| **hit** | 109 | 103 | 234 | 19 | 4 | 469 |
| **stand** | 57 | 280 | 184 | 6 | 3 | 530 |
| **double** | 31 | 23 | 54 | 3 | 0 | 111 |
| **split** | 0 | 0 | 0 | 35 | 2 | 37 |

"invalid" = invalid action (the engine stood as a fallback; that stand is not counted as a stand choice).

## Action frequency (model vs basic strategy, same decisions)

| Action | Model count | Model % | Basic strategy count | Basic strategy % |
|---|---|---|---|---|
| hit | 197 | 17.2% | 469 | 40.9% |
| stand | 406 | 35.4% | 530 | 46.2% |
| double | 472 | 41.2% | 111 | 9.7% |
| split | 63 | 5.5% | 37 | 3.2% |
| invalid | 9 | 0.8% | 0 | 0.0% |

- The model chose hit on 17.2% of decisions; basic strategy calls for hit on 40.9%.
- The model chose stand on 35.4% of decisions; basic strategy calls for stand on 46.2%.
- The model chose double on 41.2% of decisions; basic strategy calls for double on 9.7%.
- The model chose split on 5.5% of decisions; basic strategy calls for split on 3.2%.

## Most common mistakes (top 10 by count)

1. doubled hard 13 vs 10 (optimal: hit) ×22
2. doubled hard 12 vs 10 (optimal: hit) ×18
3. doubled hard 14 vs 10 (optimal: hit) ×17
4. doubled hard 10 vs 10 (optimal: hit) ×15
5. doubled hard 15 vs 10 (optimal: hit) ×15
6. doubled pair 10,10 vs 10 (optimal: stand) ×13
7. doubled hard 16 vs 10 (optimal: hit) ×12
8. doubled hard 17 vs 10 (optimal: stand) ×10
9. stood on hard 9 vs 10 (optimal: hit) ×10
10. doubled hard 15 vs 7 (optimal: hit) ×9

## EV loss (secondary metric)

EV loss = EV(basic-strategy action) - EV(action played), in units per 1-unit initial bet; a correct decision has EV loss 0. EVs are exact for 6 decks with the player's cards and the dealer's upcard removed, given the dealer has no blackjack (blackjack/ev.py). Invalid actions are charged for the stand the engine played as a fallback. A few composition-dependent decisions (e.g. a three-card 16 vs 10) have a slightly negative loss when the model deviated from the chart; losses are not clipped. 

| Metric | Value |
|---|---|
| Total EV loss | 376.250 units over 1147 decisions |
| Mean EV loss per decision | 0.3280 units |
| Mean EV loss per hand | 0.3762 units (n = 1000 hands) |
| Mean EV loss per mistake | 0.5624 units (n = 669 incorrect decisions) |
| Of which invalid actions | 1.976 units over 9 decisions (mean 0.2196) |
| Decisions where the model beat the chart | 1 (total -0.0033 units) |

### EV loss by hand type

| Hand type | n | Total EV loss | Mean EV loss |
|---|---|---|---|
| hard | 887 | 215.924 | 0.2434 |
| soft | 109 | 14.760 | 0.1354 |
| pair | 151 | 145.565 | 0.9640 |

### Costliest mistakes (top 10 by total EV loss)

| # | Mistake | n | Total EV loss | Mean EV loss |
|---|---|---|---|---|
| 1 | doubled pair 10,10 vs 10 (optimal: stand) | 13 | 29.307 | 2.2544 |
| 2 | doubled pair 10,10 vs 5 (optimal: stand) | 8 | 19.018 | 2.3772 |
| 3 | doubled pair 10,10 vs 8 (optimal: stand) | 7 | 17.435 | 2.4908 |
| 4 | doubled pair 10,10 vs 2 (optimal: stand) | 7 | 16.422 | 2.3460 |
| 5 | doubled pair 10,10 vs 7 (optimal: stand) | 5 | 12.364 | 2.4728 |
| 6 | doubled pair 10,10 vs 4 (optimal: stand) | 5 | 11.828 | 2.3656 |
| 7 | doubled pair 10,10 vs 3 (optimal: stand) | 5 | 11.777 | 2.3555 |
| 8 | doubled pair 10,10 vs 9 (optimal: stand) | 4 | 9.819 | 2.4548 |
| 9 | doubled hard 13 vs 10 (optimal: hit) | 22 | 9.674 | 0.4397 |
| 10 | doubled hard 18 vs 5 (optimal: stand) | 6 | 8.535 | 1.4225 |

## Charts

- `accuracy_by_hand_type.png`: Decision accuracy for hard, soft and pair decisions; whiskers are Wilson 95% CIs, n = decisions.
- `confusion_matrix.png`: Basic-strategy action (rows) vs the action the model chose (columns); outlined diagonal = correct decisions.
- `accuracy_heatmap.png`: Decision accuracy by player hand and dealer upcard; each cell shows accuracy (n); grey cells had no decisions. Sized for full text width (figure*).
- `action_frequency.png`: Share of decisions on which the model chose each action vs the basic-strategy action at the same decisions; bar labels are counts.
- `ev_loss_heatmap.png`: Mean EV loss per decision (units per 1-unit bet) by player hand and dealer upcard; each cell shows mean loss (n); grey cells had no decisions. Sized for full text width (figure*).
