"""Tests for the poker strategy tool (poker/preflop_chart.py): a fixed heads-up preflop chart
by hand class and spot, and the line the full-tools prompt shows.

Hand-built states carry only what the chart reads: cards, seat, street, history and menu
(a raise is on the menu unless can_raise=False).
"""

from poker.engine import Action, DecisionState, MenuItem
from poker.cards import RANKS
from poker.preflop_chart import CHART, CHART_HEADER, chart_lines, chart_play, expand_range, hand_class


def state(hole_cards=("Ah", "Kd"), is_button=True, history=(), board=(), to_call=1, can_raise=True):
    street = {0: "preflop", 3: "flop", 4: "turn", 5: "river"}[len(board)]
    menu = (MenuItem("fold"), MenuItem("call", to_call)) if to_call else (MenuItem("check"),)
    if can_raise:
        menu += (MenuItem("raise_pot", 12), MenuItem("all_in", 200))
    return DecisionState(
        seat="button" if is_button else "big_blind", hole_cards=tuple(hole_cards), board=tuple(board),
        street=street, pot=3, stack=199, opponent_stack=198, to_call=to_call, is_button=is_button,
        history=tuple(history), menu=menu,
    )


OPEN = Action("preflop", "button", "raise_half_pot", 4)


def test_hole_cards_become_a_hand_class_high_card_first():
    assert hand_class(("Kh", "Ah")) == "AKs"
    assert hand_class(("2c", "Td")) == "T2o"
    assert hand_class(("7c", "7d")) == "77"


def test_range_notation_expands_plus_and_dash_the_standard_way():
    assert expand_range("TT+") == {"TT", "JJ", "QQ", "KK", "AA"}
    assert expand_range("22-44") == {"22", "33", "44"}
    assert expand_range("K9o+") == {"K9o", "KTo", "KJo", "KQo"}
    assert expand_range("A2s+, QJs") == {f"A{rank}s" for rank in "23456789TJQK"} | {"QJs"}


def test_on_the_button_with_no_raise_yet_the_chart_raises_or_folds_and_never_limps():
    assert chart_play(state(("Ah", "Kd"))) == "raise"
    assert chart_play(state(("7c", "2d"))) == "fold"


def test_in_the_big_blind_facing_one_raise_the_chart_re_raises_premiums_defends_wide_and_folds_trash():
    facing = dict(is_button=False, history=(OPEN,), to_call=2)
    assert chart_play(state(("Qs", "Qd"), **facing)) == "raise"
    assert chart_play(state(("9s", "6s"), **facing)) == "call"
    assert chart_play(state(("8c", "3d"), **facing)) == "fold"


def test_in_the_big_blind_after_a_limp_the_chart_raises_strong_hands_and_checks_the_rest_never_folding():
    limped = dict(is_button=False, history=(Action("preflop", "button", "call", 1),), to_call=0)
    assert chart_play(state(("As", "Td"), **limped)) == "raise"
    assert chart_play(state(("7c", "2d"), **limped)) == "check"


def test_facing_a_re_raise_the_chart_continues_only_with_strong_hands():
    three_bet = dict(history=(OPEN, Action("preflop", "big_blind", "raise_pot", 12)), to_call=8)
    assert chart_play(state(("Ks", "Kd"), **three_bet)) == "raise"
    assert chart_play(state(("8s", "8d"), **three_bet)) == "call"
    assert chart_play(state(("Kh", "9d"), **three_bet)) == "fold"


def test_after_the_flop_the_chart_has_no_play_and_when_no_raise_is_legal_its_raise_becomes_a_call():
    assert chart_play(state(board=("2c", "7d", "9h"), to_call=0)) is None
    facing_all_in = state(("As", "Ad"), is_button=False, history=(Action("preflop", "button", "all_in", 200),),
                          to_call=198, can_raise=False)
    assert chart_play(facing_all_in) == "call"


def test_the_chart_block_names_the_hand_class_the_spot_and_the_play_and_is_empty_after_the_flop():
    assert chart_lines(state(("Ah", "Kd"))) == [
        CHART_HEADER,
        "- Your hand: AKo. Spot: on the button, nobody has raised yet. Chart play: raise (any raise size on the menu).",
    ]
    assert chart_lines(state(("8c", "3d"), is_button=False, history=(OPEN,), to_call=2))[1] == (
        "- Your hand: 83o. Spot: facing one raise. Chart play: fold."
    )
    assert chart_lines(state(board=("2c", "7d", "9h"), to_call=0)) == []


def _combos(hand):
    return 6 if len(hand) == 2 else 4 if hand.endswith("s") else 12


def test_the_chart_names_only_real_hand_classes_and_opens_about_60_percent_of_hands_on_the_button():
    every_class = {hand_class((first + "c", second + ("c" if suited else "d")))
                   for first in RANKS for second in RANKS for suited in (True, False)
                   if first != second or not suited}
    assert len(every_class) == 169
    for plays in CHART.values():
        for _, notation in plays:
            assert expand_range(notation) <= every_class if notation else True, notation
    opened = sum(_combos(hand) for hand in expand_range(CHART["open"][0][1]))
    assert 0.55 < opened / 1326 < 0.70
