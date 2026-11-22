# Notes for the Paper

What was really built, in plain English. For the Methodology and Results writers.
Newest entries at the bottom.

## Blackjack simulator (2026-11-22)

**Rule set** (fixed for every run, `blackjack/rules.py`):
- 6 decks
- Dealer stands on soft 17 (S17)
- Player may double on any first two cards, including after a split (DAS)
- One split only (no resplitting). Any two cards of equal value can be split (e.g., K+Q)
- Split aces get exactly one card each and no further choices
- No surrender; no insurance offered
- Dealer peeks for blackjack when showing an ace or 10-value card; if the dealer has blackjack the hand ends at once (player loses 1 unit, or pushes with their own blackjack)
- Blackjack pays 3:2; a two-card 21 after a split counts as 21, not blackjack
- Flat bet of 1 unit per hand
- Any player hand that reaches 21 stands automatically (no decision is asked for)

**Dealing / reproducibility:** every hand is dealt from its own freshly shuffled 6-deck shoe, seeded from the run seed plus the hand number (seed string `"<run seed>-<hand number>"`). This guarantees hand N starts with the same player cards and dealer upcard under every harness configuration, so differences between configurations aren't caused by different cards. (Consequence: no card counting is possible, which matches basic strategy's assumption.)

**Basic strategy source:** Wizard of Odds 4-to-8-deck chart, dealer stands on soft 17, double after split allowed, no surrender (https://wizardofodds.com/games/blackjack/strategy/4-decks/), encoded 2026-11-22. Covers hard totals, soft totals, and pairs against dealer upcards 2 through ace. Basic strategy originates with Baldwin et al. (1956).

**Sanity check:** a bot that always plays our basic strategy table returned **-0.427% per hand** over 1,000,000 hands (95% CI -0.652% to -0.203%; run seed 2026), and **-0.425%** over a separate 3,000,000-hand run (95% CI -0.555% to -0.296%; run seed 99). Both are consistent with the published house edge of roughly 0.4-0.5% for these rules.

**How decisions are graded:** a decision is correct if it matches the *best legal* basic strategy action. Where the chart says "double" but doubling is not allowed (e.g., the hand already has three cards), the chart's fallback is the correct answer: "double, otherwise hit" counts hit as correct, and "double, otherwise stand" counts stand as correct. A pair that can no longer be split (already split once) is graded by its hard or soft total.

**Invalid actions:** if the player gives no action or an action that isn't legal right now, the simulator stands for it and records the decision as invalid.

**What counts as a decision:** each action the player chooses at a point where it has a real choice. Hands that end immediately on a player or dealer blackjack produce no decisions; split aces produce no decisions after the split itself.

## LLM player, baseline configuration (2026-11-22)

**Model:** `qwen2.5:7b` via Ollama 0.35.0 (local, $0), digest `845dbda0ea48ed749caafd9e6037047aa19acfcfd82e704d7ca97d631a0b697e` (7.6B parameters, Q4_K_M quantization). The digest identifies the exact model weights.

**Sampling settings:** temperature 0, Ollama seed 42, maximum reply length 400 tokens (`num_predict`), model kept loaded between requests (`keep_alive` 30 minutes). Each decision is a fresh, single-turn chat (one system message + one user message); the model sees no earlier hands or decisions.

**Harness configuration:** "baseline" = all four harness components (probability tool, strategy information, memory, self-evaluation) off.

**Exact baseline prompt (prompt version `baseline-v2`).** The system message is identical for every decision:

```
You are playing blackjack against a dealer. The goal is to finish closer to 21 than the dealer without going over 21.

Rules:
- The game uses 6 decks shuffled together.
- Number cards count their value, J, Q and K count 10, and an ace counts 1 or 11.
- The dealer must draw to 17 and stands on soft 17.
- You may double on any first two cards, including after a split.
- You may split any two cards of equal value (for example 8 and 8, or K and Q) once; there is no resplitting.
- Split aces receive exactly one card each.
- There is no surrender and no insurance.
- When the dealer's upcard is an ace or a 10-value card, the dealer checks for blackjack before you act; if the dealer has blackjack the hand ends immediately.
- Blackjack (an ace and a 10-value card as your first two cards) pays 3 to 2. A two-card 21 after a split counts as 21, not blackjack.
- Your bet is 1 unit per hand.

Actions:
- hit: take another card.
- stand: take no more cards.
- double: double your bet, take exactly one more card, then stand.
- split: split a pair into two separate hands, each with its own bet.

First explain your reasoning in two or three sentences. Then end your reply with a final line of exactly the form `ACTION: <one of the legal actions>`.
```

The user message contains only the current state. Two examples, a first decision and a hand that came from a split:

```
Your cards: 10, 6
Your total: hard 16
Pair: no
Dealer upcard: 10
Legal actions: hit, stand, double
```

```
Your cards: 8, 3
Your total: hard 11
Pair: no
This hand came from a split (hand 2 of 2).
Dealer upcard: 6
Legal actions: hit, stand, double
```

"Pair: yes" means the two cards have equal value; whether splitting is actually allowed is shown by the legal actions (after the one allowed split, a pair can no longer be split). No strategy advice, probabilities, or history is included.

**Prompt revision (v1 to v2).** The first version of the prompt ended with "Think briefly about the best play, then end your reply with a final line of exactly the form `ACTION: <one of the legal actions>`." With that wording the model almost never reasoned: in a 20-hand test (run seed 2026), 26 of 28 replies were only the bare line `ACTION: <word>`, with 64.3% accuracy over 28 decisions. Since the design calls for free reasoning followed by the action, the last line was changed to the v2 wording shown above ("First explain your reasoning in two or three sentences. Then ..."). The rest of the prompt did not change. Every logged decision records its prompt version, and runs made with different versions are never combined.

**How replies are read (parser rules, parser version `parser-v2`):**
- The model may reason freely; the action is taken from the text `ACTION:` (or `ACTION -`, or with the full-width colon `ACTION：`) followed by a word, anywhere in the reply.
- Each marker's text runs to the end of its line or to the next `ACTION` marker, whichever comes first, so two markers on one line are read separately.
- Markdown characters (`*`, `_`, backticks), letter case, brackets and trailing punctuation are ignored, so `**ACTION: stand**.` reads as stand.
- Accepted words: hit, stand, double, split, plus a fixed synonym list: "hit me" = hit, "take a card" = hit, "stay" = stand, "stand pat" = stand, "double down" = double, "doubledown" = double.
- A reply is an **invalid action** if: it has no `ACTION` marker (bare words elsewhere are never guessed from); it was cut off at the 400-token limit before giving a usable marker (a cut-off reply whose marker is partial or unrecognized counts as truncated); the marker is followed by nothing or by an unrecognized word; one marker names more than one different action (e.g. `ACTION: double (or hit if not allowed)`); several markers name *different* actions (several naming the same action is fine); or the named action is not legal right now (e.g. double on three cards).
- Parser v1 (used only in the two 20-hand smoke tests) differed in four edge cases: it ignored a second marker on the same line, took the first action from a marker naming several, did not accept the full-width colon, and labeled a cut-off reply with an unrecognized marker as an unknown word. Re-reading all 50 smoke-test replies with parser v2 changed none of the results. Every logged decision records its parser version.
- Invalid actions count as incorrect decisions. The player stands, so the hand can finish. The model is not asked again (no retries in the baseline).
- Server or connection failures are not invalid actions: the request is retried up to 3 times, and if Ollama is still unreachable the run stops without logging that hand.

**Grading:** a decision is correct when the reply was valid and the action matches the best legal basic-strategy action.

**What gets logged:** for every decision: run id, model and digest, harness configuration, prompt version, parser version, run seed and Ollama seed, hand number, which split hand it was, player cards, total, soft/hard, pair (the logged `is_pair` field means *splitting is legal at this decision*, which is narrower than the prompt's "Pair: yes": after the one allowed split, a pair of equal-value cards shows "Pair: yes" in the prompt but is logged with `is_pair` false), dealer upcard, legal actions, number of cards, the exact prompt (both messages), the model's full raw reply, the parsed action, the action actually taken, the basic-strategy action and chart code, correct/invalid flags with the invalid reason, why the reply ended (normal stop vs length cutoff), tokens generated, response time, and the hand's final payout plus this sub-hand's own result. For every hand (including blackjacks with no decisions): cards, dealer cards and total, blackjacks, each player hand's result, and the payout in units. Each run also saves its settings (model, digest, Ollama version, sampling options, rule set, system prompt, prompt version, parser version, seed, Python version, code version).

**Smoke test, prompt v2 (20 hands, run seed 2026):** 22 decisions, 11 correct (50.0%), 0 invalid, net 0 units over 20 hands; every reply gave 2-3 sentences of reasoning before the action (35-73 tokens, about 3.3 s per decision). The decision count differs from the v1 test (22 vs 28) because different choices lead to different later decisions in the same hands. Far too small for conclusions; it only checks the pipeline.

## Limitations (running list)

- **One split vs resplitting in the reference charts.** The reference charts used to build and check the strategy table (the BlackjackInfo strategy engine and Wizard of Odds) assume resplitting is allowed, but our game allows only one split. In theory a few borderline split cells (2,2, 3,3 and 6,6 against a dealer 2) could change under a one-split rule, but standard references treat them as unchanged. The table was checked against the reference chart with 0 of 190 cells mismatching.

## Analysis (2026-11-22)

Every number below is computed by `scripts/analyze.py` (code in `analysis/`) directly from a run's `decisions.jsonl`, `hands.jsonl` and `metadata.json`. Output goes to `results/<run dir>/results.md` plus four charts.

**Metric definitions:**
- **Decision accuracy** (primary metric) = correct decisions / all decisions. Invalid actions count as incorrect and stay in the denominator.
- **Invalid-action rate** = invalid actions / all decisions, with a count for each logged reason (e.g. no `ACTION` marker, illegal action).
- **Average return per hand** = mean payout in units over *every* hand, including hands that ended on a blackjack with no decisions. Reported next to the return of a simulated basic-strategy player (-0.427% per hand, from the house-edge sanity check above), which is a reference value, not a result of the LLM run. At a few hundred hands the return's confidence interval is far wider than the house edge, so returns are reported for completeness and decision accuracy is the number to interpret.
- **Accuracy by hand type:** "pair" = splitting was legal at that decision. A pair that could no longer be split (after the one allowed split) is counted under its hard or soft total. Otherwise "soft" if an ace counts as 11, else "hard".
- **Accuracy by dealer upcard:** 2 through 10 and A; J, Q and K are counted as 10.
- **Confusion matrix:** rows = the basic-strategy action at each decision, columns = the action the model chose, with invalid actions as their own column (the fallback stand is not counted as a stand choice).
- **Action frequency:** how often the model chose each action vs how often basic strategy called for it *at the same decisions the model faced*.
- **Most common mistakes:** incorrect decisions grouped by chosen action, player total (hard/soft/pair) and upcard, e.g. "doubled hard 12 vs 4 (optimal: stand)".
- Also reported: decisions per hand, mean response time per decision, mean tokens generated per decision.

**Confidence intervals (95%):**
- Proportions (accuracy, invalid rate, every breakdown cell) use the **Wilson score interval**, which stays inside 0-100% and behaves sensibly at small n.
- Mean return per hand uses the **normal approximation**: mean ± 1.96 × (sample standard deviation) / sqrt(number of hands).

**Small-sample flag:** any breakdown row (hand type or dealer upcard) with **fewer than 30 decisions** is marked "small sample" in the tables.

**Run comparison:** given several runs, the script also writes a comparison table (run id, prompt version, harness configuration, model, hands, decisions, accuracy ± CI, invalid rate, mean return per hand ± CI) and a chart of accuracy per run. Runs with different prompt versions are kept separate, never pooled.

## Scenario set (2026-11-22)

Natural dealing over-represents common hands (hard 12–17) and rarely produces others (e.g., soft 13 vs 2, pair 4,4), so accuracy measured on it is dominated by a few chart cells. To measure accuracy evenly we also ran a **scenario set**: every basic strategy cell exactly once. The cells are hard 5–19, soft 13–20 (A,2–A,9) and the ten pairs (2,2–10,10 and A,A), each against dealer upcards 2–10 and A, giving 33 × 10 = 330 scenarios. Hard 4 and hard 20 appear only as the pairs 2,2 and 10,10. Each hard total uses one fixed two-card hand: a 10 plus the remainder when possible (hard 12–19 = 10,2 … 10,9), otherwise 2 plus the remainder (hard 5–11 = 2,3 … 2,9). None of these is a pair or contains an ace. Pairs use 10,10 rather than mixed face cards. Each scenario is dealt from a full 6-deck shoe with the three forced cards removed and the rest shuffled from a seed built from the run seed and the scenario name, so card counts stay realistic and every scenario can be reproduced exactly. The dealer's hole card is chosen so the dealer never has blackjack; otherwise, with an ace or 10 showing, the dealer's peek would end the hand before the player decides. The model, prompt (`baseline-v2`), parser (`parser-v2`) and sampling settings are the same as in the baseline run. Only the first decision of each scenario hand is graded as that cell. Later decisions in the same hand are logged but excluded from scenario accuracy. The scenario set measures decision accuracy only. Its returns are not reported, because the hands are not a natural sample. Limitation: each hard total is tested with only one card combination (e.g., hard 16 is always 10,6, never 9,7), so the model's sensitivity to how a total is made up is not measured.

## EV loss (secondary metric, 2026-11-22)

As a secondary metric we report EV loss: for each decision, the expected value (in units per 1-unit initial bet) of the basic-strategy action minus that of the action actually played, so correct decisions cost 0. EVs are computed exactly by recursion for our rule set (6 decks, S17, DAS, one split, split aces one card, dealer peek), conditioning on no dealer blackjack and removing the player's cards and the dealer's upcard from a 6-deck shoe. Later draws use those fixed proportions. Splits are valued as two independent split hands. The calculator reproduces Wizard of Odds' 6-deck S17 dealer outcome probabilities to within 0.0007 (https://wizardofodds.com/games/blackjack/appendix/2a/) and its infinite-deck player EVs to within 0.0005 (https://wizardofodds.com/games/blackjack/player-expected-return/). Its best action agrees with our strategy table on all 540 two-card hand/upcard combinations, and it gives an exact basic-strategy house edge of 0.457%, consistent with our 3M-hand simulation (0.425%, 95% CI 0.296–0.555%). Invalid actions are charged for the stand the engine played as a fallback; their loss is also reported separately. In the baseline run (1,000 hands, 1,147 decisions), the model gave up 376 units of expected value: 0.33 units per decision, 0.38 per hand and 0.56 per mistake. That is roughly 90 times the 0.0043 units/hand basic-strategy house edge. 85% of this loss came from doubling, and doubling a pair of tens alone (54 decisions) cost 128 units, a third of the total.

## Scenario run results (2026-11-22)

Scenario run (330 forced cells, each graded once on its first decision): 40.9% accuracy (95% CI 35.7–46.3%), statistically indistinguishable from the natural baseline's 41.7% (38.9–44.6%). The two are reported side by side and never pooled: the natural run weights cells by how often they are dealt, while the scenario set weights every cell equally. Follow-up decisions within scenario hands (n=187, 30.5%) are reported separately. The basic-strategy reference return is now the exact enumeration, −0.457% per hand; a 3M-hand simulation gave −0.425% (95% CI −0.555% to −0.296%).
