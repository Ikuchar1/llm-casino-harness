"""Odds for the probability tool: what the harness tells the model about the current state.

Three things, computed exactly with the same shoe and dealer model as blackjack/ev.py
(6 decks minus the visible cards, dealer stands on soft 17, dealer peeked):
- the chance of busting if the player hits exactly once;
- the dealer's final-total distribution (17-21 or bust), given no dealer blackjack;
- if the player stands now, the chance to win, push and lose.

The visible cards are the player's current cards and the dealer upcard. No per-action
EV is computed here on purpose: the largest EV is basically the answer.
"""

from dataclasses import dataclass

from blackjack.ev import BUST, add_card, dealer_distribution, hand_value, shoe_probabilities
from blackjack.rules import DEFAULT_RULES, RuleSet


@dataclass(frozen=True)
class Odds:
    """Probabilities (0-1) for one decision."""

    bust_if_hit: float
    dealer: dict[int | str, float]  # keys 17, 18, 19, 20, 21, "bust"
    stand_win: float
    stand_push: float
    stand_lose: float


def compute_odds(player_cards: list[str] | tuple[str, ...], upcard: str, rules: RuleSet = DEFAULT_RULES) -> Odds:
    """The probability tool's odds for these player cards against this dealer upcard."""
    cards = list(player_cards)
    probs = shoe_probabilities(cards + [upcard], rules.num_decks)
    total, is_soft = hand_value(cards)
    dealer = dealer_distribution(upcard, probs, rules)

    bust_if_hit = sum(p for value, p in probs.items() if add_card(total, is_soft, value)[0] > 21)

    win = dealer[BUST] + sum(p for outcome, p in dealer.items() if outcome != BUST and outcome < total)
    push = dealer.get(total, 0.0) if total >= 17 else 0.0
    lose = sum(p for outcome, p in dealer.items() if outcome != BUST and outcome > total)
    return Odds(bust_if_hit=bust_if_hit, dealer=dealer, stand_win=win, stand_push=push, stand_lose=lose)
