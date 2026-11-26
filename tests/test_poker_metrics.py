"""Tests for the poker metrics (analysis/poker_metrics.py) on hand-built rows."""

import pytest

from analysis import poker_metrics as pm

RAISES = [{"action": "raise_half_pot", "amount": 6}, {"action": "raise_pot", "amount": 12}, {"action": "all_in", "amount": 200}]
CHECK_MENU = [{"action": "check", "amount": 0}, *RAISES]
FACING_MENU = [{"action": "fold", "amount": 0}, {"action": "call", "amount": 4}, *RAISES]

# Hole cards and boards with a clear equity vs random (checked with equity_vs_random).
AIR = (["7c", "2d"], ["As", "Ks", "Qs", "Js", "3h"])  # about 0.05
NUTS = (["Ah", "Ad"], ["As", "Ac", "7d", "2h", "9s"])  # 1.0
TOP_PAIR_FLOP = (["Kh", "9d"], ["Ks", "8c", "4d"])  # about 0.83


def decision(cards=AIR, action="check", street=None, to_call=0, player="model", hand_number=0, seat="button",
             history=(), menu=None, **extra):
    hole, board = cards
    if street is None:
        street = {0: "preflop", 3: "flop", 4: "turn", 5: "river"}[len(board)]
    if menu is None:
        menu = FACING_MENU if to_call else CHECK_MENU
    return {"hand_number": hand_number, "player": player, "seat": seat, "is_button": seat == "button",
            "street": street, "hole_cards": hole, "board": board, "to_call": to_call, "history": list(history),
            "menu": menu, "action": action, "fallback": False, "parse_status": None, **extra}


def test_bluff_rate_is_the_share_of_the_models_postflop_bets_made_with_under_30_percent_equity():
    rows = [
        decision(AIR, "raise_half_pot"),
        decision(NUTS, "raise_pot"),
        decision(TOP_PAIR_FLOP, "all_in"),
        decision(AIR, "check"),  # not a bet: outside the subset
        decision(AIR, "raise_pot", player="bot"),  # the bot's: outside the subset
        decision((["7c", "2d"], []), "raise_pot", street="preflop"),  # preflop: outside the subset
    ]

    rate = pm.bluff_rate(rows)

    assert (rate.k, rate.n) == (1, 3)


def test_value_bet_rate_is_the_share_of_strong_postflop_spots_where_the_model_bet_or_raised():
    no_raise = [{"action": "fold", "amount": 0}, {"action": "call", "amount": 4}]
    rows = [
        decision(NUTS, "raise_pot"),
        decision(TOP_PAIR_FLOP, "check"),
        decision(TOP_PAIR_FLOP, "call", to_call=4),
        decision(NUTS, "call", to_call=4, menu=no_raise),  # could not raise: outside the subset
        decision(AIR, "check"),  # weak: outside the subset
        decision(NUTS, "raise_pot", player="bot"),
    ]

    rate = pm.value_bet_rate(rows)

    assert (rate.k, rate.n) == (1, 3)


def test_fold_to_bet_rate_is_the_share_of_postflop_bets_faced_that_the_model_folded():
    rows = [
        decision(AIR, "fold", to_call=4),
        decision(TOP_PAIR_FLOP, "call", to_call=4),
        decision(NUTS, "raise_pot", to_call=4),
        decision(AIR, "check"),  # no bet to face: outside the subset
        decision((["7c", "2d"], []), "fold", to_call=2),  # preflop: outside the subset
        decision(AIR, "fold", to_call=4, player="bot"),
    ]

    rate = pm.fold_to_bet_rate(rows)

    assert (rate.k, rate.n) == (1, 3)


RIVER_BOARD = ["Ks", "Tc", "8d", "2h", "3s"]
MEDIUM_LOW = (["Ad", "Qh"], RIVER_BOARD)  # about 0.45
MEDIUM_HIGH = (["3d", "7h"], RIVER_BOARD)  # about 0.56


def test_call_down_rate_is_the_share_of_river_bets_faced_with_a_medium_hand_that_the_model_did_not_fold():
    rows = [
        decision(MEDIUM_LOW, "call", to_call=4),
        decision(MEDIUM_HIGH, "fold", to_call=4),
        decision(MEDIUM_HIGH, "raise_pot", to_call=4),  # a raise also continues
        decision(NUTS, "call", to_call=4),  # strong: outside the subset
        decision(AIR, "fold", to_call=4),  # weak: outside the subset
        decision(MEDIUM_LOW, "check"),  # no bet to face: outside the subset
        decision((["Ad", "Qh"], RIVER_BOARD[:3]), "fold", to_call=4),  # the flop: outside the subset
    ]

    rate = pm.call_down_rate(rows)

    assert (rate.k, rate.n) == (2, 3)


PREFLOP = (["7c", "2d"], [])
LIMP = {"street": "preflop", "seat": "button", "action": "call", "amount": 1}
OPEN = {"street": "preflop", "seat": "button", "action": "raise_two_thirds_pot", "amount": 6}


def test_preflop_open_rate_is_the_share_of_unraised_preflop_spots_where_the_model_raised():
    rows = [
        decision(PREFLOP, "raise_pot", to_call=1),  # button, first to act
        decision(PREFLOP, "fold", to_call=1),  # button, first to act
        decision(PREFLOP, "raise_pot", seat="big_blind", history=[LIMP]),  # big blind after a limp
        decision(PREFLOP, "call", to_call=4, seat="big_blind", history=[OPEN]),  # facing a raise: outside
        decision(PREFLOP, "raise_pot", to_call=1, player="bot"),
        decision(TOP_PAIR_FLOP, "raise_pot"),  # postflop: outside the subset
    ]

    rate = pm.preflop_open_rate(rows)

    assert (rate.k, rate.n) == (2, 3)


def test_each_bot_gets_its_own_habit_metrics_with_the_direction_an_exploit_moves_them():
    rows = [decision(AIR, "raise_half_pot"), decision(AIR, "fold", to_call=4), decision(PREFLOP, "raise_pot", to_call=1)]

    station = pm.habit_metrics(rows, "calling_station")
    maniac = pm.habit_metrics(rows, "maniac")
    rock = pm.habit_metrics(rows, "rock")
    control = pm.habit_metrics(rows, "control")

    assert {name: habit.target for name, habit in station.items()} == {"bluff_rate": "down", "value_bet_rate": "up"}
    assert {name: habit.target for name, habit in maniac.items()} == {"fold_to_bet_rate": "down", "call_down_rate": "up"}
    assert {name: habit.target for name, habit in rock.items()} == {"preflop_open_rate": "up", "fold_to_bet_rate": "up"}
    assert set(control) == {"bluff_rate", "value_bet_rate", "fold_to_bet_rate", "call_down_rate", "preflop_open_rate"}
    assert all(habit.target is None for habit in control.values())  # descriptive: no exploit target
    assert (station["bluff_rate"].rate.k, station["bluff_rate"].rate.n) == (1, 1)
    assert (rock["fold_to_bet_rate"].rate.k, rock["fold_to_bet_rate"].rate.n) == (1, 1)
