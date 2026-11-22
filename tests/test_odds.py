"""Tests for the probability tool's odds (blackjack/odds.py)."""

import pytest

from blackjack.ev import BUST, DEALER_OUTCOMES, action_evs, dealer_distribution, shoe_probabilities
from blackjack.odds import compute_odds

UPCARDS = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "A"]
HANDS = [["10", "6"], ["A", "6"], ["5", "4"], ["8", "8"], ["A", "A"], ["10", "2"], ["9", "3", "4"], ["A", "2", "5"]]


@pytest.mark.parametrize("upcard", UPCARDS)
@pytest.mark.parametrize("cards", HANDS)
def test_every_distribution_sums_to_one(cards, upcard):
    odds = compute_odds(cards, upcard)
    assert set(odds.dealer) == set(DEALER_OUTCOMES)
    assert sum(odds.dealer.values()) == pytest.approx(1.0)
    assert odds.stand_win + odds.stand_push + odds.stand_lose == pytest.approx(1.0)
    assert 0.0 <= odds.bust_if_hit <= 1.0


@pytest.mark.parametrize("upcard", UPCARDS)
def test_dealer_distribution_matches_ev_module(upcard):
    cards = ["10", "6"]
    expected = dealer_distribution(upcard, shoe_probabilities(cards + [upcard]))
    assert compute_odds(cards, upcard).dealer == pytest.approx(expected)


@pytest.mark.parametrize("upcard", UPCARDS)
@pytest.mark.parametrize("cards", HANDS)
def test_stand_win_minus_lose_is_the_stand_ev(cards, upcard):
    odds = compute_odds(cards, upcard)
    stand_ev = action_evs(cards, upcard, can_double=False, can_split=False)["stand"]
    assert odds.stand_win - odds.stand_lose == pytest.approx(stand_ev)


def test_dealer_bust_rate_under_a_six_is_about_42_percent():
    assert compute_odds(["10", "6"], "6").dealer[BUST] == pytest.approx(0.42, abs=0.01)


@pytest.mark.parametrize("upcard", ["10", "K"])
def test_dealer_bust_rate_under_a_ten_without_blackjack_is_21_to_23_percent(upcard):
    assert 0.21 <= compute_odds(["10", "6"], upcard).dealer[BUST] <= 0.23


def test_ace_upcard_is_conditioned_on_no_blackjack():
    # With the 10 ruled out as the hole card, the dealer can't make 21 on two cards,
    # so 21 is much rarer than the unconditioned ~36% (blackjacks included).
    odds = compute_odds(["10", "6"], "A")
    assert odds.dealer[21] < 0.10


def test_hard_16_hit_bust_is_the_chance_of_a_six_or_more():
    # 10,6 vs 10: 6..10 bust. Count them in a 6-deck shoe minus 10, 6, 10.
    counts = {6: 24 - 1, 7: 24, 8: 24, 9: 24, 10: 96 - 2}
    assert compute_odds(["10", "6"], "10").bust_if_hit == pytest.approx(sum(counts.values()) / (312 - 3))


@pytest.mark.parametrize("cards", [["A", "6"], ["A", "A"], ["5", "4"], ["2", "3"], ["A", "2", "5"]])
def test_hands_that_cannot_bust_on_one_card_have_zero_hit_bust(cards):
    assert compute_odds(cards, "7").bust_if_hit == 0.0


def test_stand_on_low_total_wins_only_when_the_dealer_busts():
    odds = compute_odds(["10", "2"], "6")
    assert odds.stand_win == pytest.approx(odds.dealer[BUST])
    assert odds.stand_push == 0.0


def test_stand_on_20_pushes_with_dealer_20():
    odds = compute_odds(["10", "K"], "10")
    assert odds.stand_push == pytest.approx(odds.dealer[20])
    assert odds.stand_lose == pytest.approx(odds.dealer[21])
