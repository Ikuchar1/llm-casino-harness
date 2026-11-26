"""A fast hand evaluator for the bots, for any 3 to 7 cards.

PokerKit has an evaluator and an equity helper, but its equity helper samples from
Python's global `random` (so it can't be seeded per decision) and its evaluator takes
about 0.14 ms per hand, too slow for hundreds of Monte Carlo samples per decision.
This one ranks hands the same way (tests check it against PokerKit).
"""

from collections import Counter

from poker.cards import RANKS

HIGH_CARD, ONE_PAIR, TWO_PAIR, TRIPS, STRAIGHT, FLUSH, FULL_HOUSE, QUADS, STRAIGHT_FLUSH = range(9)

_RANK_VALUE = {rank: value for value, rank in enumerate(RANKS, start=2)}  # "2" -> 2 ... "A" -> 14


def hand_value(cards: list[str]) -> tuple[int, ...]:
    """A tuple that compares like the best 5-card hand in `cards`: (category, tiebreakers...)."""
    values = sorted((_RANK_VALUE[card[0]] for card in cards), reverse=True)
    suits = Counter(card[1] for card in cards)
    flush_suit = next((suit for suit, count in suits.items() if count >= 5), None)
    if flush_suit is not None:
        flush_values = sorted((_RANK_VALUE[card[0]] for card in cards if card[1] == flush_suit), reverse=True)
        high = _straight_high(flush_values)
        if high:
            return (STRAIGHT_FLUSH, high)

    counts = Counter(values)
    groups = sorted(counts.items(), key=lambda item: (item[1], item[0]), reverse=True)
    top, top_count = groups[0]
    second, second_count = groups[1] if len(groups) > 1 else (0, 0)
    if top_count == 4:
        return (QUADS, top, max((v for v in values if v != top), default=0))
    if top_count == 3 and second_count >= 2:
        return (FULL_HOUSE, top, second)
    if flush_suit is not None:
        return (FLUSH, *flush_values[:5])
    high = _straight_high(values)
    if high:
        return (STRAIGHT, high)
    if top_count == 3:
        return (TRIPS, top, *[v for v in values if v != top][:2])
    if top_count == 2 and second_count == 2:
        return (TWO_PAIR, top, second, max((v for v in values if v not in (top, second)), default=0))
    if top_count == 2:
        return (ONE_PAIR, top, *[v for v in values if v != top][:3])
    return (HIGH_CARD, *values[:5])


def category(cards: list[str]) -> int:
    """HIGH_CARD ... STRAIGHT_FLUSH for the best hand in `cards`."""
    return hand_value(cards)[0]


def _straight_high(values: list[int]) -> int:
    """The top card of the best straight in these values (5 for the wheel), or 0."""
    unique = sorted(set(values), reverse=True)
    if 14 in unique:
        unique.append(1)  # the ace also plays low
    run = 1
    for previous, current in zip(unique, unique[1:]):
        run = run + 1 if previous - current == 1 else 1
        if run == 5:
            return current + 4
    return 0
