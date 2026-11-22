# Progress Log

Running log of important events and completed work. Newest entries at the bottom of each day.
For *what the paper should say*, see `NOTES_FOR_PAPER.md`. For term definitions, see `CONTEXT.md`.

## 2026-11-22 (Milestone 2 due 11:59pm)

### Done
- Read `PROJECT_CONTEXT.md`; Ollama 0.35.0 confirmed running.
- Pulled `qwen2.5:7b` (4.7 GB).
- Grill session with Ian — all pre-development decisions locked (below).
- Created `CONTEXT.md` (glossary) and `docs/adr/0001-fresh-seeded-shoe-per-hand.md`.

### Decisions locked (grill session)
| # | Topic | Decision |
|---|---|---|
| 1 | Rule set | 6 decks, S17, double any 2 + DAS, one split only, split aces get one card, no surrender, dealer peeks, 3:2 |
| 2 | Decision | Every model action = one decision (hit, hit, stand = 3) |
| 3 | Grading | Against the best *legal* basic-strategy action (Dh/Ds fallbacks) |
| 4 | Invalid action | Counts as incorrect; fallback = stand; no retry in baseline |
| 5 | Reply format | Free reasoning, then `ACTION: <word>`; lenient parser (case/markdown/punctuation, fixed synonyms); missing/conflicting/illegal = invalid |
| 6 | Sampling | temperature 0, fixed logged Ollama seed, num_predict ≈ 400 |
| 7 | Seeding | Fresh shoe per hand, seeded by run seed + hand # (ADR 0001) |
| 8 | Sample | Natural dealing today (A); scenario set covering every chart cell (B) only if time |
| 9 | Side rules | No insurance offered; flat 1-unit bets |

Ideas parked for later: card counting as Future Work (needs a count-adjusted grader; ties to open question #2); Ollama JSON-schema mode as a possible later harness component.

### Timing test results (step 1)
- Machine: Apple M2, 16 GB, qwen2.5:7b runs 100% on GPU at ~18 tok/s.
- **~5.1 s per decision** (max 6.1 s) → ~700 decisions/hr ≈ ~470 hands/hr. Replies were 60–110 tokens; none hit the 400 cap.
- Model load adds ~5–6 s on first call; it unloads after ~4 min idle → set `keep_alive` on runs.
- Format: 5/6 replies had a clean `ACTION: x` last line; 1 was inline `**ACTION: stand**.` → parser must strip `*`, search last `ACTION:` anywhere, drop punctuation.
- Early quality signal: 4/6 sample decisions were wrong by basic strategy (e.g., doubled 8,8 vs 6; doubled 12 vs 4).
- Implication: scenario set (~280 cells ≈ 25 min) is affordable — stretch goal B looks feasible.

### Simulator + strategy table (step 2)
- Built `blackjack/` package: `cards.py` (shoe, per-hand seeding), `rules.py` (frozen `RuleSet`), `engine.py` (`Player` protocol, `DecisionState`, `play_hand`, `HandRecord`), `strategy.py` (chart + `best_legal_action` + `BasicStrategyPlayer`).
- **151 tests pass** (`.venv/bin/pytest -q`). Python 3.14.3 in `.venv`.
- **House-edge sanity check: −0.427% per hand** (1M hands, 95% CI −0.65% to −0.20%); 3M hands gave −0.425%. Matches expected −0.4 to −0.5% → engine + table are plausibly correct.
- Small rules the agent settled: any hand reaching 21 auto-stands (no decision asked); dealer doesn't draw if all player hands bust; engine only accepts exact lowercase action names (LLM layer normalizes).
- Table was written from memory of the Wizard of Odds chart — **not yet checked against the live page** (step 3). Soft 12 (unsplittable A,A) set to hit everywhere; needs confirming.

### Strategy table review (step 3)
- **Verdict: 0 mismatches across all 190 cells.** Checked against the BlackjackInfo Basic Strategy Engine (6D, S17, DAS, double any 2, no surrender, peek) and the Wizard of Odds 4–8 deck page. `best_legal_action` fallbacks verified for every 2- and 3-card hand.
  - https://www.blackjackinfo.com/blackjack-basic-strategy-engine/?numdecks=6&soft17=s17&dbl=all&das=yes&surr=ns&peek=yes
  - https://wizardofodds.com/games/blackjack/strategy/4-decks/
- Caveat for the paper: both source charts assume resplitting is allowed; our game allows one split. Close split calls (2,2 / 3,3 / 6,6 vs 2) could in theory differ, but standard references treat them as unchanged. → Add to `NOTES_FOR_PAPER.md` (Limitations) once the step-4 agent is done editing it.

### LLM player + smoke test (step 4)
- Built `agent/` package: `config.py` (`HarnessConfig`, `BASELINE`), `parser.py`, `prompt.py`, `ollama_client.py`, `llm_player.py`, `run_log.py`, `runner.py`; CLI `scripts/run_baseline.py` (resumable). **227 tests pass.**
- Logs per run in `runs/<dir>/`: `decisions.jsonl`, `hands.jsonl`, `metadata.json`. Model digest `845dbda0ea48…`, Ollama 0.35.0.
- **Smoke v1** (`runs/smoke_seed2026/`): 20 hands, 28 decisions, **64.3% accuracy**, 0 invalid, −4 units, 0.9 s/decision.
- **Problem found:** with "Think briefly…" the model skipped reasoning on 26/28 replies (bare `ACTION: x`). That breaks locked decision #5 → prompt being revised to "explain your reasoning in two or three sentences, then ACTION:" (v2), with `prompt_version` logged. v1 run kept as a record (no-reasoning data point — possibly useful later as its own comparison).
- Model habit seen: doubles on hard 12–20 a lot.
- **Smoke v2** (`runs/smoke_seed2026_v2/`, prompt `baseline-v2`): 20 hands, 22 decisions, **50.0% accuracy**, 0 invalid, 0 units, **3.3 s/decision**, ~56 tokens/reply. 22/22 replies reasoned first. ~1/3 put `ACTION:` inline (parser handles it).
  - With reasoning the model over-doubles even more (doubled hard 17, 6, 20, 12, 14, 12) and its reasoning often contradicts its action — good Discussion material.
  - `prompt_version` now logged; resume refuses to mix prompt versions. **232 tests pass.**
- Step 4 done. Steps 5 (parser/grading review) and 7 (analysis script, built on smoke logs) running in parallel.

### Parser/grading review (step 5)
- Smoke logs clean: **50/50 parses, 50/50 grades, 40/40 payouts correct**; prompt leaks no strategy hints.
- **2 parser bugs found (would appear at scale):** a second `ACTION:` on the same line was ignored; `ACTION: hit or stand` took the first word. Both should be `conflicting` (invalid). Being fixed as `parser-v2` (+ accept fullwidth `：`; truncated partial marker → `truncated_no_action`) before the full run.
- Analysis trap noted: logged `is_pair` = "split is legal", not the prompt's card-based "Pair: yes".
- **Open question for Ian (not acted on):** the model sometimes reasons as if the dealer might have blackjack under a 10, even though the rules say the dealer peeks. Adding a state line "Dealer checked: no blackjack" for 10/A upcards would be a prompt change (new prompt version). Left as-is for the baseline.
- Parser-v2 done: **278 tests pass**; re-parsing all 50 smoke replies changed nothing. `PARSER_VERSION` logged + checked on resume.

### Full baseline run (step 6) — RUNNING
- Started ~09:48. 1000 hands, seed 2026, prompt `baseline-v2`, parser `parser-v2`, qwen2.5:7b.
- Dir `runs/baseline_seed2026/`, log `runs/baseline_seed2026.log`, PID 14245 (under `caffeinate`, PID 14247). Resumable if interrupted (re-run same command).
- ~3.7 s/decision, ~3.2 s/hand → ETA ~53 min.
- First impression (7 decisions only): model doubled on its first 4 decisions (hard 17 vs 10, 6 vs 2, 20 vs 5, 12 vs 4) — consistent with smoke runs.
- Step 8 (scenario set) being built in parallel; it will run only after step 6 finishes (one GPU).

- Check at hand 37: 52.5% accuracy (21/40), 0 invalid, 3.5 s/decision, ETA ~1h.

### Analysis script (step 7) — built, waiting on full run
- `analysis/` (stats, loading, metrics, charts, report) + `scripts/analyze.py`. **280 tests pass** (30 new).
- Outputs: `results/<run>/results.md` + 4 PNGs (accuracy by hand type, confusion matrix, heatmap, action frequency); multi-run → `results/comparison_<a>__<b>/` with `comparison.md/.csv` + accuracy chart.
- Smoke v2 numbers: 50.0% (CI 30.7–69.3%), model doubles 40.9% of decisions vs 13.6% optimal; hits 13.6% vs 36.4%.
- Analysis choices: J/Q/K folded to 10; invalid shown as its own column (logged action is the stand fallback); v1 shows prompt "not logged"; −0.427% reference return hard-coded in `analysis/report.py` and labelled "not from this run".
- **For Ian:** `results/` isn't gitignored. Commit it (teammates need the charts) or ignore it?

### Plan
1. [x] Timing test (qwen2.5:7b, reasoning-style reply)
2. [x] Simulator + basic strategy table (test-first)
3. [x] Independent review of strategy table vs a published chart
4. [x] LLM player + logging + runner; 20-hand smoke test
5. [x] Review smoke-test replies / parser
6. [ ] Full baseline run (background) — running
7. [~] Analysis script → `results.md` + chart(s) — built; rerun on full run

8. [ ] Scenario set (stretch)

### Scenario set (step 8) — built, waiting for GPU
- `agent/scenarios.py`, `agent/scenario_runner.py`, `scripts/run_scenarios.py`. **302 tests pass** (22 new). No existing files changed.
- 330 scenarios (15 hard + 8 soft + 10 pair rows × 10 upcards), version `scenarios-v1`. Hard 12–19 = 10,x; hard 5–11 = 2,x. Dealer never has blackjack.
- Extra log fields: `run_type="scenario"`, `scenario_id`, `is_scenario_cell` (first decision only). Analysis must filter on `is_scenario_cell` and ignore returns.
- Launch after baseline finishes: `caffeinate -i .venv/bin/python scripts/run_scenarios.py --seed 2026 --model qwen2.5:7b --out runs/scenarios_seed2026 > runs/scenarios_seed2026.log 2>&1 &` (~30 min).
- Paper paragraph merged into `NOTES_FOR_PAPER.md`.

### Full baseline run (step 6) — DONE
- 1000 hands, 1147 decisions, **41.7% accuracy**, 9 invalid, −330 units.

### EV loss (secondary metric) — DONE (Ian asked for it)
- `blackjack/ev.py` (exact EV, 6-deck composition at the decision point, memoized) + `analysis/ev_loss.py`; EV-loss section in results.md, new comparison.csv columns, `ev_loss_heatmap.png`. **373 tests pass.**
- Validated: dealer outcomes match Wizard of Odds within 0.0007; best-EV action matches the chart on all 540 two-card cells; exact house edge −0.457% (sim −0.425%, inside CI).
- **Baseline:** 376 units EV lost; 0.33/decision, 0.56/mistake. Doubling = 85% of the loss; doubling 10,10 alone = 128 units (34%).
- Invalid actions are charged for the stand fallback and also reported separately.
- **To fix before reporting scenario accuracy:** the accuracy metrics don't filter on `is_scenario_cell` yet (EV loss does).

### Scenario run (step 8) — DONE
- `runs/scenarios_seed2026/`: all 330 scenarios, 517 decisions, 9 invalid. Live accuracy 37.1% counts every decision; the real cell accuracy (first decision only) comes from the final analysis.
- Final analysis (scenario accuracy filter + both runs + comparison) handed to a subagent.

### Final analysis (step 7) — DONE
- **391 tests pass.** Scenario metrics now grade only `is_scenario_cell` rows; natural and scenario runs are never pooled; reference return = exact −0.457%.
- Baseline: **41.7%** (CI 38.9–44.6%), EV loss 0.33/decision, return −0.330 units/hand.
- Scenario: **40.9%** (CI 35.7–46.3%), EV loss 0.27/decision; vs 5/6 63.6%, vs 8/A 24.2%; splits every pair (5,5 wrong on all 10 upcards); 8,8 and A,A perfect.
- Outputs: `results/baseline_seed2026/`, `results/scenarios_seed2026/`, `results/comparison_baseline_seed2026__scenarios_seed2026/`.
- Cosmetic: the scenario EV heatmap footer says "Grey: no decisions" although it has no grey cells.
- **Open for Ian:** commit? gitignore `results/`? "Dealer checked" prompt line (future version)?
