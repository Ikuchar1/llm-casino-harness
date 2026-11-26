"""Tests for the poker probability tool (poker/equity_info.py): seeded equity against a random
hand, pot odds, and the block of lines the full-tools prompt shows.

Hand-built states carry only the menu items a test needs.
"""

import time

from poker.engine import DecisionState, MenuItem
from poker.equity_info import EQUITY_HEADER, equity_info


def state(hole_cards=("Ah", "Kd"), board=(), street="preflop", pot=3, to_call=1, stack=199, is_button=True):
    menu = (MenuItem("fold"), MenuItem("call", to_call)) if to_call else (MenuItem("check"),)
    return DecisionState(
        seat="button" if is_button else "big_blind",
        hole_cards=tuple(hole_cards),
        board=tuple(board),
        street=street,
        pot=pot,
        stack=stack,
        opponent_stack=stack,
        to_call=to_call,
        is_button=is_button,
        history=(),
        menu=menu,
    )


def test_the_same_cards_always_get_the_same_equity_and_other_cards_get_another_seed():
    first = equity_info(state())
    again = equity_info(state())
    other = equity_info(state(hole_cards=("Ah", "Kc")))
    assert first == again
    assert first.seed != other.seed


def test_pocket_aces_show_about_85_percent_equity_and_one_decision_takes_well_under_a_second():
    started = time.perf_counter()
    info = equity_info(state(hole_cards=("As", "Ah")))
    elapsed = time.perf_counter() - started
    assert abs(info.equity - 0.85) < 0.025
    assert elapsed < 0.25


def test_pot_odds_are_the_call_over_the_pot_after_calling_and_there_are_none_when_checking_is_free():
    assert equity_info(state(pot=6, to_call=4)).pot_odds == 0.4
    assert equity_info(state(pot=4, to_call=0)).pot_odds is None


def test_the_equity_block_says_it_is_against_a_random_hand_and_gives_the_break_even_share_of_a_call():
    info = equity_info(state(pot=6, to_call=4))
    assert info.lines() == [
        EQUITY_HEADER,
        f"- Your equity against a random hand: {100 * info.equity:.1f}%.",
        "- Pot odds: calling 4 chips makes the pot 10 chips, so the call breaks even at 40.0% equity.",
    ]
    assert "random hand" in EQUITY_HEADER


def test_when_checking_is_free_the_equity_block_says_so_instead_of_pot_odds():
    assert equity_info(state(pot=4, to_call=0)).lines()[-1] == "- Nothing to call: checking costs no chips."
