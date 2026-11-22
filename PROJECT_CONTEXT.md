# Project Context — for Claude Code

Read this first. It's the briefing for the coding session on this repo.

## What this is

CSCE 480H (Generative AI: Applications, Ethics, and Research; UNL; Fall 2026) team class
project, worth 36% of the grade. Team: Jack, Daniel, Ian, Aden. Ian is in the 480
(undergrad) section, so the citation and length targets below are the 480 numbers.
**Ian is the one coding here**; the other three are writing the paper and will not read the
code. The code exists to produce **numbers, tables, and charts for the paper**.

**Research question:** How much of an LLM agent's decision-making performance comes from the
underlying model versus the *harness* built around it, and which harness components
contribute the most?

A **harness** = everything around the LLM: how game state is presented, tools it can call,
memory kept between hands, and self-checks before acting. Testbeds: **blackjack** (has a
mathematically optimal "basic strategy," so every decision can be graded right/wrong
regardless of the hand's outcome) and later **heads-up no-limit Texas Hold'em** poker.

## Source files — read these for full background

All project history lives in Ian's class-notes repo. **Read-only from this session:
never edit anything under `Notes/`.** Read them in this order; the first two matter most.

Base path: `/Users/ikuchar/Desktop/projects/Notes/fall-2026/CSCE-480H/assignments/class-project/`

| File | What's in it |
|---|---|
| `06-milestone-2-draft.pdf` | **Current state of the paper** (Google Docs export, 2026-11-22). Intro, Related Work, old + proposed-new Methodology, and a list of 5 new sources not yet worked into the text. No Results section. Read with `pdftotext -layout`. |
| `05-methodology-draft.md` | Methodology drafts plus a reviewer pass and **5 open design questions** (summarized below). |
| `03-milestone-1.md` | Milestone 1 Canvas prompt: ACM/Overleaf format rules and the section requirements Milestone 2 builds on. |
| `02-research-poker-harness.md` | Original research (2026-09-28): prior LLM-poker work (PokerSkill, GTO Wizard Benchmark, Poker Arena, PokerBench, SpinGPT, Agent-Pro), terms (HUNL, bb/100, AIVAT, GTO), tooling (PokerKit, Slumbot, RLCard/OpenSpiel), the variance problem, and the three project framings. **Framing A (the ablation) is the one the team picked.** |
| `04-research-related-work.md` | Related-work research (2026-10-29), five buckets of papers plus **ready-made BibTeX entries** for the ACM template (line ~313 on). Its key finding is in "Novelty claim" below. |
| `00-project-introduction.md` | Semester-long project timeline from the instructor. |

Course wiki page: `/Users/ikuchar/Desktop/projects/Notes/fall-2026/CSCE-480H/wiki/assignments/class-project-csce-480h.md`

## Decisions already made (don't re-litigate)

- **Framing:** an ablation study ("which harness piece actually helps?"), with blackjack
  first because every decision can be graded, then HUNL poker.
- **Harness components, in this order:** baseline → (1) probability → (2) strategy info →
  (3) memory → (4) self-evaluation. Each is tested **cumulatively and also alone on top of
  the baseline**, because a component's gain can depend on what comes before it.
- **"Self-evaluation" is a per-decision pre-commit check**, adapted from Reflexion. Don't
  call it Reflexion itself, which reflects *after* failed trials.
- **Poker plans:** scripted leak bots (calling station, maniac, rock) run in our own
  PokerKit games with **duplicate dealing** (each deal played twice with seats swapped to
  cancel luck). Slumbot is played through its own HTTP API and **can't** be dealt in
  duplicate. Report bb/100 ± 95% CI.
- **Changed since Milestone 1:** the old plan assumed a paid-API budget. It's now
  **local models only, $0**. The writers need to know this for the Methodology.

## Open design questions (from `05-methodology-draft.md`, still unresolved)

Flag these to Ian when they come up. Don't silently pick an answer.
1. **Strategy info in blackjack:** if the component hands the model the basic strategy
   chart, accuracy becomes a lookup test against that same chart. Options: general
   principles only, a partial chart, or make this component poker-only.
2. **Memory in blackjack:** basic strategy ignores past hands, so memory can't raise
   accuracy. Make it poker-only, or keep it to measure whether it *hurts*?
3. **Models:** the "model gap vs harness gap" claim needs **at least two models**, e.g.
   `llama3.2:3b` vs `qwen2.5:7b` locally. One model is fine for today's baseline.
4. **Order-effects runs:** "each component alone" doubles the conditions. Is there time
   for it?
5. **Poker sample size vs Slumbot:** with no duplicate dealing there, how many hands is
   realistic?

## Novelty claim (from the related-work research)

`04-research-related-work.md` found **no published accuracy numbers for LLMs measured
against blackjack basic strategy**. Agent-Pro plays blackjack but reports win rate only.
PokerSkill's own paper says the relative contribution of its expert system versus the
LLM's judgment "is not isolated," which is exactly what this ablation does. So the baseline
accuracy number from today is the first data point for the paper's main contribution.

## The deadline driving today

**Milestone 2 is due Sun Nov 22, 2026 at 11:59pm.** As of this morning **no development
work exists**: the paper only has Intro / Related Work / Methodology carried over from
Milestone 1. Milestone 2 adds a required **Results and Discussion** section, which needs
real output from real runs.

**Today's goal: a minimal blackjack baseline that runs end to end and produces results.**
Not the full harness. Poker is out of scope for today.

### Milestone 2 rubric (15 pts)
| Criterion | Satisfactory |
|---|---|
| Alignment with format | ACM SIGCHI format (Overleaf). Teammates handle this. |
| Related Work citations | ≥10 citations total, ≥7 peer-reviewed. Teammates handle this. |
| **Results and Discussion** | "Sufficient coverage of results and discussion portions of the work done so far." Exemplary = rich detail with supporting imagery (charts/figures). **This repo's job.** |
| Addresses M1 comments | Teammates handle this. |

Paper target is ~1,750 words total. The current draft is about 1,730 words, but that
includes two copies of the Methodology, so Results has to make up the difference.

**Remaining timeline:** Milestone 2 team meeting with the instructor in the last weeks of
November · in-class final presentations Dec 3–10 · Raikes showcase Dec 7 (poster or demo
booth, so a live demo of the agent playing would be good) · **final report Dec 16**
(~3,000 words, adding Limitations, Future Work, and Conclusions). The full ablation and
poker have to land by then.

## Constraints

- **No paid APIs. Zero spending.** Use a local model through **Ollama**
  (`http://localhost:11434`, `/api/generate` or `/api/chat`). Default model: `qwen2.5:7b`
  (fall back to `llama3.2:3b` if the machine struggles). Record the exact model tag in outputs.
- Python with a `.venv` in the repo root. Current deps: `requests`, `matplotlib`. Keep a
  `requirements.txt` up to date.
- Runs must be reproducible: **seed the deck RNG** and log the seed, so every harness config
  can later be run on the identical sequence of hands.

## What to build today (minimal baseline)

1. **Blackjack simulator.** Shoe, dealing, player actions (hit, stand, double, split),
   dealer play, payouts. Pick one rule set, state it in a config, and keep it consistent:
   suggested 6 decks, dealer stands on soft 17, double after split allowed, no surrender,
   blackjack pays 3:2. The rule set must be written up in the paper.
2. **Basic strategy table** for exactly that rule set (hard totals, soft totals, pairs ×
   dealer upcard 2–A). Basic strategy originates with Baldwin et al. (1956), but use a
   standard modern chart matching the rule set and **verify it against a published chart**.
   A wrong table silently corrupts every accuracy number.
3. **LLM player, baseline config.** Prompt = brief game description + current state (player
   cards/total, soft or hard, dealer upcard) + the legal actions only. Parse the reply into
   an action. If it's unparseable or illegal, count it as an **invalid action** and apply a
   fallback (e.g. stand) so the hand finishes.
4. **Per-decision logging** (JSONL or CSV), one row per decision: run id, model, harness
   config, seed, hand #, player hand, total, soft?, pair?, dealer upcard, legal actions,
   prompt, raw response, parsed action, optimal action, correct?, invalid?, and the hand's
   final outcome/payout.
5. **Analysis script** that reads the logs and outputs:
   - Decision accuracy: % of decisions matching basic strategy (**primary metric**)
   - Invalid-action rate
   - Average return per hand (units bet)
   - Accuracy broken down by hand type (hard / soft / pair) and by dealer upcard
   - Most common mistake types (e.g. "stood on hard 16 vs 10")
   - At least one chart PNG for the paper (e.g. accuracy by hand type, or a heatmap of
     accuracy by player total × dealer upcard)
   - A short `results.md` summary the writers can lift numbers from directly

**Scale:** a few hundred decisions on the baseline is enough for Milestone 2. Local
inference is slow, so start with ~20 hands to check everything works, then scale up.

## Design for what comes later (don't build yet, but don't block it)

Harness components are added one at a time and also cumulatively, each toggleable by config:
1. **Probability tool:** e.g. bust probability for hitting, dealer final-total distribution
2. **Strategy information:** strategy guidance provided in the prompt
3. **Memory:** prior hands, decisions, and outcomes
4. **Self-evaluation:** the model reconsiders its answer before committing (Reflexion-style)

So: one `HarnessConfig` (or similar) that the LLM player reads, with the baseline being "all
off." Later the same experiments run across multiple local models. Poker comes later via
**PokerKit** (Kim, 2025), scored in bb/100 (big blinds won per 100 hands) against scripted
bots (always-call, overly aggressive).

## The team's methodology (as written in the paper draft)

> Our approach is based around developing a modular harness to evaluate how different tools
> and system configurations affect an LLM's decision-making performance in simulated casino
> games. We mainly focus on blackjack, where mathematically optimal decisions are well
> established, with plans to expand to heads-up no-limit Texas Hold'em poker. For blackjack,
> we use a custom Python simulator and implement basic strategy rules based on Baldwin et al.
> (1956). [...] Gameplay data is generated through these simulations, with each decision
> recorded alongside the game state, model prompt, selected action, and eventual outcome.
>
> Our experimental design begins with a baseline configuration in which the model receives
> only a simple prompt describing the game, its current state, and the available legal
> actions. We then introduce four additional harness components: (1) probability
> calculations [...]; (2) strategy information [...]; (3) memory [...]; and (4)
> self-evaluation [...]. To isolate the effects of each component, we compare
> configurations individually against the baseline and cumulatively as additional components
> are enabled. [...]
>
> Our primary evaluation metric for blackjack is decision accuracy, measured as the
> percentage of actions that match mathematically optimal basic strategy. [...] We also
> track average returns per hand and the frequency of invalid actions [...]. To reduce
> randomness and improve reproducibility, we aim to use consistent game situations across
> configurations, including repeated hands [...].

Whatever actually gets built (rule set, model, prompt wording, number of hands, fallback
for invalid actions) has to be reported back to the writers so the Methodology can say
what was **really** done. Keep a running list in `NOTES_FOR_PAPER.md`.

## Sources the paper cites (for context, not for code)

Baldwin et al. 1956 (optimal blackjack strategy) · Zhang et al. 2026 (harness configuration
> model choice) · ReAct (Yao 2023) · Toolformer (Schick 2023) · Reflexion (Shinn 2023) ·
Tree of Thoughts (Yao 2023) · Agent-Pro (Zhang 2024, blackjack and Hold'em) · PokerSkill
(Li 2026) · PokerKit (Kim 2025) · PokerBench (Zhuang 2025) · AgentBench (Liu 2024) ·
Self-Consistency · "LLMs vs Poker Players" · "LLMs and Complex Card Games"

## How to work with Ian

Ian is a senior CS student who is comfortable with C#/TypeScript and newer to Python, so walk
through Python code clearly. His global CLAUDE.md has his style preferences. Time is tight
today, so prioritize **getting a working run producing numbers** over polish.
