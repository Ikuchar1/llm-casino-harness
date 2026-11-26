"""Tests for the leak bots: each bot's one habit on hand-built decision states, then whole matches.

Hand-built states carry only the menu items a test needs. Amounts are chips to call,
or the raise-to total for raises.
"""

import random
import time

from poker.bots import BOTS, make_bot
from poker.cards import make_deck
from poker.engine import Action, DecisionState, MenuItem
from poker.hands import equity_vs_random


def state(
    hole_cards=("7c", "2d"), board=(), street="preflop", pot=3, to_call=1, stack=199, menu=None, history=(),
    is_button=True,
):
    if menu is None:
        menu = facing_bet_menu(to_call) if to_call else checked_to_menu()
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
        history=tuple(history),
        menu=tuple(menu),
    )


def facing_bet_menu(to_call, two_thirds=20, min_raise=12):
    return [
        MenuItem("fold"), MenuItem("call", to_call), MenuItem("raise_half_pot", 15), MenuItem("raise_pot", 25),
        MenuItem("all_in", 200), MenuItem("raise_two_thirds_pot", two_thirds), MenuItem("min_raise", min_raise),
    ]


def checked_to_menu(two_thirds=8, min_raise=2):
    return [
        MenuItem("check"), MenuItem("raise_half_pot", 6), MenuItem("raise_pot", 12), MenuItem("all_in", 200),
        MenuItem("raise_two_thirds_pot", two_thirds), MenuItem("min_raise", min_raise),
    ]


FACING_ALL_IN = [MenuItem("fold"), MenuItem("call", 198)]


# ---------- Calling station ----------


def test_the_calling_station_calls_an_all_in_with_seven_deuce():
    station = make_bot("calling_station")

    assert station.decide(state(hole_cards=("7c", "2d"), to_call=198, menu=FACING_ALL_IN)) == "call"


def test_the_calling_station_checks_when_checked_to_even_with_the_nuts():
    station = make_bot("calling_station")

    assert station.decide(state(hole_cards=("As", "Ks"), board=("Qs", "Js", "Ts"), street="flop", to_call=0)) == "check"


# ---------- Maniac ----------


def test_the_maniac_bets_two_thirds_pot_when_checked_to():
    assert make_bot("maniac").decide(state(board=("Qs", "Js", "2d"), street="flop", to_call=0)) == "raise_two_thirds_pot"


def test_the_maniac_min_raises_when_facing_a_bet():
    facing_a_bet = state(board=("Qs", "Js", "2d"), street="flop", to_call=8, history=[Action("flop", "big_blind", "raise_two_thirds_pot", 8)])

    assert make_bot("maniac").decide(facing_a_bet) == "min_raise"


def test_the_maniac_stops_raising_after_three_raises_on_the_street_and_calls():
    three_raises = [
        Action("flop", "big_blind", "raise_two_thirds_pot", 8),
        Action("flop", "button", "min_raise", 16),
        Action("flop", "big_blind", "raise_pot", 60),
    ]
    capped = state(board=("Qs", "Js", "2d"), street="flop", to_call=44, history=three_raises)

    assert make_bot("maniac").decide(capped) == "call"


def test_the_maniacs_raise_cap_counts_only_this_streets_raises():
    preflop_war = [
        Action("preflop", "button", "min_raise", 4),
        Action("preflop", "big_blind", "min_raise", 6),
        Action("preflop", "button", "raise_pot", 18),
        Action("preflop", "big_blind", "call", 12),
        Action("flop", "big_blind", "raise_two_thirds_pot", 24),
    ]
    flop_bet = state(board=("Qs", "Js", "2d"), street="flop", pot=60, to_call=24, history=preflop_war)

    assert make_bot("maniac").decide(flop_bet) == "min_raise"


def test_the_maniac_calls_an_all_in_because_it_cannot_raise():
    assert make_bot("maniac").decide(state(to_call=198, menu=FACING_ALL_IN)) == "call"


# ---------- Rock ----------


def test_the_rock_folds_ace_jack_offsuit_preflop():
    assert make_bot("rock").decide(state(hole_cards=("Ah", "Jc"), to_call=1)) == "fold"


def test_the_rock_raises_queens_two_thirds_pot_preflop():
    assert make_bot("rock").decide(state(hole_cards=("Qh", "Qc"), to_call=1)) == "raise_two_thirds_pot"


def test_the_rock_checks_trash_in_the_big_blind_when_the_button_limps():
    assert make_bot("rock").decide(state(hole_cards=("9c", "4d"), to_call=0, pot=4, is_button=False)) == "check"


def test_the_rock_folds_middle_pair_to_a_flop_bet():
    middle_pair = state(hole_cards=("Jh", "9c"), board=("Ks", "Jd", "4c"), street="flop", pot=20, to_call=8)

    assert make_bot("rock").decide(middle_pair) == "fold"


def test_the_rock_bets_top_pair_on_the_flop():
    top_pair = state(hole_cards=("Kh", "9c"), board=("Ks", "Jd", "4c"), street="flop", pot=12, to_call=0)

    assert make_bot("rock").decide(top_pair) == "raise_two_thirds_pot"


def test_the_rock_bets_a_pocket_pair_above_the_board():
    overpair = state(hole_cards=("Qh", "Qc"), board=("Js", "8d", "4c"), street="flop", pot=12, to_call=0)

    assert make_bot("rock").decide(overpair) == "raise_two_thirds_pot"


def test_the_rock_raises_a_flop_bet_with_bottom_two_pair_because_it_beats_top_pair():
    two_pair = state(hole_cards=("Jh", "4h"), board=("Ks", "Jd", "4c"), street="flop", pot=20, to_call=8)

    assert make_bot("rock").decide(two_pair) == "raise_two_thirds_pot"


def test_the_rock_folds_when_its_only_pair_is_on_the_board():
    board_pair = state(hole_cards=("9h", "8h"), board=("Ks", "Kd", "4c"), street="flop", pot=20, to_call=8)

    assert make_bot("rock").decide(board_pair) == "fold"


def test_the_rock_bets_a_flush_made_with_a_hole_card():
    flush = state(hole_cards=("9h", "2h"), board=("Kh", "Jh", "4h", "Ac"), street="turn", pot=12, to_call=0)

    assert make_bot("rock").decide(flush) == "raise_two_thirds_pot"


# ---------- Control ----------


def test_the_control_folds_trash_to_a_pot_size_bet():
    trash = state(hole_cards=("7c", "2d"), board=("Ks", "Jd", "4c", "9h"), street="turn", pot=40, to_call=20)

    assert make_bot("control").decide(trash) == "fold"


def test_the_control_raises_the_nuts():
    nuts = state(hole_cards=("As", "Ks"), board=("Qs", "Js", "Ts"), street="flop", pot=20, to_call=8)

    assert make_bot("control").decide(nuts) == "raise_two_thirds_pot"


def test_the_control_calls_a_small_bet_with_a_draw_that_has_the_pot_odds():
    # A gutshot plus two overcards has well over the 1/6 equity a 1/4-pot bet asks for.
    draw = state(hole_cards=("Ah", "Kd"), board=("Qs", "Tc", "4h"), street="flop", pot=25, to_call=5)

    assert make_bot("control").decide(draw) == "call"


def test_the_control_bluffs_about_five_percent_of_spots_checked_to_it_and_only_those():
    # Weak flops only (equity well under the raise line), so every bet is a bluff.
    rng = random.Random(3)
    bets = spots = 0
    bot = make_bot("control")
    for _ in range(400):
        deck = make_deck(rng.randrange(10**9))
        hole, board = deck[:2], deck[2:5]
        if equity_vs_random(hole, board, 200, random.Random(0)) > 0.55:
            continue
        spots += 1
        checked_to = state(hole_cards=hole, board=board, street="flop", pot=12, to_call=0)
        bets += bot.decide(checked_to) == "raise_two_thirds_pot"
        facing = state(hole_cards=hole, board=board, street="flop", pot=36, to_call=24)
        assert bot.decide(facing) != "raise_two_thirds_pot"

    assert 0.02 < bets / spots < 0.09, (bets, spots)


def test_a_control_decision_takes_under_20_ms_on_average():
    spot = state(hole_cards=("Ah", "Kd"), board=("Qs", "Tc", "4h"), street="flop", pot=25, to_call=5)
    bot = make_bot("control")
    started = time.perf_counter()
    for _ in range(20):
        bot.decide(spot)

    assert (time.perf_counter() - started) / 20 < 0.020


# ---------- Every bot ----------


def test_the_registry_names_all_four_bots_and_the_factory_builds_each_one_fresh():
    assert set(BOTS) == {"calling_station", "maniac", "rock", "control"}
    assert all(make_bot(name).name == name for name in BOTS)
    assert make_bot("rock") is not make_bot("rock")


def test_every_bot_gives_the_same_choice_for_the_same_state_even_from_a_fresh_instance():
    spots = [
        state(hole_cards=("Ah", "Kd"), board=("Qs", "Tc", "4h"), street="flop", pot=25, to_call=5),
        state(hole_cards=("8h", "7h"), board=("Qs", "Tc", "4h", "2c"), street="turn", pot=30, to_call=0),
        state(hole_cards=("9c", "9d"), to_call=1),
    ]
    for name in BOTS:
        first, second = make_bot(name), make_bot(name)
        assert [first.decide(spot) for spot in spots] == [second.decide(spot) for spot in spots] == [first.decide(spot) for spot in spots]
