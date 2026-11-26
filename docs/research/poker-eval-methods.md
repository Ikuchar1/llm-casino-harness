# How have others evaluated LLM (or other) poker agents against scripted or exploitable opponents, and what should we copy?

Researched 2026-11-25. Budget: hard (brief allowed ~25), used 23 tool calls.

## Answer
Prior LLM poker work almost never uses scripted exploitable bots. Opponents are usually RL/CFR agents in Leduc or Limit Hold'em (Suspicion-Agent, ToolPoker: 100 games per matchup with seats swapped on the same seeds), other LLMs (Poker Arena, the community LLM Poker Arena: 1,000-hand heads-up matches with no CIs), or a near-GTO bot (the GTO Wizard Benchmark and PokerSkill: 5,000+ hands with AIVAT, 200bb stacks reset every hand). So the bot definitions have to be built from poker-strategy archetypes plus simple rule agents like RLCard's limit-holdem rule model. The best fit for us is duplicate dealing (same seeds, seats swapped). Our bots are deterministic and the model runs at temperature 0, so this is nearly free to build. AIVAT would need a bot strategy over full ranges, which our bots don't have. Heads-up NLHE raw SD is roughly 130 bb/100. Unadjusted, 1,000 hands gives a 95% CI of about +/-80 bb/100. That is enough to see large exploits but not a small memory effect. So the primary outcome should be decision-level exploit metrics (bluff rate vs the station, fold rate to the rock's aggression, call-down rate vs the maniac), with bb/100 secondary. Copy PokerSkill's and Poker Arena's action handling: structured output, a validator that clamps to legal sizes, a conservative fallback, and logging of how often the fallback fires.

## Findings

### Opponents and bot definitions
1. **Prior LLM-in-Leduc/Limit studies used learned agents (NFSP, DQN, DMC, CFR+), not scripted archetypes. But they did describe those opponents' behavior in archetype terms, e.g. NFSP as an always-call bot and DQN as a never-fold aggressor.** (High)
   - https://arxiv.org/html/2309.17277v3 (Suspicion-Agent, rev. Aug 2024). WebFetch summarized Figure 3 rather than quoting it: NFSP "always calls and never folds"; DQN is "aggressive, raises with strong and mid hands and never folds"; CFR+ is "conservative, often folds weak hands". These are summarizer wordings, not verbatim quotes.
   - https://arxiv.org/html/2602.00528v1 (ToolPoker, Jan 2026), summarized: baselines are "NFSP, DQN, DMC, and CFR+ for Leduc Hold'em, and NFSP, DQN, DMC, and DeepCFR for Limit Texas Hold'em."
2. **Poker Arena (ICML 2026) uses LLM opponents only. Its prompt tells models to classify opponents into exactly our archetypes using HUD stats (statistics shown on a heads-up display).** (High, primary source)
   - https://arxiv.org/html/2606.13815
   - > "Use VPIP/PFR/AF stats to classify each opponent (TAG, LAG, calling station, nit)."
   - VPIP is voluntarily-put-money-in-pot %, PFR is preflop-raise %, and AF is aggression factor.
3. **Archetype definitions (qualitative, from poker-strategy sources): calling station = loose-passive; maniac = loose and over-aggressive; nit = active only with very strong hands; TAG = few hands, controlled aggression; LAG = looser than TAG but less extreme than a maniac.** (Medium: a strategy site, not research, but it is the conventional definition)
   - https://www.pokerstrategy.com/strategy/bss/five-player-types/ (updated Mar 2026)
   - > "The calling station is a very loose opponent who plays his hands passively."
   - > "This kind of opponent plays a lot of hands and is often overly aggressive, even with weak holdings."
   - > "This type of player is only active with very strong hands and folds a great deal of the time."
   - > "This opponent type plays few hands and uses controlled aggression." (TAG)
   - > "This player type is looser than the TAG, but not quite as extreme as the maniac." (LAG)
   - The same page's exploit advice is "don't bluff" the station, "induce their bluffs" vs the maniac, and attack the nit's blinds but respect its bets. These were summarized by WebFetch, not quoted verbatim.
4. **The numeric VPIP/PFR cutoffs for archetypes vary between sources (e.g. station VPIP 35%+ with PFR 8-12%; maniac PFR >25% or VPIP>40/PFR>30).** (Low: seen only in a search-result summary, page not fetched). Listed under Unverified too.
5. **RLCard ships a simple open-source "rock-like" rule agent for Limit Hold'em. Preflop it raises pairs, AK-AT, suited aces and broadway combos, and folds everything else. Postflop it raises only on board-connected hits. When an action is illegal it substitutes one (raise->call, check->fold, call->raise).** (Medium: read via WebFetch summary of the source file; nesting of one branch was unclear)
   - https://github.com/datamllab/rlcard/blob/master/rlcard/models/limitholdem_rule_models.py
   - Source-code comment, as returned by WebFetch: "Fold all hand types except those mentioned above to save money."

### Variance reduction
6. **Seat-swapped duplicate dealing on fixed seeds is the standard trick in the LLM Leduc/Limit studies.** (High: two independent papers)
   - https://arxiv.org/html/2309.17277v3, summarized: "We ran a series of 50 games with a fixed random seed, thereby keeping the sequence of cards constant across these games." Positions were then switched for another 50.
   - https://arxiv.org/html/2602.00528v1
   - > "Each method plays 100 games with varying random seeds and alternated player positions"
   - Agent-Pro (https://arxiv.org/html/2402.17574v1, ACL 2024) did the 4-player version: "generating 16 distinct permutations to eliminate the impact of chance and playing order."
7. **Duplicate poker was the ACPC's (Annual Computer Poker Competition's) evaluation method. The "baseline" alternative uses the agent's self-play outcome as an unbiased estimator and does not need control of the deal.** (Medium: abstract only, the 2013 paper; PDF redirected and could not be fetched)
   - https://aitopics.org/doc/conferences:A25FDDD2
   - > "an approach that leverages the ability to deal sets of cards to agents in order to reduce variance."
   - > "an agent's outcome in self play to create an unbiased estimator for use in agent evaluation."
8. **AIVAT is provably unbiased and cut SD about threefold in the GTO Wizard Benchmark. It is used there and in PokerSkill, but both rely on a solver-backed opponent that supplies full-range strategies.** (High)
   - https://arxiv.org/html/2603.23660 (GTO Wizard Benchmark, Mar 2026)
   - > "AIVAT achieves a threefold reduction in standard deviation"
   - https://arxiv.org/pdf/2605.30094 (PokerSkill, May 2026), extracted with pdftotext:
   - > "AIVAT is a variance-reduction estimator for poker evaluation [Burch et al., 2018]; Slumbot does not provide it, so Slumbot results are raw chip outcomes with wider confidence intervals."
   - Implementation burden for us is my inference (Low). AIVAT needs the probability of each action the opponent could have taken, plus value estimates. Our deterministic bots could in principle provide the probabilities, but a value function is extra work.
9. **Raw heads-up NLHE variance is about 130 bb/100 SD (a rule-of-thumb figure, not research).** (Medium: one tool site)
   - https://www.deucescracked.com/tools/variance-calculator
   - > "Heads-up NLHE": "130 bb/100"
   - My arithmetic: the 95% half-width is 1.96 x 130 / sqrt(N/100). That is about +/-80 bb/100 at 1,000 hands, +/-57 at 2,000 and +/-36 at 5,000, before any variance reduction.

### Sample sizes and CIs in prior work
10. **The GTO Wizard Benchmark played 5,000 HUNL hands per model and reports a +/-SD with 95%-CI-lower-bound ranking. The best LLM was -16 +/- 3 bb/100 (AIVAT).** (High)
    - https://arxiv.org/html/2603.23660
    - > "We used our GTO Wizard Benchmark API to play 5000 poker hands of HUNL Texas Hold'em per model."
    - > "The best performing agent is GPT-5.3 Extra High reasoning with a luck-adjusted win rate of -16 bb/100."
11. **PokerSkill used at least 5,000 hands with AIVAT and 95% CIs computed as mean +/- 1.96 SE. Even so, the CIs were +/-21 to +/-64 mbb/hand (i.e. +/-2 to 6 bb/100).** (High)
    - https://arxiv.org/pdf/2605.30094
    - > "All PokerSkill and default prompt experiments are evaluated for at least 5,000 hands against GTOWizard with AIVAT variance reduction."
    - > "With PokerSkill, GPT-5.5 XHigh achieves −57 ± 21 mbb/hand against GTOWizard, Claude Opus 4.6 achieves −80 ± 29 mbb/hand, and Claude Opus 4.7 achieves −87 ± 64 mbb/hand."
12. **PokerBench's heads-up games ran 50k hands per checkpoint pair, but only 1,000 hands vs GPT-4 because of inference cost. No variance-reduction method is described.** (High)
    - https://arxiv.org/html/2501.08328v2 (AAAI 2025). These points come from WebFetch's summary: stacks "reset to 100BB for each hand"; seats "randomly assigned before each hand"; and the GPT-4 match was "limited to 1,000 hands because of inference cost."
13. **Suspicion-Agent and ToolPoker used only 100 games per matchup. Suspicion-Agent explicitly blamed budget for this.** (High)
    - https://arxiv.org/html/2309.17277v3
    - > "Due to budgetary constraints, our experiments are limited to running 100 games for each comparison with baseline methods."
14. **The community LLM Poker Arena ran 1,000-hand heads-up matches, reported no CIs, and itself recommends 5,000-10,000 hands per matchup.** (Medium: hobby report, Jan 2026)
    - https://mattohan567.github.io/AI-Poker-Arena/
    - > "Poker is an inherently high-variance game where short-term results can be heavily influenced by luck."
    - The "1,000-hand heads-up matches" and "5,000-10,000 hands" figures are WebFetch-summarized.
15. **Poker Arena ran 1,000 total hands (50 seven-player tournaments x 20 hands).** (High)
    - https://arxiv.org/html/2606.13815
    - > "50 seven-player tournaments of 20 hands each, producing 1,000 hands and 9,115 logged actions."

### Metrics besides bb/100
16. **PokerBench grades decisions against solver labels: Action Accuracy (right action type) and Exact Match (right size too). It keeps only spots where the dominant solver action has more than 50% probability.** (High)
    - https://arxiv.org/html/2501.08328v2
    - > "Action accuracy measures if LLMs can take game theory optimal actions (fold, raise, bet, etc.) for a given spot."
    - > "Exact match accuracy also considers if the wager amount is game theory optimal."
17. **Solver-agreement accuracy did not predict winning against an imperfect opponent. This is why exploit studies should use opponent-specific metrics, not GTO agreement.** (High)
    - https://arxiv.org/html/2501.08328v2
    - > "despite achieving higher test accuracy, our fine-tuned Llama model was outplayed by GPT-4."
18. **Prior studies report behavioral stats as secondary metrics: VPIP, PFR, AF, fold-to-raise, WTSD (went-to-showdown %), fold/raise frequency by street, and a judged bluff axis.** (High: three sources)
    - https://arxiv.org/html/2606.13815
    - > "aggression factor spans 0.69 (Kimi, passive) to 3.34 (Grok, hyper-aggressive)."
    - > "Poker Arena reports a nine-axis cognitive profile spanning deterministic, regex-verified, and judge-scored measures."
    - https://arxiv.org/html/2402.17574v1 (Agent-Pro): the figures show Fold and Raise frequencies by stage (summarized).
    - https://mattohan567.github.io/AI-Poker-Arena/ lists VPIP, PFR, AF, fold to raise and WTSD (summarized).
19. **Poker Arena's memory result: whether memory helps depends on the model, so treat memory as a per-model axis.** (High, primary; directly relevant to our ablation)
    - https://arxiv.org/html/2606.13815
    - > "Whether persistent memory is an asset thus depends on the model's prior-update behaviour."
    - > "memory must be benchmarked as a model-conditional axis, not a binary switch."
    - Their memory design: a 16K-character text buffer per agent and session, starting empty each session (summarized).

### Match structure
20. **The standard HUNL eval structure resets stacks every hand and alternates the button, with fixed blinds. The GTO Wizard Benchmark used 200bb with 50/100 blinds. PokerBench used 100bb. ToolPoker used 100 chips with 1/2 blinds (50bb).** (High)
    - https://arxiv.org/html/2603.23660
    - > "with player chip stacks resetting to 20 000 before each hand begins."
    - > "Blinds were 50 and 100 chips, with stack sizes of 200 big blinds."
    - https://arxiv.org/pdf/2605.30094
    - > "Positions alternate every hand: the player who was the button becomes the big blind in the next hand, and vice versa."
    - https://arxiv.org/html/2501.08328v2: GTO strategies are calculated at 100BB stacks (summarized).

### LLM-specific pitfalls
21. **Raw LLM output is prone to invalid sizing and hallucination. PokerSkill passes it through a validator that clamps to legal bounds and falls back to the most conservative action, which happened in under 0.1% of hands.** (High)
    - https://arxiv.org/pdf/2605.30094
    - > "a bare LLM receives the game state and all legal actions without context, producing raw outputs prone to invalid sizing, hallucination, and weak strategy."
    - > "If the LLM output fails validation, the system defaults to the most conservative viable action; such fallbacks occur in fewer than 0.1% of hands."
22. **Poker Arena parses actions with a three-stage fallback (JSON, then regex, then default check/fold). The GTO Wizard prompt restricts output to legal action codes plus an amount.** (High)
    - https://arxiv.org/html/2606.13815
    - > "When the tool call is malformed, a three-stage fallback (JSON, regex, default to check/fold) recovers an action."
    - https://arxiv.org/html/2603.23660
    - > "instructed it to output a valid poker action alongside the betting amount if the action was a bet or a raise."
23. **Prompt growth: PokerSkill keeps conversation context only within a hand. Poker Arena caps memory at 16K characters and splits stable instructions from the dynamic state. Suspicion-Agent reports degradation from long prompts.** (Medium)
    - https://arxiv.org/pdf/2605.30094
    - > "Conversation context is maintained within each hand."
    - https://arxiv.org/html/2606.13815: the prompt is split to "separate stable instructions from dynamic game state, enabling efficient caching" (summarized quote).
    - The Suspicion-Agent long-prompt point is summarized only.
24. **PokerKit lets the harness validate amounts before applying them. The min/max raise-to amounts can be queried, and invalid operations raise ValueError without changing the state.** (High: official docs)
    - https://pokerkit.readthedocs.io/en/stable/simulation.html
    - > "If the verification fails, the state remains unchanged."
    - > "All the errors raised are `ValueError` (or `UserWarning` if configured as such)."
    - The queriers are `can_complete_bet_or_raise_to`, `min_completion_betting_or_raising_to_amount` and `max_completion_betting_or_raising_to_amount`.

## Conflicts
- **Hands needed.** Published LLM studies ran 100 games (Suspicion-Agent, ToolPoker) or 1,000 hands (PokerBench vs GPT-4, LLM Poker Arena). The community arena itself says 5,000-10,000 per matchup, and the GTO Wizard Benchmark and PokerSkill used 5,000+ hands with AIVAT and still got +/-2-6 bb/100. The larger figures are better grounded statistically. Small-sample studies relied on large effects or reported no CIs at all.
- **Does memory help?** Agent-Pro's belief/reflection ablation lowered chips from 4.3 to 2.5 when removed, i.e. reflection helped (search snippet, not fetched). Poker Arena says the effect is model-conditional. Poker Arena is more recent and tested more models, so I can't tell which generalizes to qwen2.5.
- **Stack depth:** 200bb (GTO Wizard), 100bb (PokerBench) and 50bb (ToolPoker, 100 chips at 1/2). There is no single convention; 100bb is the most common "standard" depth.

## Unverified
- Numeric VPIP/PFR cutoffs per archetype (station VPIP 35%+ / PFR 8-12%; maniac PFR >25% or VPIP>40/PFR>30; nit VPIP<18%; LAG VPIP and PFR >25%). Seen only in a search summary of various strategy sites.
- PokerSkill's claim of about 30x variance reduction from AIVAT over raw duplicate. Seen in a search summary, not located in the extracted text.
- All-in EV adjustment (replacing the chip result of a pre-river all-in with equity x pot). No fetched source in this run. It is standard poker-tracker practice and is easy to implement with an equity calculator, but its effect size is unverified.
- Agent-Pro's ablation numbers (4.3 -> 2.5 chips). Search snippet only.
- The secondary blog claim that GTO Wizard "crushed" LLMs over 5,000 hands. Superseded by the primary paper above.

## Leads
- ToolPoker's (arXiv 2602.00528) LLM-as-judge "action-reasoning consistency" metric could check whether qwen's written opponent notes actually drive its actions (the knowing-doing gap). The second half of that paper (Appendix C.4) was not read.
- Poker Arena section text past 100k characters (memory ablation details, the bluff axis definition) was not read. It is worth reading for the memory-gating design.
- Husky Hold'em Bench (NeurIPS 2025) has LLMs write poker bots, with 1,000-hand games, and could be a source of rule-bot code. Not fetched.

## Sources read
- https://arxiv.org/html/2603.23660 (GTO Wizard Benchmark, Mar 2026): AIVAT, 5,000 hands, 200bb, stack resets, action format, results.
- https://arxiv.org/html/2606.13815 (Poker Arena, ICML 2026): memory as a model-conditional axis, parsing fallback, behavioral metrics, archetype prompt.
- https://arxiv.org/pdf/2605.30094 (PokerSkill, May 2026; text via pdftotext): validator and fallback rate, 5,000+ hands, CI formula, button alternation, within-hand context.
- https://arxiv.org/html/2309.17277v3 (Suspicion-Agent, Aug 2024): 100 games, seat-swapped fixed seeds, opponent behavior descriptions, cost limits.
- https://arxiv.org/html/2602.00528v1 (ToolPoker, Jan 2026): 100 games with alternated positions, 100-chip stacks with 1/2 blinds, LLM-judge metrics.
- https://arxiv.org/html/2402.17574v1 (Agent-Pro, ACL 2024): 16-permutation dealing, fold/raise frequency by street.
- https://arxiv.org/html/2501.08328v2 (PokerBench, AAAI 2025): AA/EM metrics, 100bb resets, 50k/1,000-hand games, accuracy not equal to win rate.
- https://mattohan567.github.io/AI-Poker-Arena/ (community, Jan 2026): 1,000-hand HU matches, metrics list, no CIs.
- https://github.com/datamllab/rlcard/blob/master/rlcard/models/limitholdem_rule_models.py (RLCard): rule-agent logic and illegal-action substitution.
- https://pokerkit.readthedocs.io/en/stable/simulation.html (PokerKit docs): legal-amount queriers, ValueError behavior.
- https://www.pokerstrategy.com/strategy/bss/five-player-types/ (PokerStrategy, 2026): archetype definitions and exploits.
- https://www.deucescracked.com/tools/variance-calculator (DeucesCracked): HU NLHE SD of 130 bb/100.
- https://aitopics.org/doc/conferences:A25FDDD2 (AAMAS 2013 abstract): duplicate poker and the baseline estimator.

---

## Recommended setup for our study

This section is my synthesis from the findings above. Numbers marked "est." are my arithmetic or judgement, not sourced.

**Bot rules.** Make every bot a deterministic function of (hole cards, board, street, facing-bet, pot) so duplicate dealing works. Use one fixed bet size (e.g. 2/3 pot), so the only signal is the habit under test.
- **Calling station:** never folds and never raises; always check or call (an all-in call when facing all-in). Exploit: value-bet thin and never bluff. Habit metric: the model's bluff rate (bets or raises with weak hands, e.g. below about 30% equity vs random) should go down, and its value-bet rate with medium-plus hands should go up.
- **Maniac:** always bets or raises when legal (2/3 pot, or a min-raise when facing a bet), up to a cap of, say, 3 raises per street to avoid infinite loops. It calls when it can't raise and never folds. Exploit: call down wider and stop bluffing. Habit metric: the model's call-down rate with medium hands facing the maniac's river bet, and its fold-to-bet rate (should go down).
- **Rock / nit:** preflop, continue only with a premium range (e.g. TT+, AQ+, roughly 4-5% of hands, like RLCard's tighter cousin) and fold everything else, including in the big blind facing a raise. Postflop, bet or raise only with top pair or better and fold otherwise to any bet. Exploit: steal relentlessly and fold to its aggression. Habit metrics: the model's preflop open/raise rate (should go up), and its fold rate when the rock bets or raises (should go up).
- **No-leak control:** a bot with no single dominant habit. The cheapest defensible choice is a fixed TAG-ish equity-threshold bot. It raises when Monte Carlo equity vs random exceeds a high threshold, calls when equity exceeds the pot odds, and otherwise checks or folds, with a fixed small bluff frequency driven by a hash of the card seed (so it stays deterministic). Its role is to show that memory doesn't help, or hurts, when there is nothing to exploit. Don't call it GTO.

**Variance reduction.** Use duplicate dealing first. Generate N deck seeds, and play each seed twice with seats swapped (model as button, then model as big blind) against the same bot. Use the same seed list for memory-on and memory-off and for both models. Then the memory delta is a paired difference per seed-pair, so analyse it with a paired t-test or a bootstrap over seed-pairs. Optionally add an all-in EV adjustment: when all chips go in before the river, score the hand at equity x pot. With PokerKit plus a Monte Carlo equity function this is a small change, but it is unverified here. Skip AIVAT, because it needs value estimates we don't have time to build.

**Hands per match (est.).** At about 3 model decisions per hand and 2-5 s each, a hand takes about 6-15 s. That makes 1,000 hands about 2-4 GPU-hours. Plan 500 seed-pairs = 1,000 hands per (model x bot x memory) cell. The grid is 2 models x 4 bots x 2 memory conditions = 16 cells, i.e. 16,000 hands, about 30-65 GPU-hours. If compute is short, cut the control bot to 500 hands, or run 14b on two bots only. Raw bb/100 CIs at 1,000 hands are about +/-80 bb/100 before the duplicate pairing tightens them. That is fine for the large exploits (vs a never-folding or always-raising bot, a good exploit should win well over 50 bb/100) but weak for small memory deltas. Hence the metric priority below.

**Metrics (in priority order).**
1. The per-bot habit metric above, computed over decisions. Hundreds of decisions per match give tight binomial CIs.
2. Change in that metric over time within a match (first 100 hands vs last 500). This is the learning signal that memory should create.
3. bb/100 with a 95% CI computed as mean +/- 1.96 SE over duplicate seed-pairs (the PokerSkill formula).
4. VPIP, PFR, AF and WTSD per condition, as descriptive profiles.
5. Invalid-output rate and fallback rate.
6. Prompt length in tokens per decision.

Don't grade against a solver; PokerBench shows GTO agreement doesn't predict exploiting an imperfect opponent.

**Stack and match rules.** Use heads-up, blinds 1/2 (or 50/100), and 100bb stacks reset before every hand (GTO Wizard and PokerBench practice). Alternate the button every hand, use a fixed hand count per match, and have no rebuys or bust-outs. Opponent notes persist across hands within a match. Clear them between matches so each match starts from empty memory (Poker Arena practice).

**LLM handling.**
- Give the model the legal actions and the exact min/max raise-to amounts from PokerKit's queriers. Ask for JSON {action, amount}.
- Parse with JSON first, then regex, then fall back to check, or fold if check is illegal.
- Clamp out-of-range amounts to [min, max] rather than rejecting them.
- Log every clamp and fallback, and report the rate per condition. A memory condition that inflates fallbacks is a confound.
- Keep per-decision context to the current hand plus a capped notes block (a fixed character budget), so the memory-on and memory-off prompts differ only by that block.
