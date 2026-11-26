# What is the best-supported way to give an LLM poker/game agent opponent memory (especially model-written notes) so it learns real patterns without locking onto one early observation?

Researched 2026-11-25. Budget: hard (brief said ~25; hard stop 20), used 20 tool calls.

## Answer
No paper I found tests "premature persona lock-in" in poker notes directly. The best-supported designs all do one thing that plain notes do not: they score or check each belief against outcomes or predictions. Hypothetical Minds keeps several hypotheses and scores each by how well it predicts the opponent's next move (Rescorla-Wagner update, validation threshold 0.7, top-5 kept). ExpeL gives each insight a vote count, and an insight that is voted down to zero is dropped. Agent-Pro keeps a reflected belief only if a replayed game confirms it. Generative Agents makes each reflection cite the numbered memories behind it. Separate evidence shows LLMs anchor on early hints and resist contrary evidence ("nearly all" of 9 models tested in DERELAB), and they do poorly at self-correction without outside feedback. So free-form self-revised notes are the riskiest form of C. Human HUD practice gives concrete sample-size floors: about 20 hands for VPIP/PFR at the loosest, 100+ in more conservative sources, and postflop stats counted by opportunities rather than hands. Small models are a real concern. Weaker base models (GPT-3.5, Llama2-70B) clearly underperformed GPT-4 with the same memory and reflection machinery, and nothing I found tested 7B/14B.

## Findings
1. **Hypothetical Minds generates natural-language hypotheses about other agents' strategies and keeps the ones that predict well.** (High: primary paper)
   - https://arxiv.org/abs/2407.07086
   - > "reinforcing hypotheses that make correct predictions about the other agents' behavior"
   - > ablations "reveal the importance of hypothesis evaluation and refinement for succeeding on complex scenarios."

2. **Hypothetical Minds' scoring details: a Rescorla-Wagner value per hypothesis, +c/−c reward per correct or incorrect prediction, α = 0.3, validation threshold 0.7, top_k = 5 hypotheses evaluated in parallel.** (High: primary paper, full HTML)
   - https://arxiv.org/html/2407.07086
   - > "We set the validation threshold Vthr = 0.7 apriori based on analysis of the Rescorla-Wagner dynamics."
   - > "With reward values of c = 1 and learning rate = 0.3"
   - Cost: per the fetched summary, each ToM step costs "(3 + top_k) LLM calls if no hypothesis is validated yet" and 2 after validation. The summary also reported that "Adding hypothesis evaluation (MMP + HE) and refinement (full HM) improved performance", that Llama-3 results were "relatively robust" to α and the threshold, and that smaller learning rates did better.

3. **Hypothetical Minds' results depend on model strength. GPT-4 was clearly best, and Llama-3-70B fell between GPT-4 and GPT-3.5, or below GPT-3.5 on Prisoner's Dilemma.** (Medium: primary paper, but only the summarizer's paraphrase plus one short quote)
   - https://arxiv.org/html/2407.07086
   - > GPT-4 "significantly outperformed the other models across all tasks."

4. **Agent-Pro keeps natural-language beliefs about itself and its opponents ("world-belief"), updates them every decision, and reflects on beliefs rather than on single actions.** (High: primary paper)
   - https://arxiv.org/abs/2402.17574
   - > "Rather than action-level reflection, Agent-Pro iteratively reflects on past trajectories and beliefs."
   - https://arxiv.org/html/2402.17574
   - > "These beliefs are updated in each decision-making cycle."

5. **Agent-Pro accepts a reflected belief or policy only if it improves the score on a replay of the same game, so an unverified "lesson" is discarded.** (High: primary paper)
   - https://arxiv.org/html/2402.17574
   - > "If it fails to pass verification after three retries, we discard this trajectory."
   - The fetched summary also says that reflecting directly on action sequences without beliefs was "quite unstable" and produced vaguer, more verbose instructions (GPT-4 chip gain fell from 4.3 to 2.5).

6. **Agent-Pro depends on the base model. Llama2-70B in Hold'em became "highly conservative" and folded early, and GPT-3.5 still trailed the DMC (Deep Monte-Carlo RL) baseline.** (Medium: primary paper, quote plus paraphrase)
   - https://arxiv.org/html/2402.17574
   - > "the learning process of the Agent-Pro heavily relies on the capability of the foundational model."

7. **Suspicion-Agent infers opponent "pattern/preference" beliefs from the game history each round, inside a Reflexion-style module. GPT-3.5 won only 50% where GPT-4 won 100%. The authors blame weaker instruction following, degradation on long prompts, and weaker theory-of-mind (ToM) reasoning.** (Medium: primary paper; the 2023 source is over 12 months old and pre-dates current models)
   - https://arxiv.org/html/2309.17277v3
   - > "infer several beliefs about the opponent's game pattern/preference for each round."
   - > "the winning probability for agents built on GPT-3.5 stands at just 50%"

8. **Readable Minds (Apr 2026 preprint, Claude Sonnet 4, 100-hand Hold'em sessions): agents that write and read natural-language notes between hands show ToM-like behavior. However, their opponent-model predictions were only 55.4% directionally accurate, not significantly above chance.** (Medium: single non-peer-reviewed preprint, one model family)
   - https://arxiv.org/html/2604.04157
   - > "can write and read natural-language notes between hands"
   - > "directional accuracy was 55.4% (above chance but not significantly so"
   - Relevance: model-written notes make the agent look like it models the opponent more than its predictions back up. The paper gives no note size, update cadence or failure-mode analysis.

9. **ExpeL manages its learned insights as a list with ADD/EDIT/UPVOTE/DOWNVOTE operations. New insights start at count 2, and an insight is removed when its count reaches 0, explicitly to stop misleading insights from persisting.** (High: primary paper)
   - https://arxiv.org/html/2308.10144
   - > "A newly added insight will have an initial importance count of two associated with it."
   - > "If an insight's importance count reaches zero, it will be removed."
   - > "since even successful trajectories can be suboptimal and mislead the generated insights"

10. **Generative Agents triggers reflection on accumulated importance, not every step, and makes every insight cite the numbered memories it rests on.** (High: primary paper)
    - https://arxiv.org/html/2304.03442
    - > "What 5 high-level insights can you infer from the above statements? (example format: insight (because of 1, 5, 3))"
    - > reflections fire when importance passes "a threshold (150 in our implementation)"; agents "reflected roughly two or three times a day."
    - Reported failure modes include agents that "fabricated embellishments to the agent's memory" and "failed to retrieve relevant memories". (2023 source.)

11. **LLMs show confirmation bias when updating beliefs: they accept agreeing evidence and resist contrary updates across multi-turn belief-revision dialogues.** (Medium: one 2026 preprint, abstract only)
    - https://arxiv.org/abs/2608.30413
    - > "nearly all exhibit a systematic tendency to accept congruent evidence while resisting incongruent updates"
    - This is the direct mechanism behind the owner's worry. Once a note says "calling station", later folds are likely to be discounted.

12. **LLMs struggle to self-correct without external feedback, and can get worse.** (High: well-known primary paper, Huang et al., 2023/ICLR 2024)
    - https://arxiv.org/abs/2310.01798
    - > "LLMs struggle to self-correct their responses without external feedback"
    - > "their performance even degrades after self-correction."
    - Implication: a note rewritten only from the model's own previous note carries no new feedback. Each rewrite needs fresh evidence in the prompt, such as counts or recent hands.

13. **In human HUD practice, about 20 hands is the loosest quoted floor for VPIP/PFR. Aggression factor needs about 100, and postflop stats need 100 to 1000+.** (Medium: strategy blog; the number varies by source)
    - https://www.blackrain79.com/2017/11/poker-hud-stat-sample-size.html
    - > "You need about 20 hands in order to get accurate information for this stat."
    - > "You need 100 hands on your opponent before drawing any conclusions here."
    - > "A lot of people make all kinds of mistakes by drawing incorrect conclusions from insufficient data."

14. **Preflop stats converge fastest. For postflop stats, count opportunities rather than hands: one player had only 11 c-bet opportunities in 300 hands.** (Medium: PokerNews, quoting pro Ryan Laplante)
    - https://www.pokernews.com/strategy/teachable-moments-from-twitch-ryan-laplante-hud-stats-32348.htm
    - > "instead of looking at the number of hands played, you must look at the number of opportunities presented"
    - > "we saw that this player only had 11 opportunities to c-bet in the 300 hands they had played together."

## Conflicts
- **VPIP sample size:** BlackRain79 says about 20 hands (https://www.blackrain79.com/2017/11/poker-hud-stat-sample-size.html). The search summary attributed "100 marginal / 500+ confident" to DeucesCracked and PokerStrategy, but I did not fetch those pages. For the study, the leak bots are extreme (VPIP close to 100% or close to 10%), so roughly 20 hands is enough to separate them. Against subtler opponents, the conservative figure would apply.
- **Do notes help?** Readable Minds says memory notes are needed for ToM-like behavior to emerge, but the notes' predictive accuracy was not significantly above chance (55.4%). Hypothetical Minds and Agent-Pro show gains only when beliefs are checked against outcomes. Notes without feedback look weaker. That is my inference across papers, not a head-to-head test.

## Unverified
- DERELAB reportedly found that a thinking-mode Qwen3-32B had near-zero default confirmation bias (search snippet only; the PDF did not parse).
- Lou & Sun (arXiv 2412.06593) reportedly found that Chain-of-Thought, reflection and "ignore the anchor" prompts do not remove anchoring (search snippet only).
- An arXiv 2611.05720 study reportedly found that search agents are sensitive to the order of early evidence, but not when all evidence is given at once (snippet only). If it holds, this supports giving the model the full stats or history at rewrite time instead of letting a note build up incrementally.
- PokéChamp's authors note that their static opponent modelling can be exploited adversarially (snippet only).
- PokerBench, PokerSkill (Li 2026), the Werewolf/Diplomacy agents and Reflexion itself were not fetched in this run. I have no cited findings for them.
- EMO (NAACL 2025, "LLM-Based Explicit Models of Opponents") builds one model per opponent with "bi-level feedback-refinement"; the abstract alone gives no mechanism detail.
- No source tested 7B/14B models on opponent-note memory. The small-model caution is extrapolated from GPT-3.5 and Llama2/3-70B results.

## Leads
- CEO-Poker (NYU Shanghai 2026 thesis, Yuanheng Li) uses modular opponent modeling plus a blend of GTO (game-theory-optimal) and exploitative play: https://cdn.shanghai.nyu.edu/sites/default/files/yuanheng_li_thesis_nyush_honors_2026.pdf. It may be the "PokerSkill/Li 2026" the brief meant. Check it.
- "How Far Are LLMs from Professional Poker Players?" (arXiv 2602.00528) covers agentic tool use in poker and may have opponent-stat tools.
- "Dynamic Theory of Mind as a Temporal Memory Problem" (arXiv 2603.14646) frames ToM failures as a memory and retrieval problem.

## Sources read
- https://arxiv.org/abs/2407.07086 and https://arxiv.org/html/2407.07086 (Hypothetical Minds, 2024): hypothesis generation, scoring, threshold, top-k, cost, ablations.
- https://arxiv.org/abs/2402.17574 and https://arxiv.org/html/2402.17574 (Agent-Pro, 2024): belief and reflection loop, verification, weak-model results.
- https://arxiv.org/abs/2309.17277 and https://arxiv.org/html/2309.17277v3 (Suspicion-Agent, 2023): opponent-pattern inference, GPT-3.5 failure.
- https://arxiv.org/html/2604.04157 (Readable Minds, Apr 2026 preprint): poker notes memory, 55.4% accuracy.
- https://arxiv.org/abs/2608.30413 (DERELAB, 2026): LLM confirmation bias in belief updating.
- https://arxiv.org/abs/2310.01798 (Huang et al., 2023): no self-correction without external feedback.
- https://arxiv.org/html/2308.10144 (ExpeL, 2023): voted insight list with removal at zero.
- https://arxiv.org/html/2304.03442 (Generative Agents, 2023): evidence-cited reflections, importance trigger.
- https://aclanthology.org/2025.naacl-long.41/ (EMO, NAACL 2025): abstract only.
- https://www.blackrain79.com/2017/11/poker-hud-stat-sample-size.html (BlackRain79): HUD sample sizes.
- https://www.pokernews.com/strategy/teachable-moments-from-twitch-ryan-laplante-hud-stats-32348.htm (PokerNews): convergence; opportunities rather than hands.

---

## Recommended design for C: "evidence-gated hypothesis notes"
These design rules are synthesized from findings 1-14. They are my inference and have not been tested as a package.

1. **Harness keeps the ground truth and the model writes the interpretation.** The harness tracks counts with opportunities, such as `VPIP 14/15 hands`, `fold-to-bet 0/9 opportunities`, `raise when checked to 7/8`. Every note-update prompt includes this table plus the last ~5 raw hands. The model never rewrites the note from the old note alone (findings 11-12, 14).
2. **The note is a short list of competing hypotheses, not one persona.** Use a fixed schema with at most 3 hypotheses and a hard cap of about 80-120 words:
   ```
   H1: never folds to bets | for: 9/9 bets called | against: 0 | status: TENTATIVE
   H2: plays every hand preflop | for: 14/15 | against: 1 | status: CONFIRMED
   Exploit now: value-bet thin, don't bluff
   ```
   Requiring "for" and "against" counts copies Generative Agents' "because of 1, 5, 3" citations and Hypothetical Minds' multiple hypotheses (findings 1, 2, 10). The word cap protects 7B/14B models from long-prompt degradation (finding 7).
3. **The harness, not the model, enforces status gates.** A hypothesis can be marked CONFIRMED only when its supporting count is at least N opportunities, say 8-10 for the extreme leak bots and around 20 hands for VPIP-type claims (finding 13). Below that it stays TENTATIVE, and the action prompt says "tentative reads should only nudge play." The harness checks the cited counts against its own table and rejects or downgrades claims that don't match.
4. **Hypotheses are killed by prediction error, not by the model changing its mind.** Before each opponent decision point (or once per hand), the harness notes what each hypothesis predicts, such as "H1 predicts call." It scores the prediction against the actual action with a simple Rescorla-Wagner value or an ExpeL-style vote count, and drops a hypothesis when the value falls below a threshold (findings 2, 9). This gives the outside feedback that self-correction lacks (finding 12). To keep costs down, the prediction can come from the existing note in the same call as the action, so no extra call is needed.
5. **Cadence: rewrite every N = 5 hands, not every hand.** Each rewrite is a full rewrite from evidence, not an append. The old note is shown but labelled "previous hypotheses; revise or discard based on the counts below." Cost is about 1 extra call per 5 hands, roughly 20% overhead at one decision call per hand. Generative Agents' thresholded, non-continuous reflection supports this choice over per-hand updates (finding 10).
6. **Ablation hygiene:** log every note version and the stat table at each rewrite. That way lock-in can be measured directly, for example how many hands pass between the first contrary evidence and the note's revision.

### Alternative 1: B+C hybrid with stats that always ship and a one-line note
Always inject the harness stats with sample sizes (design B), and let the model add only a one-sentence "exploit plan" refreshed every 5 hands. This is cheapest and most robust for 7B models. It tests less of the model's own pattern discovery, though.

### Alternative 2: Hypothetical-Minds-lite
At hand 5, ask the model for 3 candidate opponent types. The harness then scores each candidate's per-action predictions automatically with RW α ≈ 0.3 and threshold ≈ 0.7. The top candidate is shown to the action prompt only once it is validated. This is the most direct defence against lock-in, but it costs (3 + k) calls per generation step until a candidate is validated (finding 2).
