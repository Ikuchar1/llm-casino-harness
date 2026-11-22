"""Basic strategy for the study's rule set, plus a bot player that follows it.

Source chart: Wizard of Odds, "4-Deck to 8-Deck Blackjack Strategy", dealer
stands on soft 17, double after split allowed, no surrender
(https://wizardofodds.com/games/blackjack/strategy/4-decks/). Encoded 2026-11-22.
This matches the rule set in blackjack/rules.py (6 decks, S17, DAS, no surrender).

Chart codes:
    H  = hit
    S  = stand
    Dh = double if allowed, otherwise hit
    Ds = double if allowed, otherwise stand
    P  = split (with DAS, every split on this chart is a plain split)

Each table has one row per player hand and one column per dealer upcard,
in the order 2, 3, 4, 5, 6, 7, 8, 9, 10, A. Hand totals of 4-8 and 17+ are
written out in full so every cell can be checked against the chart. (The engine
stands any 21 automatically, so the 21 rows are never actually looked up.)
"""

from blackjack.cards import card_value
from blackjack.engine import DOUBLE, HIT, SPLIT, STAND, DecisionState

DEALER_UPCARDS = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "A"]

# fmt: off
# Hard totals (no ace counted as 11). Key = player total.
HARD_TOTALS: dict[int, list[str]] = {
    #      2     3     4     5     6     7     8     9     10    A
    4:  ["H",  "H",  "H",  "H",  "H",  "H",  "H",  "H",  "H",  "H"],
    5:  ["H",  "H",  "H",  "H",  "H",  "H",  "H",  "H",  "H",  "H"],
    6:  ["H",  "H",  "H",  "H",  "H",  "H",  "H",  "H",  "H",  "H"],
    7:  ["H",  "H",  "H",  "H",  "H",  "H",  "H",  "H",  "H",  "H"],
    8:  ["H",  "H",  "H",  "H",  "H",  "H",  "H",  "H",  "H",  "H"],
    9:  ["H",  "Dh", "Dh", "Dh", "Dh", "H",  "H",  "H",  "H",  "H"],
    10: ["Dh", "Dh", "Dh", "Dh", "Dh", "Dh", "Dh", "Dh", "H",  "H"],
    11: ["Dh", "Dh", "Dh", "Dh", "Dh", "Dh", "Dh", "Dh", "Dh", "H"],
    12: ["H",  "H",  "S",  "S",  "S",  "H",  "H",  "H",  "H",  "H"],
    13: ["S",  "S",  "S",  "S",  "S",  "H",  "H",  "H",  "H",  "H"],
    14: ["S",  "S",  "S",  "S",  "S",  "H",  "H",  "H",  "H",  "H"],
    15: ["S",  "S",  "S",  "S",  "S",  "H",  "H",  "H",  "H",  "H"],
    16: ["S",  "S",  "S",  "S",  "S",  "H",  "H",  "H",  "H",  "H"],
    17: ["S",  "S",  "S",  "S",  "S",  "S",  "S",  "S",  "S",  "S"],
    18: ["S",  "S",  "S",  "S",  "S",  "S",  "S",  "S",  "S",  "S"],
    19: ["S",  "S",  "S",  "S",  "S",  "S",  "S",  "S",  "S",  "S"],
    20: ["S",  "S",  "S",  "S",  "S",  "S",  "S",  "S",  "S",  "S"],
    21: ["S",  "S",  "S",  "S",  "S",  "S",  "S",  "S",  "S",  "S"],
}

# Soft totals (one ace counted as 11). Key = player total.
# Soft 12 is A,A when splitting is not legal (not on the published chart; always hit).
SOFT_TOTALS: dict[int, list[str]] = {
    #      2     3     4     5     6     7     8     9     10    A
    12: ["H",  "H",  "H",  "H",  "H",  "H",  "H",  "H",  "H",  "H"],   # A,A
    13: ["H",  "H",  "H",  "Dh", "Dh", "H",  "H",  "H",  "H",  "H"],   # A,2
    14: ["H",  "H",  "H",  "Dh", "Dh", "H",  "H",  "H",  "H",  "H"],   # A,3
    15: ["H",  "H",  "Dh", "Dh", "Dh", "H",  "H",  "H",  "H",  "H"],   # A,4
    16: ["H",  "H",  "Dh", "Dh", "Dh", "H",  "H",  "H",  "H",  "H"],   # A,5
    17: ["H",  "Dh", "Dh", "Dh", "Dh", "H",  "H",  "H",  "H",  "H"],   # A,6
    18: ["S",  "Ds", "Ds", "Ds", "Ds", "S",  "S",  "H",  "H",  "H"],   # A,7
    19: ["S",  "S",  "S",  "S",  "S",  "S",  "S",  "S",  "S",  "S"],   # A,8
    20: ["S",  "S",  "S",  "S",  "S",  "S",  "S",  "S",  "S",  "S"],   # A,9
    21: ["S",  "S",  "S",  "S",  "S",  "S",  "S",  "S",  "S",  "S"],   # soft 21 always stands
}

# Pairs, used only when splitting is legal. Key = rank of each card ("10" = any 10-value).
# 5,5 is never split: its row is the same as hard 10.
PAIRS: dict[str, list[str]] = {
    #        2     3     4     5     6     7     8     9     10    A
    "2":  ["P",  "P",  "P",  "P",  "P",  "P",  "H",  "H",  "H",  "H"],
    "3":  ["P",  "P",  "P",  "P",  "P",  "P",  "H",  "H",  "H",  "H"],
    "4":  ["H",  "H",  "H",  "P",  "P",  "H",  "H",  "H",  "H",  "H"],
    "5":  ["Dh", "Dh", "Dh", "Dh", "Dh", "Dh", "Dh", "Dh", "H",  "H"],
    "6":  ["P",  "P",  "P",  "P",  "P",  "H",  "H",  "H",  "H",  "H"],
    "7":  ["P",  "P",  "P",  "P",  "P",  "P",  "H",  "H",  "H",  "H"],
    "8":  ["P",  "P",  "P",  "P",  "P",  "P",  "P",  "P",  "P",  "P"],
    "9":  ["P",  "P",  "P",  "P",  "P",  "S",  "P",  "P",  "S",  "S"],
    "10": ["S",  "S",  "S",  "S",  "S",  "S",  "S",  "S",  "S",  "S"],
    "A":  ["P",  "P",  "P",  "P",  "P",  "P",  "P",  "P",  "P",  "P"],
}
# fmt: on


def _column_key(rank: str) -> str:
    """Turn a rank into its chart key: J/Q/K become "10", everything else is unchanged."""
    if rank == "A":
        return "A"
    return str(card_value(rank))


def chart_code(state: DecisionState) -> str:
    """Look up the raw chart code (H, S, Dh, Ds, or P) for this decision.

    The pair table is used only when splitting is legal. A pair that can't be
    split (already split once) is looked up by its hard or soft total instead.
    """
    column = DEALER_UPCARDS.index(_column_key(state.dealer_upcard))
    if state.is_pair:
        return PAIRS[_column_key(state.player_cards[0])][column]
    if state.is_soft:
        return SOFT_TOTALS[state.total][column]
    return HARD_TOTALS[state.total][column]


def best_legal_action(state: DecisionState) -> str:
    """The basic strategy action, adjusted to what is actually legal right now.

    Dh becomes hit and Ds becomes stand when doubling is not legal. This is the
    action a decision is graded against.
    """
    code = chart_code(state)
    can_double = DOUBLE in state.legal_actions
    if code == "H":
        return HIT
    if code == "S":
        return STAND
    if code == "Dh":
        return DOUBLE if can_double else HIT
    if code == "Ds":
        return DOUBLE if can_double else STAND
    if code == "P":
        return SPLIT
    raise ValueError(f"Unknown chart code: {code}")


class BasicStrategyPlayer:
    """A bot that always plays the best legal basic strategy action."""

    def decide(self, state: DecisionState) -> str:
        return best_legal_action(state)
