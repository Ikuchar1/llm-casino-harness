# Poker plan (grill session started 2026-11-25)

The terms are defined in `CONTEXT.md`. This is the poker phase of the ablation: a stretch goal that comes after blackjack.

## Purpose

Poker is the test of **memory**, the one harness component blackjack can't use, because the blackjack dealer has no patterns to learn. The question is whether memory helps the model notice an opponent's habit and exploit it.

The model plays heads-up no-limit Hold'em in PokerKit against scripted leak bots. Chip results alone are too noisy to separate small effects at the sample sizes we can afford, which is why poker tests one targeted question instead of repeating the full blackjack ablation.

## Decisions

| # | Topic | Decision |
|---|---|---|
| 1 | Purpose | Poker tests memory: does it help the model exploit a leak bot? |
| 2 | Memory design | Evidence-gated opponent notes (option C, made safe). See "Memory" below. |
| 3 | Opponents | 4 bots: calling station (never folds), maniac (always bets and raises), rock (premium hands only), and a no-leak control bot that checks whether memory invents a habit that isn't there. Heads-up: the model plays a separate match against each bot, one bot per match, and the bots never play each other. |
| 4 | Main metric | Exploit rate: per decision, did the model make the habit-specific right move against this bot (e.g. value-bet and stop bluffing vs the calling station; fold weak hands to the rock's raises). bb/100 is reported as a secondary number, because raw heads-up variance is about ±80 bb/100 at 1,000 hands. See docs/research/poker-eval-methods.md. |
| 5 | Luck reduction | Duplicate dealing: every seeded deck is dealt twice with the model and bot swapping seats. The same seeds are reused across memory-on and memory-off (and across models), so differences come from the harness, not the cards. No AIVAT. |
| 6 | Stacks | Both players start every hand with 100 big blinds (reset each hand); the button alternates. Nobody busts, and every hand is scored on its own. |
| 7 | Setups and models | 2x2: {plain model, full tools} x {memory off, memory on}. Full tools = poker versions of probability (equity), strategy (e.g. preflop hand chart), and self-check, all of which must be built. Run all 4 setups x 4 bots on qwen2.5:7b first (16 matches); qwen2.5:14b is the stretch goal (another 16). This revises decision 1: poker's main question is still memory, measured with and without the other tools. |
| 8 | Hands per match | 1,000 hands = 500 seeded decks dealt twice (seats swapped). Rough cost: ~4 calls/hand x ~3 s, so 3-4 h per match and ~55-65 GPU-h for the 16 matches on 7b, split across parallel HCC jobs. |
| 9 | Bot rules | Deterministic scripts, one fixed bet size (2/3 pot). Calling station: never folds or raises, always check/call. Maniac: always bets/raises (cap 3 raises per street), never folds. Rock: preflop plays only TT+/AQ+, postflop bets only with top pair or better, else folds to any bet. Control: plain equity-threshold play with no single habit (not GTO). Per-bot habit metrics are in docs/research/poker-eval-methods.md, "Recommended setup". |
| 10 | Full-table play | Stretch goal only, not part of the study: a short 5-handed table (model + all 4 bots) as a showcase demo, with no stats claimed. Reasons: duplicate dealing would need 5 rotations per deck, wins can't be attributed to one habit, and memory would have to track 4 opponents at once. |
| 11 | Slumbot | Late stretch goal, after full-table play. It has no habit to learn, so it doesn't test memory; it runs through an external HTTP API, so no duplicate dealing (noisy); and it is an outside dependency during HCC runs. The control bot covers the no-leak case in the study. |
| 12 | Action format | Fixed menu: fold, check/call, raise 1/2 pot, raise pot, all-in (only legal options shown; sizes clamped to PokerKit min/max raise). Unreadable answer -> check, or fold if check is illegal. Log every fallback and clamp, and report the rate per setup (a setup that inflates fallbacks is a confound). |
| 13 | Build order and timeline | Blackjack HCC runs come first (due 2026-11-29). Then: (1) core loop - PokerKit, 4 bots, duplicate dealing, action menu, logging; (2) memory, and run plain vs plain+memory on 7b (the headline result); (3) poker full tools (equity, hand chart, self-check), then run the other half of the 2x2. If time runs short, step 3 is cut. Ian's presentation is 2026-12-08, so the plain-vs-memory results should be in by about 2026-12-06 for slides; final report due 2026-12-16. |
| 14 | Prediction-error scoring | Skipped. The tally plus threshold gating already prevents forced personas, so it isn't worth the build time. |

## Memory

Research: `docs/research/poker-memory.md`. The risk it addresses is the model locking onto one early read of the opponent. LLMs show confirmation bias and can't self-correct without outside feedback.

- The harness keeps a tally of the opponent's actions per opportunity, e.g. "faced a bet 9 times, folded 0".
- Every 5 hands, the model rewrites its notes in full from the tally plus the last 5 raw hands. It never just appends. The old notes are shown, labelled "previous notes; revise or discard based on the counts below".
- The notes hold at most 3 hypotheses in about 100 words, each with counts for and against, e.g. `never folds to bets | for 9 | against 0 | TENTATIVE`.
- The harness, not the model, sets the status. A hypothesis is CONFIRMED only once its supporting count reaches the threshold: about 8–10 opportunities for the extreme leak bots, and about 20 hands for how often it plays a hand at all. Below that it stays TENTATIVE. The decision prompt says tentative reads should only nudge play. The harness checks each count the model cites against its own tally and downgrades any that don't match.
- The harness writes the notes shown at decision time (2026-11-27, chosen by Ian; memory-v5). The model still picks up to 3 reads per rewrite, each with its own text, a key and counts, but the decision prompt shows only the harness's evidence sentence and status for each kept read, e.g. `- folded when facing a bet 14 of 20 times — TENTATIVE`. The rewrite prompt's previous notes are shown the same way (key, current counts, status). The model's text is logged only, so reads whose text contradicts their key (qwen2.5:7b wrote "never folds to bets" on `faced_bet.fold` at 10/1) stay measurable but never reach play. If two reads cite the same key, the first is kept and the rest are dropped as `duplicate_key`.
- Cost: about one extra model call every 5 hands.
- Every version of the notes and the tally is logged, so lock-in can be measured, e.g. how many hands pass between the first contrary evidence and the revision.
- Decided against (decision 14): scoring each hypothesis's predictions against the opponent's actual actions and dropping failing ones (the Hypothetical Minds approach). The tally plus threshold gating already guards against forcing a persona.
