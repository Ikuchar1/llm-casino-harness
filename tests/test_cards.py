"""Tests for card values, hand totals, and the per-hand seeded shoe."""

from blackjack.cards import (
    RANKS,
    card_value,
    hand_total,
    is_blackjack,
    make_shoe_for_hand,
    shoe_seed_string,
)


def test_number_cards_count_face_value():
    assert card_value("2") == 2
    assert card_value("9") == 9
    assert card_value("10") == 10


def test_face_cards_count_ten():
    assert card_value("J") == 10
    assert card_value("Q") == 10
    assert card_value("K") == 10


def test_ace_counts_eleven_before_soft_adjustment():
    assert card_value("A") == 11


def test_hard_total_without_aces():
    assert hand_total(["10", "7"]) == (17, False)


def test_ace_with_six_is_soft_17():
    assert hand_total(["A", "6"]) == (17, True)


def test_ace_drops_to_one_when_eleven_would_bust():
    # A + 6 + 10 = 17 hard (the ace must count as 1).
    assert hand_total(["A", "6", "10"]) == (17, False)


def test_two_aces_is_soft_12():
    assert hand_total(["A", "A"]) == (12, True)


def test_multiple_aces_only_one_counts_eleven():
    # A + A + A + 8 = 11 + 1 + 1 + 8 = 21, soft.
    assert hand_total(["A", "A", "A", "8"]) == (21, True)


def test_multiple_aces_all_count_one_when_needed():
    # A + A + 9 + 10 = 21 hard.
    assert hand_total(["A", "A", "9", "10"]) == (21, False)


def test_bust_total_is_reported_as_hard():
    assert hand_total(["10", "6", "K"]) == (26, False)


def test_blackjack_is_two_card_21():
    assert is_blackjack(["A", "K"])
    assert is_blackjack(["10", "A"])
    assert not is_blackjack(["7", "7", "7"])
    assert not is_blackjack(["A", "9"])


def test_six_deck_shoe_has_312_cards_with_24_of_each_rank():
    shoe = make_shoe_for_hand(run_seed=1, hand_number=0, num_decks=6)
    assert len(shoe) == 312
    for rank in RANKS:
        assert shoe.count(rank) == 24


def test_same_seed_and_hand_number_give_same_shoe():
    first = make_shoe_for_hand(run_seed=42, hand_number=7, num_decks=6)
    second = make_shoe_for_hand(run_seed=42, hand_number=7, num_decks=6)
    assert first == second


def test_different_hand_numbers_give_different_shoes():
    first = make_shoe_for_hand(run_seed=42, hand_number=7, num_decks=6)
    second = make_shoe_for_hand(run_seed=42, hand_number=8, num_decks=6)
    assert first != second


def test_shoe_is_stable_across_python_processes():
    # Pinned value: if this ever changes, every logged run stops being reproducible.
    # (Python's built-in hash() of strings is randomized per process; random.Random
    # seeded with a str is not, because it hashes the string with SHA-512.)
    shoe = make_shoe_for_hand(run_seed=42, hand_number=0, num_decks=6)
    assert shoe[:8] == PINNED_FIRST_EIGHT_CARDS


def test_seed_string_combines_run_seed_and_hand_number():
    assert shoe_seed_string(42, 7) == "42-7"


# Recorded from two separate Python processes (with PYTHONHASHSEED=random).
PINNED_FIRST_EIGHT_CARDS = ["K", "2", "4", "A", "8", "J", "9", "2"]
