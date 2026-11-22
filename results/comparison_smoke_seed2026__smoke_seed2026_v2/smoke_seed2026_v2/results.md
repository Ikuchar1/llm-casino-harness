# Results: smoke_seed2026_v2

- **Run id:** `baseline_qwen2.5-7b_seed2026_20261122-093942`
- **Model:** `qwen2.5:7b` (digest `845dbda0ea48ed749caafd9e6037047aa19acfcfd82e704d7ca97d631a0b697e`), Ollama 0.35.0
- **Prompt version:** baseline-v2
- **Harness config:** baseline (components on: none)
- **Rule set:** 6 decks, dealer stands on soft 17, double after split allowed, max 1 split, split aces get one card, no surrender, no insurance, dealer peeks, blackjack pays 3:2, flat 1-unit bet
- **Sampling:** temperature 0, Ollama seed 42, num_predict 400
- **Run seed:** 2026
- **Hands:** 20  |  **Decisions:** 22
- **Date:** 2026-11-22 (started 2026-11-22T09:39:42-06:00)

## Headline numbers

| Metric | Value |
|---|---|
| Decision accuracy (primary metric) | 50.0% (11/22; 95% CI 30.7%-69.3%) |
| Invalid-action rate | 0.0% (0/22; 95% CI 0.0%-14.9%) |
| Mean return per hand | +0.000 units/hand (95% CI -0.735 to +0.735; n = 20 hands) |
| Net result | +0.000 units over 20 hands |
| Reference: basic-strategy return | -0.427% per hand (simulated basic-strategy player, 1,000,000 hands, run seed 2026 (house-edge sanity check); not from this run) |
| Decisions per hand | 1.10 |
| Mean latency per decision | 3.34 s |
| Mean tokens generated per decision (eval_count) | 55.7 |

> **Note on returns:** at this sample size, return per hand is dominated by card variance: the 95% CI half-width is ±0.735 units/hand, against a basic-strategy return of -0.00427 units/hand. Decision accuracy is the meaningful number; returns are reported for completeness.

## Invalid actions

No invalid actions (0 of 22 decisions).

## Accuracy by hand type

| Hand type | n | Correct | Accuracy | 95% CI | Flag |
|---|---|---|---|---|---|
| hard | 18 | 8 | 44.4% | 24.6%-66.3% | small sample |
| soft | 2 | 2 | 100.0% | 34.2%-100.0% | small sample |
| pair | 2 | 1 | 50.0% | 9.5%-90.5% | small sample |

"small sample" = fewer than 30 decisions.

Pair = splitting was legal at that decision; pairs that could not be split are counted by their hard/soft total.

## Accuracy by dealer upcard

| Upcard | n | Correct | Accuracy | 95% CI | Flag |
|---|---|---|---|---|---|
| 2 | 2 | 1 | 50.0% | 9.5%-90.5% | small sample |
| 3 | 2 | 1 | 50.0% | 9.5%-90.5% | small sample |
| 4 | 5 | 3 | 60.0% | 23.1%-88.2% | small sample |
| 5 | 4 | 2 | 50.0% | 15.0%-85.0% | small sample |
| 6 | 1 | 1 | 100.0% | 20.7%-100.0% | small sample |
| 7 | 4 | 2 | 50.0% | 15.0%-85.0% | small sample |
| 8 | 1 | 1 | 100.0% | 20.7%-100.0% | small sample |
| 9 | 0 | 0 | n/a | n/a | small sample |
| 10 | 3 | 0 | 0.0% | 0.0%-56.2% | small sample |
| A | 0 | 0 | n/a | n/a | small sample |

"small sample" = fewer than 30 decisions.

J, Q and K are counted as 10.

## Confusion matrix (rows: basic-strategy action, columns: model's chosen action)

| Basic strategy \ Model | hit | stand | double | split | invalid | Total |
|---|---|---|---|---|---|---|
| **hit** | 2 | 4 | 2 | 0 | 0 | 8 |
| **stand** | 1 | 5 | 4 | 0 | 0 | 10 |
| **double** | 0 | 0 | 3 | 0 | 0 | 3 |
| **split** | 0 | 0 | 0 | 1 | 0 | 1 |

"invalid" = invalid action (the engine stood as a fallback; that stand is not counted as a stand choice).

## Action frequency (model vs basic strategy, same decisions)

| Action | Model count | Model % | Basic strategy count | Basic strategy % |
|---|---|---|---|---|
| hit | 3 | 13.6% | 8 | 36.4% |
| stand | 9 | 40.9% | 10 | 45.5% |
| double | 9 | 40.9% | 3 | 13.6% |
| split | 1 | 4.5% | 1 | 4.5% |
| invalid | 0 | 0.0% | 0 | 0.0% |

- The model chose hit on 13.6% of decisions; basic strategy calls for hit on 36.4%.
- The model chose stand on 40.9% of decisions; basic strategy calls for stand on 45.5%.
- The model chose double on 40.9% of decisions; basic strategy calls for double on 13.6%.
- The model chose split on 4.5% of decisions; basic strategy calls for split on 4.5%.

## Most common mistakes (top 10 by count)

1. doubled hard 12 vs 4 (optimal: stand) ×1
2. doubled hard 12 vs 7 (optimal: hit) ×1
3. doubled hard 14 vs 5 (optimal: stand) ×1
4. doubled hard 17 vs 10 (optimal: stand) ×1
5. doubled hard 6 vs 2 (optimal: hit) ×1
6. doubled pair 10,10 vs 5 (optimal: stand) ×1
7. hit hard 14 vs 3 (optimal: stand) ×1
8. stood on hard 15 vs 10 (optimal: hit) ×1
9. stood on hard 5 vs 4 (optimal: hit) ×1
10. stood on hard 7 vs 7 (optimal: hit) ×1

## Charts

- `accuracy_by_hand_type.png`: Decision accuracy for hard, soft and pair decisions; whiskers are Wilson 95% CIs, n = decisions.
- `confusion_matrix.png`: Basic-strategy action (rows) vs the action the model chose (columns); outlined diagonal = correct decisions.
- `accuracy_heatmap.png`: Decision accuracy by player hand and dealer upcard; each cell shows accuracy (n); grey cells had no decisions. Sized for full text width (figure*).
- `action_frequency.png`: Share of decisions on which the model chose each action vs the basic-strategy action at the same decisions; bar labels are counts.
