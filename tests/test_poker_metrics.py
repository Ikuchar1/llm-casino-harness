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


def test_a_habit_rate_carries_the_wilson_interval():
    # Newcombe (1998), example (a): 81/263 has the Wilson 95% interval 0.2553 to 0.3662.
    rows = [decision(AIR, "raise_pot")] * 81 + [decision(NUTS, "raise_pot")] * 182

    rate = pm.bluff_rate(rows)

    assert (rate.k, rate.n) == (81, 263)
    assert (rate.low, rate.high) == (pytest.approx(0.2553, abs=1e-4), pytest.approx(0.3662, abs=1e-4))


def test_the_difference_of_two_independent_rates_has_newcombes_hybrid_score_interval():
    # Newcombe (1998b), example (a): 56/70 - 48/80 = 0.2000, 95% CI 0.0524 to 0.3339.
    diff = pm.rate_difference(pm.Proportion(48, 80), pm.Proportion(56, 70))

    assert diff.difference == pytest.approx(0.2)
    assert (diff.low, diff.high) == (pytest.approx(0.0524, abs=1e-4), pytest.approx(0.3339, abs=1e-4))


def test_trend_windows_are_the_first_100_and_last_500_hands_scaled_down_for_a_short_match():
    assert pm.trend_windows(1000) == (100, 500)
    assert pm.trend_windows(60) == (10, 50)
    assert pm.trend_windows(60, first_hands=20, last_hands=20) == (20, 20)


def test_the_trend_compares_a_habit_in_the_first_hands_with_the_last_hands():
    # 12 hands, windows of 4 and 4: hands 0-3 bluff every bet, hands 8-11 bluff one in four.
    early = [decision(AIR, "raise_pot", hand_number=h) for h in range(4)]
    middle = [decision(AIR, "raise_pot", hand_number=h) for h in range(4, 8)]  # in neither window
    late = [decision(AIR if h == 8 else NUTS, "raise_pot", hand_number=h) for h in range(8, 12)]

    trends = pm.habit_trends(early + middle + late, "calling_station", n_hands=12, first_hands=4, last_hands=4)

    bluff = trends["bluff_rate"]
    assert (bluff.before.k, bluff.before.n, bluff.after.k, bluff.after.n) == (4, 4, 1, 4)
    assert bluff.difference == pytest.approx(-0.75)
    assert bluff.low < -0.75 < bluff.high


def hand(hand_number, model_chips, seed=None, showdown=False, board=()):
    return {"hand_number": hand_number, "seed": hand_number // 2 if seed is None else seed,
            "chip_delta": {"model": model_chips, "bot": -model_chips}, "showdown": showdown, "board": list(board)}


def test_bb_per_100_is_the_mean_over_seed_pairs_with_a_ci_from_the_pairs_spread():
    # pairs (hands 0+1, 2+3, 4+5) win 2, 0 and -4 chips = 1, 0 and -2 big blinds over 2 hands each,
    # i.e. 50, 0 and -100 bb/100. Hand 6 has no partner yet: left out and counted.
    hands = [hand(0, 4), hand(1, -2), hand(2, 10), hand(3, -10), hand(4, -6), hand(5, 2), hand(6, 50)]

    result = pm.bb_per_100(hands)

    assert result.pair_bb100 == {0: 50.0, 1: 0.0, 2: -100.0}
    assert result.incomplete_pairs == 1
    assert result.mean.n == 3
    assert result.mean.mean == pytest.approx(-50 / 3)
    sd = (((50 + 50 / 3) ** 2 + (50 / 3) ** 2 + (-100 + 50 / 3) ** 2) / 2) ** 0.5
    assert result.mean.half_width == pytest.approx(1.96 * sd / 3 ** 0.5)


def run(name, hands, decisions=(), seeds=(11, 22, 33), bot="calling_station", setup="plain"):
    metadata = {"run_id": name, "model": "qwen2.5:7b", "setup": setup, "bot": bot, "seeds": list(seeds),
                "n_hands": 2 * len(seeds)}
    return pm.Run(name=name, metadata=metadata, decisions=list(decisions), hands=list(hands))


def test_the_paired_comparison_differences_two_runs_seed_pair_by_seed_pair():
    # plain: pairs at 50, 0, -100 bb/100; memory: 100, 100, -50. Differences 50, 100, 50.
    plain = run("plain", [hand(0, 4), hand(1, -2), hand(2, 10), hand(3, -10), hand(4, -6), hand(5, 2)])
    memory = run("memory", [hand(0, 4), hand(1, 0), hand(2, 2), hand(3, 2), hand(4, -2), hand(5, 0)], setup="memory")

    comparison = pm.compare_runs(plain, memory)

    assert comparison.pair_differences == {0: 50.0, 1: 100.0, 2: 50.0}
    assert comparison.difference.mean == pytest.approx(200 / 3)
    assert comparison.difference.half_width == pytest.approx(1.96 * (2500 / 3 / 3) ** 0.5)
    assert 50 <= comparison.bootstrap_low <= comparison.difference.mean <= comparison.bootstrap_high <= 100
    assert comparison.bootstrap_p == 0.0  # every resampled mean is above zero
    assert comparison.unmatched_pairs == 0


def test_runs_dealt_different_seeds_are_refused_for_a_paired_comparison():
    plain = run("plain", [hand(0, 4), hand(1, -2)], seeds=(11,))
    memory = run("memory", [hand(0, 4), hand(1, -2)], seeds=(12,))

    with pytest.raises(pm.PairingError, match="seed"):
        pm.compare_runs(plain, memory)
