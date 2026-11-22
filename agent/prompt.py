"""Builds the baseline prompt: a system message with the rules and reply format,
and a user message with the current decision state only.

Baseline means no strategy hints, no probabilities, and no history of earlier hands.
"""

from blackjack.cards import card_value
from blackjack.engine import DecisionState
from blackjack.rules import RuleSet

# Bump this whenever any prompt text changes, so runs made with different prompts
# are never mixed (it is logged on every decision and checked on resume).
# v1 ("Think briefly about the best play, then end your reply with ...") made
# qwen2.5:7b answer with a bare ACTION line and no reasoning; v2 asks for reasoning first.
PROMPT_VERSION = "baseline-v2"

FORMAT_INSTRUCTION = (
    "First explain your reasoning in two or three sentences. Then end your reply with a "
    "final line of exactly the form `ACTION: <one of the legal actions>`."
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


def build_user_prompt(state: DecisionState) -> str:
    """The current decision state only: cards, total, pair, split, upcard, legal actions.

    "Pair" means the two cards have equal value, even when splitting is no longer
    legal (after the one allowed split); the legal actions show whether split is offered.
    """
    softness = "soft" if state.is_soft else "hard"
    lines = [
        f"Your cards: {', '.join(state.player_cards)}",
        f"Your total: {softness} {state.total}",
        f"Pair: {'yes' if _is_pair(state.player_cards) else 'no'}",
    ]
    if state.from_split:
        lines.append(f"This hand came from a split (hand {state.hand_index + 1} of 2).")
    lines += [
        f"Dealer upcard: {state.dealer_upcard}",
        f"Legal actions: {', '.join(state.legal_actions)}",
    ]
    return "\n".join(lines)


def _is_pair(cards: tuple[str, ...]) -> bool:
    return len(cards) == 2 and card_value(cards[0]) == card_value(cards[1])
