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
        decision(AIR, "fold", to_call=4, player="bot"),
    ]

    rate = pm.fold_to_bet_rate(rows)

    assert (rate.k, rate.n) == (1, 3)


BOT_OPEN = {"street": "preflop", "seat": "button", "action": "raise_two_thirds_pot", "amount": 6}
MODEL_OPEN = {"street": "preflop", "seat": "big_blind", "action": "raise_pot", "amount": 12}
BOT_RERAISE = {"street": "preflop", "seat": "button", "action": "all_in", "amount": 200}


def test_fold_to_bet_rate_counts_a_preflop_bot_raise_the_model_folded_to_but_not_the_big_blind_alone():
    rows = [
        decision(PREFLOP, "fold", to_call=4, seat="big_blind", history=[BOT_OPEN]),  # folds to the bot's raise
        decision(PREFLOP, "call", to_call=4, seat="big_blind", history=[BOT_OPEN]),  # calls the bot's raise
        decision(PREFLOP, "fold", to_call=188, seat="big_blind", history=[BOT_OPEN, MODEL_OPEN, BOT_RERAISE]),
        decision(PREFLOP, "fold", to_call=1, seat="button"),  # facing only the big blind: outside the subset
        decision(PREFLOP, "fold", to_call=4, seat="big_blind", history=[BOT_OPEN], player="bot"),
        decision(AIR, "fold", to_call=4),  # postflop bot bet, folded
        decision(TOP_PAIR_FLOP, "call", to_call=4),  # postflop bot bet, called
    ]

    rate = pm.fold_to_bet_rate(rows)
    preflop, postflop = pm.fold_to_bet_preflop(rows), pm.fold_to_bet_postflop(rows)

    assert (rate.k, rate.n) == (3, 5)
    assert (preflop.k, preflop.n) == (2, 3)
    assert (postflop.k, postflop.n) == (1, 2)


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


def test_the_paired_comparisons_habits_cover_only_the_seed_pairs_complete_in_both_runs():
    # A has all 3 pairs; B was cut after hand 2, so only pair 0 is complete in both.
    full = [hand(h, 0) for h in range(6)]
    a = run("plain", full, [decision(AIR, "raise_pot", hand_number=h) for h in range(6)])
    b = run("memory", full[:3], [decision(NUTS, "raise_pot", hand_number=h) for h in range(3)], setup="memory")

    comparison = pm.compare_runs(a, b)

    assert list(comparison.pair_differences) == [0]
    bluff = comparison.habits["bluff_rate"]
    assert (bluff.before.k, bluff.before.n) == (2, 2)  # A's hands 0 and 1 only
    assert (bluff.after.k, bluff.after.n) == (0, 2)  # B's hand 2 belongs to the incomplete pair 1


def test_runs_dealt_different_seeds_are_refused_for_a_paired_comparison():
    plain = run("plain", [hand(0, 4), hand(1, -2)], seeds=(11,))
    memory = run("memory", [hand(0, 4), hand(1, -2)], seeds=(12,))

    with pytest.raises(pm.PairingError, match="seed"):
        pm.compare_runs(plain, memory)


@pytest.mark.parametrize("key", ["seeds", "bot"])
def test_runs_whose_metadata_both_lack_the_seed_list_or_the_bot_are_refused_for_a_paired_comparison(key):
    plain = run("plain", [hand(0, 4), hand(1, -2)])
    memory = run("memory", [hand(0, 4), hand(1, -2)], setup="memory")
    del plain.metadata[key], memory.metadata[key]

    with pytest.raises(pm.PairingError, match=f"no '{key}'"):
        pm.compare_runs(plain, memory)


FLOP = ["Ks", "8c", "4d"]


def test_the_models_profile_has_vpip_pfr_af_and_wtsd():
    decisions = [
        decision(PREFLOP, "call", to_call=1, hand_number=0),  # limp: voluntary, not a raise
        decision(PREFLOP, "raise_pot", to_call=1, hand_number=1),
        decision(PREFLOP, "fold", to_call=1, hand_number=2),
        decision(PREFLOP, "check", seat="big_blind", hand_number=3, history=[LIMP]),  # free check: not voluntary
        decision(PREFLOP, "raise_pot", to_call=1, hand_number=3, player="bot"),
        decision(TOP_PAIR_FLOP, "raise_pot", hand_number=0),  # postflop: 2 bets/raises, 1 call -> AF 2
        decision(TOP_PAIR_FLOP, "all_in", to_call=4, hand_number=1),
        decision(TOP_PAIR_FLOP, "call", to_call=4, hand_number=3),
        decision(TOP_PAIR_FLOP, "check", hand_number=3),
    ]
    hands = [hand(0, 5, showdown=True, board=FLOP + ["2h", "3s"]), hand(1, 8, board=FLOP), hand(2, -1),
             hand(3, -4, showdown=True, board=FLOP + ["2h", "3s"])]

    profile = pm.player_profile(decisions, hands)

    assert (profile.vpip.k, profile.vpip.n) == (2, 4)
    assert (profile.pfr.k, profile.pfr.n) == (1, 4)
    assert profile.af == pytest.approx(2.0)
    assert (profile.wtsd.k, profile.wtsd.n) == (2, 3)  # hand 2 never saw a flop


def test_the_fallback_rate_counts_the_models_fallbacks_with_a_breakdown_by_parse_status():
    rows = [
        decision(fallback=True, parse_status="unparseable"),
        decision(parse_status="ok"),
        decision(parse_status="ok"),
        decision(parse_status="mapped"),
        decision(fallback=True, parse_status="unparseable"),
        decision(fallback=True, player="bot"),
    ]

    output = pm.output_quality(rows)

    assert (output.fallback.k, output.fallback.n) == (2, 5)
    assert output.parse_status == {"ok": 2, "mapped": 1, "unparseable": 2}


def test_an_off_menu_choice_the_engine_still_applied_is_not_a_fallback():
    rows = [decision(action="all_in", parse_status="off_menu"), decision(fallback=True, parse_status="unparseable")]

    output = pm.output_quality(rows)

    assert (output.fallback.k, output.fallback.n) == (1, 2)
    assert output.parse_status == {"off_menu": 1, "unparseable": 1}


def test_prompt_tokens_per_decision_is_the_mean_over_the_models_logged_counts_and_none_when_never_logged():
    logged = [decision(prompt_tokens=300), decision(prompt_tokens=500), decision(prompt_tokens=None),
              decision(prompt_tokens=9999, player="bot")]

    assert pm.mean_prompt_tokens(logged) == pytest.approx(400)
    assert pm.mean_prompt_tokens([decision(), decision(prompt_tokens=None)]) is None


def check(first_action, final_action, flipped):
    return {"first_action": first_action, "final_action": final_action, "flipped": flipped}


def test_the_self_check_counts_flips_and_first_answers_with_no_menu_action_over_the_re_checked_decisions():
    rows = [
        decision(self_check=check("fold", "call", True)),
        decision(self_check=check("call", "call", False)),
        decision(self_check=check(None, "check", True)),
        decision(fallback=True, parse_status="unparseable", self_check=check(None, None, False)),
        decision(player="bot", self_check=None),
    ]

    result = pm.self_check_summary(rows)

    assert (result.flips.k, result.flips.n) == (2, 4)
    assert (result.first_pass_fallback.k, result.first_pass_fallback.n) == (2, 4)
    assert (result.final_fallback.k, result.final_fallback.n) == (1, 4)
    assert pm.self_check_summary([decision(), decision(self_check=None)]) is None
