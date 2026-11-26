"""Tests for the fast hand evaluator and Monte Carlo equity the bots use (poker/hands.py).

PokerKit's own evaluator is the reference: ours must rank hands the same way.
"""

import random

from pokerkit import StandardHighHand

from poker.cards import make_deck
from poker.hands import ONE_PAIR, STRAIGHT, STRAIGHT_FLUSH, TWO_PAIR, category, equity_vs_random, hand_value


def test_hands_rank_in_the_same_order_as_pokerkit_over_many_random_seven_card_deals():
    rng = random.Random(0)
    for _ in range(3000):
        deck = make_deck(rng.randrange(10**9))
        board, first, second = deck[:5], deck[5:7], deck[7:9]
        ours = (hand_value(first + board) > hand_value(second + board)) - (hand_value(first + board) < hand_value(second + board))
        pk_first = StandardHighHand.from_game("".join(first), "".join(board))
        pk_second = StandardHighHand.from_game("".join(second), "".join(board))
        theirs = (pk_first > pk_second) - (pk_first < pk_second)
        assert ours == theirs, (first, second, board)


def test_the_wheel_is_a_five_high_straight_and_a_steel_wheel_is_a_straight_flush():
    assert hand_value(["Ac", "2d", "3h", "4s", "5c", "Kd", "Kh"])[:2] == (STRAIGHT, 5)
    assert category(["Ah", "2h", "3h", "4h", "5h"]) == STRAIGHT_FLUSH


def test_fewer_than_five_cards_still_get_a_category():
    assert category(["Ks", "Kd", "4c"]) == ONE_PAIR
    assert category(["Jh", "4h", "Ks", "Jd", "4c"]) == TWO_PAIR


def test_pocket_aces_have_about_85_percent_equity_against_a_random_hand_preflop():
    assert abs(equity_vs_random(["As", "Ah"], [], samples=4000, rng=random.Random(1)) - 0.85) < 0.02


def test_the_nuts_on_the_river_have_full_equity_and_the_same_rng_seed_gives_the_same_equity():
    royal = equity_vs_random(["As", "Ks"], ["Qs", "Js", "Ts", "2d", "3c"], samples=200, rng=random.Random(5))
    assert royal == 1.0
    first = equity_vs_random(["7c", "2d"], ["Ks", "Jd", "4c"], samples=200, rng=random.Random(9))
    assert first == equity_vs_random(["7c", "2d"], ["Ks", "Jd", "4c"], samples=200, rng=random.Random(9))
