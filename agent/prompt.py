"""Builds the decision prompt: a system message with the rules and reply format,
and a user message with the current decision state.

Baseline means no strategy hints, no probabilities, and no history of earlier hands.
Harness components add to this per config (see agent/config.py):
- probability tool: an odds block in the user message (odds_lines);
- strategy information: the principles (agent/strategy_info.py) appended to the system
  prompt after one blank line (agent/llm_player.py);
- self-evaluation: a second turn in the same conversation with recheck_prompt().
"""

from agent.config import BASELINE, HarnessConfig
from blackjack.cards import card_value
from blackjack.engine import DecisionState
from blackjack.odds import compute_odds
from blackjack.rules import DEFAULT_RULES, RuleSet

# Bump this whenever any prompt text changes, so runs made with different prompts
# are never mixed (it is logged on every decision and checked on resume).
# v1 ("Think briefly about the best play, then end your reply with ...") made
# qwen2.5:7b answer with a bare ACTION line and no reasoning; v2 asks for reasoning first.
# v3 adds a "Dealer checked for blackjack" state line under 10-value and ace upcards,
# because the dealer peeks: at any player decision the dealer is known not to have blackjack.
PROMPT_VERSION = "baseline-v3"

PEEK_LINE = "Dealer checked for blackjack: no blackjack."

# The probability tool's block heading. The baseline prompt never contains it.
ODDS_HEADER = "Odds (worked out from the cards left in the shoe):"

# How the reply must end. Shared by the system prompt and the self-evaluation re-check.
ACTION_LINE_FORM = "a final line of exactly the form `ACTION: <one of the legal actions>`"

FORMAT_INSTRUCTION = (
    "First explain your reasoning in two or three sentences. Then end your reply with "
    f"{ACTION_LINE_FORM}."
)

# Self-evaluation: after the first reply, the same conversation continues with this
# generic, content-free re-check (it names the first action, nothing else). Bump the
# version if either text changes; it is recorded in the run metadata.
SELF_EVAL_VERSION = "self-eval-v2"
RECHECK_PROMPT = (
    "You chose {first_action}. Before you commit, re-check that choice against the rules and your "
    f"cards. Briefly explain your re-check, then give your final answer as {ACTION_LINE_FORM}."
)
RECHECK_PROMPT_INVALID = (
    "Your reply did not contain a valid action. Re-check the rules and your cards. Briefly explain "
    f"your re-check, then give your final answer as {ACTION_LINE_FORM}."
)


def build_system_prompt(rules: RuleSet) -> str:
    """The game description, the full rule set in plain words, and the reply format."""
    dealer_rule = "hits soft 17" if rules.dealer_hits_soft_17 else "stands on soft 17"
    if rules.double_after_split:
        double_rule = "You may double on any first two cards, including after a split."
    else:
        double_rule = "You may double on any first two cards, but not after a split."
    split_rule = (
        "You may split any two cards of equal value (for example 8 and 8, or K and Q) once; "
        "there is no resplitting."
        if rules.max_splits == 1
        else "Splitting is not allowed."
    )
    aces_rule = "Split aces receive exactly one card each." if rules.split_aces_one_card else ""
    payout = "3 to 2" if rules.blackjack_payout == 1.5 else f"{rules.blackjack_payout} to 1"

    lines = [
        "You are playing blackjack against a dealer. The goal is to finish closer to 21 than the "
        "dealer without going over 21.",
        "",
        "Rules:",
        f"- The game uses {rules.num_decks} decks shuffled together.",
        "- Number cards count their value, J, Q and K count 10, and an ace counts 1 or 11.",
        f"- The dealer must draw to 17 and {dealer_rule}.",
        f"- {double_rule}",
        f"- {split_rule}",
    ]
    if aces_rule:
        lines.append(f"- {aces_rule}")
    lines += [
        "- There is no surrender and no insurance.",
        "- When the dealer's upcard is an ace or a 10-value card, the dealer checks for blackjack "
        "before you act; if the dealer has blackjack the hand ends immediately.",
        f"- Blackjack (an ace and a 10-value card as your first two cards) pays {payout}. "
        "A two-card 21 after a split counts as 21, not blackjack.",
        f"- Your bet is {rules.bet} unit per hand.",
        "",
        "Actions:",
        "- hit: take another card.",
        "- stand: take no more cards.",
        "- double: double your bet, take exactly one more card, then stand.",
        "- split: split a pair into two separate hands, each with its own bet.",
        "",
        FORMAT_INSTRUCTION,
    ]
    return "\n".join(lines)


def recheck_prompt(first_action: str | None) -> str:
    """The self-evaluation re-check for a first answer (None = the first reply was invalid)."""
    if first_action is None:
        return RECHECK_PROMPT_INVALID
    return RECHECK_PROMPT.format(first_action=first_action)


def build_user_prompt(state: DecisionState, config: HarnessConfig = BASELINE, rules: RuleSet = DEFAULT_RULES) -> str:
    """The decision prompt: the state lines, then any per-decision harness blocks, then legal actions.

    With the baseline config this is the current decision state only (cards, total,
    pair, split, upcard, peek result, legal actions), byte-identical to baseline-v3.
    With the probability tool on, an odds block goes between the state lines and the
    legal actions.

    "Pair" means the two cards have equal value, even when splitting is no longer
    legal (after the one allowed split); the legal actions show whether split is offered.
    """
    lines = _state_lines(state)
    if config.probability_tool:
        lines += ["", *odds_lines(state, rules), ""]
    lines.append(f"Legal actions: {', '.join(state.legal_actions)}")
    return "\n".join(lines)


def odds_lines(state: DecisionState, rules: RuleSet = DEFAULT_RULES) -> list[str]:
    """The probability tool's block: hit-once bust chance, dealer final totals, stand-now odds."""
    # On a split hand the other hand's first card (same value as ours) is gone too,
    # matching how decisions are graded (analysis/ev_loss.py).
    extra = (state.player_cards[0],) if state.from_split else ()
    odds = compute_odds(state.player_cards, state.dealer_upcard, rules, extra_removed=extra)
    dealer_label = "Dealer final total"
    if card_value(state.dealer_upcard) in (10, 11):  # the dealer peeked, so the odds assume no blackjack
        dealer_label += " (no blackjack)"
    dealer = ", ".join(f"{outcome}: {_percent(p)}" for outcome, p in odds.dealer.items())
    return [
        ODDS_HEADER,
        f"- If you hit once: {_percent(odds.bust_if_hit)} chance to bust.",
        f"- {dealer_label}: {dealer}.",
        f"- If you stand now: win {_percent(odds.stand_win)}, push {_percent(odds.stand_push)}, "
        f"lose {_percent(odds.stand_lose)}.",
    ]


def _percent(p: float) -> str:
    return f"{100 * p:.1f}%"


def _state_lines(state: DecisionState) -> list[str]:
    """Cards, total, pair, split, upcard and peek result (everything before the legal actions)."""
    softness = "soft" if state.is_soft else "hard"
    lines = [
        f"Your cards: {', '.join(state.player_cards)}",
        f"Your total: {softness} {state.total}",
        f"Pair: {'yes' if _is_pair(state.player_cards) else 'no'}",
    ]
    if state.from_split:
        lines.append(f"This hand came from a split (hand {state.hand_index + 1} of 2).")
    lines.append(f"Dealer upcard: {state.dealer_upcard}")
    if card_value(state.dealer_upcard) in (10, 11):
        # The dealer peeks under a 10 or an ace, so reaching a decision means no blackjack.
        lines.append(PEEK_LINE)
    return lines


def _is_pair(cards: tuple[str, ...]) -> bool:
    return len(cards) == 2 and card_value(cards[0]) == card_value(cards[1])
