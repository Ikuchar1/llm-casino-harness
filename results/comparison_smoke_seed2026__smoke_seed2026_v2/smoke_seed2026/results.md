# Results: smoke_seed2026

- **Run id:** `baseline_qwen2.5-7b_seed2026_20261122-093657`
- **Model:** `qwen2.5:7b` (digest `845dbda0ea48ed749caafd9e6037047aa19acfcfd82e704d7ca97d631a0b697e`), Ollama 0.35.0
- **Prompt version:** not logged
- **Harness config:** baseline (components on: none)
- **Rule set:** 6 decks, dealer stands on soft 17, double after split allowed, max 1 split, split aces get one card, no surrender, no insurance, dealer peeks, blackjack pays 3:2, flat 1-unit bet
- **Sampling:** temperature 0, Ollama seed 42, num_predict 400
- **Run seed:** 2026
- **Hands:** 20  |  **Decisions:** 28
- **Date:** 2026-11-22 (started 2026-11-22T09:36:57-06:00)

## Headline numbers

| Metric | Value |
|---|---|
| Decision accuracy (primary metric) | 64.3% (18/28; 95% CI 45.8%-79.3%) |
| Invalid-action rate | 0.0% (0/28; 95% CI 0.0%-12.1%) |
| Mean return per hand | -0.200 units/hand (95% CI -0.887 to +0.487; n = 20 hands) |
| Net result | -4.000 units over 20 hands |
| Reference: basic-strategy return | -0.427% per hand (simulated basic-strategy player, 1,000,000 hands, run seed 2026 (house-edge sanity check); not from this run) |
| Decisions per hand | 1.40 |
| Mean latency per decision | 0.94 s |
| Mean tokens generated per decision (eval_count) | 7.6 |

> **Note on returns:** at this sample size, return per hand is dominated by card variance: the 95% CI half-width is ±0.687 units/hand, against a basic-strategy return of -0.00427 units/hand. Decision accuracy is the meaningful number; returns are reported for completeness.

## Invalid actions

No invalid actions (0 of 28 decisions).

## Accuracy by hand type

| Hand type | n | Correct | Accuracy | 95% CI | Flag |
|---|---|---|---|---|---|
| hard | 24 | 16 | 66.7% | 46.7%-82.0% | small sample |
| soft | 2 | 1 | 50.0% | 9.5%-90.5% | small sample |
| pair | 2 | 1 | 50.0% | 9.5%-90.5% | small sample |

"small sample" = fewer than 30 decisions.

Pair = splitting was legal at that decision; pairs that could not be split are counted by their hard/soft total.

## Accuracy by dealer upcard

| Upcard | n | Correct | Accuracy | 95% CI | Flag |
|---|---|---|---|---|---|
| 2 | 4 | 4 | 100.0% | 51.0%-100.0% | small sample |
| 3 | 2 | 1 | 50.0% | 9.5%-90.5% | small sample |
| 4 | 6 | 3 | 50.0% | 18.8%-81.2% | small sample |
| 5 | 4 | 1 | 25.0% | 4.6%-69.9% | small sample |
| 6 | 1 | 1 | 100.0% | 20.7%-100.0% | small sample |
| 7 | 5 | 3 | 60.0% | 23.1%-88.2% | small sample |
| 8 | 1 | 0 | 0.0% | 0.0%-79.3% | small sample |
| 9 | 0 | 0 | n/a | n/a | small sample |
| 10 | 5 | 5 | 100.0% | 56.6%-100.0% | small sample |
| A | 0 | 0 | n/a | n/a | small sample |

"small sample" = fewer than 30 decisions.

J, Q and K are counted as 10.

## Confusion matrix (rows: basic-strategy action, columns: model's chosen action)

| Basic strategy \ Model | hit | stand | double | split | invalid | Total |
|---|---|---|---|---|---|---|
| **hit** | 8 | 2 | 1 | 0 | 0 | 11 |
| **stand** | 2 | 7 | 4 | 0 | 0 | 13 |
| **double** | 0 | 1 | 2 | 0 | 0 | 3 |
| **split** | 0 | 0 | 0 | 1 | 0 | 1 |

"invalid" = invalid action (the engine stood as a fallback; that stand is not counted as a stand choice).

## Action frequency (model vs basic strategy, same decisions)

| Action | Model count | Model % | Basic strategy count | Basic strategy % |
|---|---|---|---|---|
| hit | 10 | 35.7% | 11 | 39.3% |
| stand | 10 | 35.7% | 13 | 46.4% |
| double | 7 | 25.0% | 3 | 10.7% |
| split | 1 | 3.6% | 1 | 3.6% |
| invalid | 0 | 0.0% | 0 | 0.0% |

- The model chose hit on 35.7% of decisions; basic strategy calls for hit on 39.3%.
- The model chose stand on 35.7% of decisions; basic strategy calls for stand on 46.4%.
- The model chose double on 25.0% of decisions; basic strategy calls for double on 10.7%.
- The model chose split on 3.6% of decisions; basic strategy calls for split on 3.6%.

## Most common mistakes (top 10 by count)

1. doubled hard 12 vs 4 (optimal: stand) ×1
2. doubled hard 12 vs 7 (optimal: hit) ×1
3. doubled hard 14 vs 5 (optimal: stand) ×1
4. doubled hard 15 vs 4 (optimal: stand) ×1
5. doubled pair 10,10 vs 5 (optimal: stand) ×1
6. hit hard 13 vs 4 (optimal: stand) ×1
7. hit hard 14 vs 3 (optimal: stand) ×1
8. stood on hard 16 vs 7 (optimal: hit) ×1
9. stood on hard 16 vs 8 (optimal: hit) ×1
10. stood on soft 17 vs 5 (optimal: double) ×1

## Charts

- `accuracy_by_hand_type.png`: Decision accuracy for hard, soft and pair decisions; whiskers are Wilson 95% CIs, n = decisions.
- `confusion_matrix.png`: Basic-strategy action (rows) vs the action the model chose (columns); outlined diagonal = correct decisions.
- `accuracy_heatmap.png`: Decision accuracy by player hand and dealer upcard; each cell shows accuracy (n); grey cells had no decisions. Sized for full text width (figure*).
- `action_frequency.png`: Share of decisions on which the model chose each action vs the basic-strategy action at the same decisions; bar labels are counts.
