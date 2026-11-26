"""Tests for the poker reply parser (poker/parser.py)."""

from poker.engine import MenuItem
from poker.parser import parse_choice

FACING_A_BET = (MenuItem("fold"), MenuItem("call", 6), MenuItem("raise_half_pot", 18),
                MenuItem("raise_pot", 30), MenuItem("all_in", 194))
NO_BET = (MenuItem("check"), MenuItem("raise_half_pot", 6), MenuItem("raise_pot", 12), MenuItem("all_in", 194))


def test_a_json_answer_is_read_first():
    result = parse_choice('I have a flush draw. {"action": "raise_pot", "amount": 30}\nACTION: call', FACING_A_BET)

    assert (result.action, result.status, result.method) == ("raise_pot", "ok", "json")


def test_the_last_action_line_is_read_when_there_is_no_json():
    reply = "Folding is too weak here.\n**ACTION:** `Raise_Half_Pot`."

    result = parse_choice(reply, FACING_A_BET)
    assert (result.action, result.status, result.method) == ("raise_half_pot", "ok", "action_line")


def test_action_names_written_with_spaces_or_hyphens_still_count():
    assert parse_choice("ACTION: all-in", FACING_A_BET).action == "all_in"
    assert parse_choice("ACTION - raise pot", FACING_A_BET).action == "raise_pot"


def test_a_menu_number_picks_that_menu_item():
    assert parse_choice("ACTION: 3", FACING_A_BET).action == "raise_half_pot"
    assert parse_choice("ACTION: 4. raise_pot - raise to 30 (pot)", FACING_A_BET).action == "raise_pot"
    assert parse_choice('{"action": 2}', FACING_A_BET).action == "call"


def test_a_menu_number_past_the_end_of_the_menu_is_off_menu():
    result = parse_choice("ACTION: 9", FACING_A_BET)

    assert (result.action, result.status) == (None, "off_menu")


def test_check_or_call_maps_onto_whichever_of_the_two_is_on_the_menu_and_says_so():
    facing = parse_choice("ACTION: check/call", FACING_A_BET)
    no_bet = parse_choice("ACTION: check or call", NO_BET)

    assert (facing.action, facing.status, facing.mapping) == ("call", "mapped", "check/call -> call")
    assert (no_bet.action, no_bet.status, no_bet.mapping) == ("check", "mapped", "check/call -> check")


def test_call_with_nothing_to_call_maps_to_check():
    result = parse_choice("ACTION: call", NO_BET)

    assert (result.action, result.status, result.named, result.mapping) == ("check", "mapped", "call", "call -> check")


def test_without_json_or_an_action_line_a_lone_action_name_on_the_last_line_is_read_loosely():
    result = parse_choice("The opponent never folds, so I value bet.\nraise_pot", FACING_A_BET)

    assert (result.action, result.status, result.method) == ("raise_pot", "ok", "loose")


def test_loosely_the_last_action_name_mentioned_wins():
    result = parse_choice("I could fold here, but with a flush draw I will call.", FACING_A_BET)

    assert (result.action, result.method) == ("call", "loose")


def test_loosely_a_menu_number_counts_only_as_an_option_or_a_bare_number_on_its_own_line():
    assert parse_choice("The pot is 18 and I hold a draw. I pick option 2.", FACING_A_BET).action == "call"
    assert parse_choice("The pot is 18, so I will go with\n2", FACING_A_BET).action == "call"
    assert parse_choice("The pot is 18 chips and I have 9 outs.", FACING_A_BET).status == "unparseable"


def test_garbage_parses_to_none_and_is_marked_unparseable():
    for reply in ("", "I am not sure what to do here.", "ACTION: shrug", '{"move": 7}'):
        result = parse_choice(reply, FACING_A_BET)
        assert (result.action, result.status) == (None, "unparseable"), reply


def test_a_real_action_that_is_not_on_the_menu_parses_to_none_and_is_marked_off_menu():
    check_facing_a_bet = parse_choice("ACTION: check", FACING_A_BET)
    fold_with_no_bet = parse_choice('{"action": "fold"}', NO_BET)

    assert (check_facing_a_bet.action, check_facing_a_bet.status, check_facing_a_bet.named) == (None, "off_menu", "check")
    assert (fold_with_no_bet.action, fold_with_no_bet.status, fold_with_no_bet.named) == (None, "off_menu", "fold")
