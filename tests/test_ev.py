"""Tests for the expected-value calculator (blackjack/ev.py).

EV = expected units won per 1-unit initial bet. Published reference values:

- Wizard of Odds, dealer final-total probabilities, 6 decks, S17, after the
  dealer checked for blackjack:
  https://wizardofodds.com/games/blackjack/appendix/2a/
- Wizard of Odds, infinite-deck player expected return under basic strategy
  (S17, DAS, given the dealer has no blackjack):
  https://wizardofodds.com/games/blackjack/player-expected-return/
"""

import itertools
import math

import pytest

from blackjack.cards import hand_total
from blackjack.engine import DecisionState
from blackjack.ev import (
    BUST,
    DEALER_OUTCOMES,
    INFINITE,
    action_evs,
    best_action,
    card_points,
    dealer_distribution,
    shoe_probabilities,
)
from blackjack.strategy import DEALER_UPCARDS, best_legal_action

# --- shoe probabilities ----------------------------------------------------------


def test_card_points_ace_is_1_and_faces_are_10():
    assert card_points("A") == 1
    assert card_points("7") == 7
    assert [card_points(r) for r in ("10", "J", "Q", "K")] == [10, 10, 10, 10]


def test_infinite_deck_probabilities_are_one_thirteenth_per_rank():
    probs = shoe_probabilities(["10", "6", "5"], num_decks=INFINITE)  # removed cards are ignored
    assert probs[1] == pytest.approx(1 / 13)
    assert probs[10] == pytest.approx(4 / 13)
    assert sum(probs.values()) == pytest.approx(1)


def test_six_deck_probabilities_remove_the_known_cards():
    probs = shoe_probabilities(["10", "K", "6"], num_decks=6)  # 312 - 3 = 309 cards left
    assert probs[10] == pytest.approx(94 / 309)
    assert probs[6] == pytest.approx(23 / 309)
    assert probs[1] == pytest.approx(24 / 309)
    assert sum(probs.values()) == pytest.approx(1)


# --- dealer distribution ----------------------------------------------------------


@pytest.mark.parametrize("upcard", DEALER_UPCARDS)
def test_dealer_distribution_sums_to_one(upcard):
    dist = dealer_distribution(upcard, shoe_probabilities([upcard], num_decks=6))
    assert set(dist) == set(DEALER_OUTCOMES)
    assert sum(dist.values()) == pytest.approx(1)


def test_dealer_with_10_up_rarely_makes_21_because_blackjack_is_ruled_out():
    # Without the no-blackjack condition P(21) would be about 0.11 (mostly the ace hole card).
    dist = dealer_distribution("10", shoe_probabilities(["10"], num_decks=6))
    assert dist[21] == pytest.approx(0.0377, abs=0.002)


# Wizard of Odds, 6 decks, dealer stands on soft 17, after the peek (appendix 2a).
WIZARD_6D_S17 = {
    #       17        18        19        20        21        bust
    "A":  (0.188071, 0.189235, 0.188906, 0.189362, 0.077394, 0.167033),
    "2":  (0.139656, 0.134389, 0.130020, 0.124019, 0.118413, 0.353504),
    "3":  (0.134296, 0.130539, 0.125226, 0.120817, 0.114928, 0.374194),
    "4":  (0.130556, 0.124062, 0.121272, 0.116441, 0.111866, 0.395805),
    "5":  (0.121843, 0.122437, 0.117575, 0.111793, 0.107945, 0.418406),
    "6":  (0.165707, 0.106194, 0.106431, 0.101551, 0.097276, 0.422842),
    "7":  (0.369208, 0.137931, 0.078428, 0.078682, 0.073816, 0.261936),
    "8":  (0.128940, 0.359955, 0.128723, 0.069219, 0.069470, 0.243693),
    "9":  (0.120310, 0.117348, 0.351854, 0.120368, 0.060877, 0.229242),
    "10": (0.121273, 0.121007, 0.121306, 0.368447, 0.037729, 0.230239),
}


@pytest.mark.parametrize("upcard", DEALER_UPCARDS)
def test_dealer_distribution_matches_wizard_of_odds_six_decks(upcard):
    # Our model removes the upcard and then treats the shoe as fixed, so the
    # dealer's own draws don't deplete it. Measured cost: at most 0.0006 per outcome.
    dist = dealer_distribution(upcard, shoe_probabilities([upcard], num_decks=6))
    for outcome, published in zip(DEALER_OUTCOMES, WIZARD_6D_S17[upcard]):
        assert dist[outcome] == pytest.approx(published, abs=0.001), outcome


def test_dealer_6_busts_about_42_percent():
    dist = dealer_distribution("6", shoe_probabilities(["6"], num_decks=6))
    assert dist[BUST] == pytest.approx(0.42, abs=0.005)


# --- player EVs -------------------------------------------------------------------


def test_stand_on_20_infinite_deck_matches_wizard():
    for upcard, published in [("6", 0.704), ("7", 0.7732), ("10", 0.5545), ("A", 0.6555)]:
        evs = action_evs(["10", "10"], upcard, can_double=True, can_split=False, num_decks=INFINITE)
        assert evs["stand"] == pytest.approx(published, abs=0.0005), upcard


# Infinite-deck EV of the basic-strategy action (Wizard of Odds player-expected-return page).
WIZARD_INFINITE = [
    # cards,        upcard, action,  published EV
    (["10", "6"], "10", "hit", -0.5398),
    (["6", "5"], "6", "double", 0.6674),
    (["10", "2"], "2", "hit", -0.2534),
    (["10", "2"], "4", "stand", -0.2111),
    (["A", "7"], "2", "stand", 0.1217),
    (["A", "7"], "9", "hit", -0.1007),
    (["5", "4"], "2", "hit", 0.0744),
    (["6", "5"], "A", "hit", 0.143),
    (["10", "6"], "7", "hit", -0.4148),
    (["10", "6"], "6", "stand", -0.1537),
]


@pytest.mark.parametrize("cards, upcard, action, published", WIZARD_INFINITE)
def test_infinite_deck_evs_match_wizard_of_odds(cards, upcard, action, published):
    evs = action_evs(cards, upcard, can_double=True, can_split=False, num_decks=INFINITE)
    assert evs[action] == pytest.approx(published, abs=0.0005)
    assert best_action(evs) == action


def test_16_vs_10_hit_and_stand_are_a_close_call():
    evs = action_evs(["10", "6"], "10", can_double=True, can_split=False, num_decks=INFINITE)
    assert evs["stand"] == pytest.approx(-0.5404, abs=0.0005)
    assert abs(evs["hit"] - evs["stand"]) < 0.01


def test_split_8s_vs_10_close_to_wizard_even_without_resplitting():
    # Wizard allows resplitting (-0.4803); we allow one split, which is a bit worse.
    evs = action_evs(["8", "8"], "10", can_double=True, can_split=True, num_decks=INFINITE)
    assert evs["split"] == pytest.approx(-0.4803, abs=0.02)
    assert evs["split"] <= -0.4803 + 0.001


def test_only_legal_actions_are_returned():
    evs = action_evs(["10", "3", "2"], "7", can_double=False, can_split=False)
    assert set(evs) == {"hit", "stand"}
    evs = action_evs(["8", "8"], "7", can_double=True, can_split=True)
    assert set(evs) == {"hit", "stand", "double", "split"}


def test_double_is_twice_one_card_then_stand():
    # Doubling hard 20 is worse than standing on it, and can lose up to 2 units.
    evs = action_evs(["10", "10"], "6", can_double=True, can_split=False)
    assert evs["double"] < evs["stand"]
    assert -2 <= evs["double"] <= 2


@pytest.mark.parametrize("upcard", DEALER_UPCARDS)
def test_hitting_hard_20_is_a_large_mistake(upcard):
    evs = action_evs(["10", "Q"], upcard, can_double=True, can_split=False)
    assert evs["stand"] - evs["hit"] > 0.5


def test_split_aces_get_one_card_each():
    # With one card each, split aces vs 6 is well positive but below 2 x 0.5.
    evs = action_evs(["A", "A"], "6", can_double=True, can_split=True)
    assert 0.3 < evs["split"] < 1.0
    assert best_action(evs) == "split"


def test_six_deck_and_infinite_deck_are_close():
    six = action_evs(["10", "6"], "10", can_double=True, can_split=False, num_decks=6)
    inf = action_evs(["10", "6"], "10", can_double=True, can_split=False, num_decks=INFINITE)
    for action in six:
        assert six[action] == pytest.approx(inf[action], abs=0.02)
        assert not math.isclose(six[action], inf[action])  # card removal does change it


# --- validation against the basic strategy chart ------------------------------------

RANKS = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10"]


def chart_action(cards, upcard, legal):
    total, soft = hand_total(cards)
    state = DecisionState(tuple(cards), total, soft, "split" in legal, upcard, legal, 0, len(cards), False)
    return best_legal_action(state)


def test_best_ev_action_matches_the_chart_for_every_two_card_hand():
    """All 540 two-card hands x upcards (every chart cell, every composition), 6 decks."""
    mismatches = []
    for a, b in itertools.combinations_with_replacement(RANKS, 2):
        if hand_total([a, b])[0] == 21:
            continue  # blackjack: no decision
        can_split = a == b
        legal = ("hit", "stand", "double") + (("split",) if can_split else ())
        for upcard in DEALER_UPCARDS:
            evs = action_evs([a, b], upcard, can_double=True, can_split=can_split)
            if best_action(evs) != chart_action([a, b], upcard, legal):
                mismatches.append(((a, b), upcard))
    assert mismatches == []


def test_three_and_four_card_hands_differ_from_the_chart_only_in_known_close_calls():
    """Composition-dependent exceptions: multi-card 16 vs 10 and a few soft 18 vs A stand."""
    cells_with_mismatches = set()
    biggest_gap = 0.0
    for n in (3, 4):
        for cards in itertools.combinations_with_replacement(RANKS, n):
            total, soft = hand_total(list(cards))
            if total >= 21:
                continue
            for upcard in DEALER_UPCARDS:
                evs = action_evs(list(cards), upcard, can_double=False, can_split=False)
                chart = chart_action(list(cards), upcard, ("hit", "stand"))
                best = best_action(evs)
                if best != chart:
                    cells_with_mismatches.add((f"{'soft' if soft else 'hard'} {total}", upcard, best))
                    biggest_gap = max(biggest_gap, evs[best] - evs[chart])
    assert cells_with_mismatches == {("hard 16", "10", "stand"), ("soft 18", "A", "stand")}
    assert biggest_gap < 0.012


def exact_basic_strategy_return() -> float:
    """Exact enumeration of every first deal (with blackjacks) under the chart."""
    full = shoe_probabilities([])
    total_ev = 0.0
    for a in RANKS:
        for upcard in RANKS:
            for b in RANKS:
                p_deal = (
                    full[card_points(a)]
                    * shoe_probabilities([a])[card_points(upcard)]
                    * shoe_probabilities([a, upcard])[card_points(b)]
                )
                hole = shoe_probabilities([a, upcard, b])
                p_dealer_bj = {"10": hole[1], "A": hole[10]}.get(upcard, 0.0)
                if hand_total([a, b])[0] == 21:
                    ev = (1 - p_dealer_bj) * 1.5
                else:
                    can_split = card_points(a) == card_points(b)
                    evs = action_evs([a, b], upcard, can_double=True, can_split=can_split)
                    ev = -p_dealer_bj + (1 - p_dealer_bj) * evs[chart_action([a, b], upcard, tuple(evs))]
                total_ev += p_deal * ev
    return total_ev


def test_basic_strategy_house_edge_matches_the_simulation():
    """The 3,000,000-hand basic-strategy simulation (NOTES_FOR_PAPER.md) gave
    -0.425% per hand, 95% CI -0.555% to -0.296%.
    """
    assert -0.00555 < exact_basic_strategy_return() < -0.00296
