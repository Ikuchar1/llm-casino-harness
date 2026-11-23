# Showcase demo plan (decided 2026-11-22)

The terms are defined in `CONTEXT.md` (Seat, Full harness, Visitor). The demo is for the Raikes showcase on Dec 7 and the in-class presentations on Dec 3–10.

## Flow

1. The visitor plays 3 hands. Each hand is one first decision: two cards plus the dealer upcard, then Hit / Stand / Double / Split. Split is offered only on pairs.
2. The baseline and the full harness answer the same 3 deals.
3. The results screen shows one row per hand: You, Baseline, Full harness, Basic strategy, with ✓/✗ and a score line ("You 2/3 · Baseline 1/3 · Full harness 3/3"). Tapping a hand shows both agents' reasoning and the odds the full harness was given. An invalid agent reply shows as "invalid ✗", the same way the study scores it.
4. A live board shows the running average for each seat: visitors, baseline, full harness. All three are computed over the deals visitors actually played.

## Data

- The deal pool is the 330-deal scenario set (`agent/scenarios.py`), and each visitor gets 3 deals picked uniformly at random.
- Agent answers are precomputed, and `qwen2.5:7b` fills both agent seats. Mac scenario runs serve as development data for now, and the HCC scenario runs replace them once they exist. A script exports the run folders into one `demo_data.json`.
- A small local Python server (`scripts/demo_server.py`) serves the page and appends each visitor's result to `demo/visitor_results.jsonl`, which is gitignored. The tracker survives restarts. No names or personal details are stored.
- Visitor data is shown at the booth only and never reported in the paper, since that would need IRB review.

## Look

A dark casino table:
- Green felt, animated card dealing, three seats, and chip-style action buttons.
- The reveal flips the agents' cards, then the results table slides up.
- The live board uses the paper chart palette.

First, 2–3 throwaway prototypes of the play screen let Ian pick a direction.

## Decisions after the prototypes

- **Direction:** prototype A (Classic Felt), scaled up a lot because it was hard to see.
- **Play-out:** each hand plays out to the end, but only the first decision is graded. The visitor draws from the scenario's forced shoe, which is the same card order the agents saw. The agents' full hands, splits included, are replayed card by card from the run files (`hands.jsonl`, `decisions.jsonl`). The win/loss result is for fun only. Splits follow the rule set: one split, and split aces get one card each.
- **Reveal:** one hand at a time, borrowed from prototype C, with tap to advance.
  1. The deal is shown again along with the visitor's move.
  2. The Baseline chip flips, then the Full harness chip.
  3. The basic strategy answer stamps in, and ✓/✗ appears on each seat.
  4. Each seat's hand plays out.
  After the last hand comes the score tally, then the summary table with tappable rows.
- **Attract mode:** after about 30 s idle, the table auto-plays a demo hand under a "Can you beat the AI? Tap to play" banner, with the live board visible. Any tap starts a game.
- **Presenter mode:** opened by a hidden keyboard shortcut.
  - Ian picks each deal, or random, and plays any number of hands.
  - "See results" shows the session comparison with the same one-by-one reveal.
  - Presenter hands are not recorded to the live board.

## Later

Live model calls instead of precomputed answers are optional and come after the precomputed version works.
