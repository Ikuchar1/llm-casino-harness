"""The seeded 52-card deck for one poker hand.

Cards are PokerKit strings: rank then suit, e.g. "As", "Td", "2c".
"""

import random

RANKS = "23456789TJQKA"
SUITS = "cdhs"


def make_deck(seed: int) -> list[str]:
    """A freshly shuffled deck. random.Random(int) gives the same order in every process."""
    deck = [rank + suit for rank in RANKS for suit in SUITS]
    random.Random(seed).shuffle(deck)
    return deck
