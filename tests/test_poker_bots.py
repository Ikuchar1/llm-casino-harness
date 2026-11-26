"""Tests for the leak bots: each bot's one habit on hand-built decision states, then whole matches.

Hand-built states carry only the menu items a test needs. Amounts are chips to call,
or the raise-to total for raises.
"""

from poker.bots import BOTS, make_bot
from poker.engine import Action, DecisionState, MenuItem


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
