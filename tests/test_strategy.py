"""Tests for the basic strategy table and best_legal_action.

Includes the cells that differ between S17 and H17 charts (must be the S17 values).
"""

import pytest

from blackjack.engine import DecisionState
from blackjack.strategy import (
    DEALER_UPCARDS,
    HARD_TOTALS,
    PAIRS,
    SOFT_TOTALS,
    BasicStrategyPlayer,
    best_legal_action,
)

ALL_UPCARDS = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "A"]
FIRST_TWO_CARDS = ("hit", "stand", "double")
WITH_SPLIT = ("hit", "stand", "double", "split")
NO_DOUBLE = ("hit", "stand")


def make_state(cards, upcard, legal=FIRST_TWO_CARDS, from_split=False) -> DecisionState:
    """Build a DecisionState for the given cards; totals come from the real hand_total."""
    from blackjack.cards import hand_total

    total, is_soft = hand_total(list(cards))
    return DecisionState(
        player_cards=tuple(cards),
        total=total,
        is_soft=is_soft,
        is_pair="split" in legal,
        dealer_upcard=upcard,
        legal_actions=tuple(legal),
        hand_index=0,
        num_cards=len(cards),
        from_split=from_split,
    )


# ---------- Table shape ----------


def test_every_row_has_one_cell_per_dealer_upcard():
    assert DEALER_UPCARDS == ALL_UPCARDS
    for table in (HARD_TOTALS, SOFT_TOTALS, PAIRS):
        for row in table.values():
            assert len(row) == 10


def test_table_only_uses_chart_codes():
    allowed = {"H", "S", "Dh", "Ds", "P"}
    for table in (HARD_TOTALS, SOFT_TOTALS, PAIRS):
        for row in table.values():
            assert set(row) <= allowed


def test_split_code_only_appears_in_the_pair_table():
    for table in (HARD_TOTALS, SOFT_TOTALS):
        for row in table.values():
            assert "P" not in row


# ---------- Rule-set-sensitive cells (S17 values) ----------


def test_hard_11_vs_ace_is_hit_under_s17():
    assert best_legal_action(make_state(["6", "5"], "A")) == "hit"


def test_soft_18_vs_2_is_stand_under_s17():
    assert best_legal_action(make_state(["A", "7"], "2")) == "stand"


def test_soft_19_vs_6_is_stand_under_s17():
    assert best_legal_action(make_state(["A", "8"], "6")) == "stand"


# ---------- Other key hard cells ----------


def test_16_vs_10_is_hit_no_surrender():
    assert best_legal_action(make_state(["10", "6"], "10")) == "hit"


@pytest.mark.parametrize("upcard", ["2", "3"])
def test_12_vs_2_and_3_is_hit(upcard):
    assert best_legal_action(make_state(["10", "2"], upcard)) == "hit"


@pytest.mark.parametrize("upcard", ["4", "5", "6"])
def test_12_vs_4_to_6_is_stand(upcard):
    assert best_legal_action(make_state(["10", "2"], upcard)) == "stand"


def test_9_vs_2_is_hit():
    assert best_legal_action(make_state(["5", "4"], "2")) == "hit"


@pytest.mark.parametrize("upcard", ["3", "4", "5", "6"])
def test_9_vs_3_to_6_is_double(upcard):
    assert best_legal_action(make_state(["5", "4"], upcard)) == "double"


@pytest.mark.parametrize("upcard", ["10", "A"])
def test_10_vs_10_and_ace_is_hit(upcard):
    assert best_legal_action(make_state(["6", "4"], upcard)) == "hit"


def test_face_card_upcard_reads_as_ten():
    assert best_legal_action(make_state(["10", "6"], "K")) == "hit"


# ---------- Pairs ----------


@pytest.mark.parametrize("upcard", ALL_UPCARDS)
def test_8_8_always_split(upcard):
    assert best_legal_action(make_state(["8", "8"], upcard, WITH_SPLIT)) == "split"


@pytest.mark.parametrize("upcard", ALL_UPCARDS)
def test_aces_always_split(upcard):
    assert best_legal_action(make_state(["A", "A"], upcard, WITH_SPLIT)) == "split"


@pytest.mark.parametrize("upcard", ALL_UPCARDS)
def test_10_10_never_split(upcard):
    assert best_legal_action(make_state(["K", "Q"], upcard, WITH_SPLIT)) == "stand"


@pytest.mark.parametrize("upcard", ["7", "10", "A"])
def test_9_9_vs_7_10_ace_is_stand(upcard):
    assert best_legal_action(make_state(["9", "9"], upcard, WITH_SPLIT)) == "stand"


@pytest.mark.parametrize("upcard", ["2", "3", "4", "5", "6", "8", "9"])
def test_9_9_split_against_other_upcards(upcard):
    assert best_legal_action(make_state(["9", "9"], upcard, WITH_SPLIT)) == "split"


@pytest.mark.parametrize("upcard", ["5", "6"])
def test_4_4_vs_5_and_6_is_split(upcard):
    assert best_legal_action(make_state(["4", "4"], upcard, WITH_SPLIT)) == "split"


@pytest.mark.parametrize("rank", ["2", "3", "7"])
@pytest.mark.parametrize("upcard", ["2", "3", "4", "5", "6", "7"])
def test_2s_3s_7s_vs_2_to_7_is_split(rank, upcard):
    assert best_legal_action(make_state([rank, rank], upcard, WITH_SPLIT)) == "split"


@pytest.mark.parametrize("upcard", ["2", "3", "4", "5", "6"])
def test_6_6_vs_2_to_6_is_split(upcard):
    assert best_legal_action(make_state(["6", "6"], upcard, WITH_SPLIT)) == "split"


def test_5_5_is_played_as_hard_10():
    assert best_legal_action(make_state(["5", "5"], "9", WITH_SPLIT)) == "double"
    assert best_legal_action(make_state(["5", "5"], "10", WITH_SPLIT)) == "hit"


# ---------- Fallbacks when an action is not legal ----------


def test_double_hit_falls_back_to_hit_when_double_not_legal():
    # Three-card hard 11 vs 6: chart says Dh.
    assert best_legal_action(make_state(["2", "4", "5"], "6", NO_DOUBLE)) == "hit"


def test_double_stand_falls_back_to_stand_when_double_not_legal():
    # Three-card soft 18 vs 4: chart says Ds.
    assert best_legal_action(make_state(["A", "3", "4"], "4", NO_DOUBLE)) == "stand"


def test_double_stand_doubles_when_legal():
    assert best_legal_action(make_state(["A", "7"], "4")) == "double"


def test_unsplittable_8_8_is_played_as_hard_16():
    # After a split, 8,8 cannot be split again; vs 10 that is hard 16 = hit.
    cards = ["8", "8"]
    assert best_legal_action(make_state(cards, "10", FIRST_TWO_CARDS, from_split=True)) == "hit"
    assert best_legal_action(make_state(cards, "6", FIRST_TWO_CARDS, from_split=True)) == "stand"


def test_unsplittable_aces_are_played_as_soft_12():
    assert best_legal_action(make_state(["A", "A"], "6", FIRST_TWO_CARDS, from_split=True)) == "hit"


def test_best_action_is_always_legal_for_every_reachable_two_card_hand():
    ranks = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10"]
    for first in ranks:
        for second in ranks:
            for upcard in ALL_UPCARDS:
                for legal in (FIRST_TWO_CARDS, WITH_SPLIT, NO_DOUBLE):
                    if "split" in legal and first != second:
                        continue
                    state = make_state([first, second], upcard, legal)
                    if state.total == 21:
                        continue
                    assert best_legal_action(state) in legal


def test_basic_strategy_player_uses_best_legal_action():
    state = make_state(["10", "6"], "10")
    assert BasicStrategyPlayer().decide(state) == "hit"
