"""Cards, hand totals, and the per-hand seeded shoe.

Cards are plain rank strings ("A", "2", ..., "10", "J", "Q", "K"). Suits never
matter in blackjack, so they are left out.

Seeding follows ADR 0001 (docs/adr/0001-fresh-seeded-shoe-per-hand.md): every
hand gets its own freshly shuffled shoe, seeded from (run seed, hand number).
"""

import random

RANKS: list[str] = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]

# Each deck has 4 of every rank (one per suit).
CARDS_PER_RANK_PER_DECK = 4


def card_value(rank: str) -> int:
    """Return a card's blackjack value. Aces return 11; hand_total lowers them to 1."""
    if rank == "A":
        return 11
    if rank in ("J", "Q", "K"):
        return 10
    return int(rank)


def hand_total(cards: list[str]) -> tuple[int, bool]:
    """Return (total, is_soft) for a list of ranks.

    A hand is soft when one ace is still counted as 11 without busting.
    Every other ace counts as 1.
    """
    total = sum(card_value(rank) for rank in cards)
    aces_counted_as_eleven = cards.count("A")

    # Lower aces from 11 to 1, one at a time, until the hand no longer busts.
    while total > 21 and aces_counted_as_eleven > 0:
        total -= 10
        aces_counted_as_eleven -= 1

    is_soft = aces_counted_as_eleven > 0
    return total, is_soft


def is_blackjack(cards: list[str]) -> bool:
    """True for a two-card 21 (an ace plus a 10-value card).

    The engine is responsible for not calling a split hand's 21 a blackjack.
    """
    return len(cards) == 2 and hand_total(cards)[0] == 21


def shoe_seed_string(run_seed: int, hand_number: int) -> str:
    """The string used to seed hand N's shoe, e.g. "42-7". Logged with every hand."""
    return f"{run_seed}-{hand_number}"


def make_shoe_for_hand(run_seed: int, hand_number: int, num_decks: int) -> list[str]:
    """Build and shuffle a fresh shoe for one hand.

    random.Random seeded with a string is stable across Python processes
    (it hashes the string with SHA-512), unlike the built-in hash(), which is
    randomized per process.
    """
    shoe = RANKS * (CARDS_PER_RANK_PER_DECK * num_decks)
    rng = random.Random(shoe_seed_string(run_seed, hand_number))
    rng.shuffle(shoe)
    return shoe
