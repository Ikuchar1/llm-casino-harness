"""Tests for the poker decision prompt (poker/prompt.py)."""

from poker.engine import Action, DecisionState, MenuItem
from poker.prompt import (
    FORMAT_INSTRUCTION, NOTES_HEADER, PROMPT_VERSION, build_system_prompt, build_user_prompt, notes_block,
)


def flop_state():
    """The button on the flop facing a 6-chip bet, after raising preflop and being called."""
    return DecisionState(
        seat="button", hole_cards=("Ad", "4d"), board=("Jh", "6s", "4s"), street="flop", pot=18,
        stack=194, opponent_stack=188, to_call=6, is_button=True,
        history=(
            Action("preflop", "button", "raise_pot", 6),
            Action("preflop", "big_blind", "call", 4),
            Action("flop", "big_blind", "raise_half_pot", 6),
        ),
        menu=(MenuItem("fold"), MenuItem("call", 6), MenuItem("raise_half_pot", 18),
              MenuItem("raise_pot", 30), MenuItem("all_in", 194)),
    )


def test_the_system_prompt_states_the_rules_and_the_answer_line():
    system = build_system_prompt()

    assert "heads-up no-limit Texas Hold'em" in system
    assert "1/2" in system and "100 big blinds" in system
    assert "reset" in system
    assert "ACTION: <action name>" in system


def test_the_answer_format_asks_for_the_exact_menu_name_says_bets_use_the_raise_names_and_gives_an_example():
    assert "exact action name" in FORMAT_INSTRUCTION
    assert "raise_half_pot" in FORMAT_INSTRUCTION and "raise_pot" in FORMAT_INSTRUCTION
    assert "never \"bet\"" in FORMAT_INSTRUCTION
    assert "For example: ACTION: raise_half_pot" in FORMAT_INSTRUCTION
    assert build_system_prompt().rstrip().endswith(FORMAT_INSTRUCTION)


def test_the_decision_prompt_shows_the_cards_street_pot_stacks_and_amount_to_call():
    prompt = build_user_prompt(flop_state())

    assert "Your hole cards: Ad 4d (ace of diamonds, four of diamonds)" in prompt
    assert "Board: Jh 6s 4s (jack of hearts, six of spades, four of spades)" in prompt
    assert "Street: flop" in prompt
    assert "Pot: 18 chips" in prompt
    assert "Your stack: 194 chips" in prompt
    assert "Opponent's stack: 188 chips" in prompt
    assert "To call: 6 chips" in prompt
    assert "You are on the button" in prompt


def test_the_menu_is_numbered_and_lists_only_the_legal_actions_with_exact_chip_amounts():
    prompt = build_user_prompt(flop_state())

    menu = prompt[prompt.index("Legal actions:"):].splitlines()[1:]
    assert menu == [
        "1. fold - give up the hand",
        "2. call - put in 6 more chips to match",
        "3. raise_half_pot - your total this street becomes 18 chips (half the pot)",
        "4. raise_pot - your total this street becomes 30 chips (the size of the pot)",
        "5. all_in - your total this street becomes 194 chips (all your chips)",
    ]


def test_with_no_bet_to_face_after_the_flop_the_menu_names_each_item_first_and_offers_no_bare_bet():
    state = flop_state()
    state = DecisionState(**{**state.__dict__, "to_call": 0, "history": state.history[:2],
                             "menu": (MenuItem("check"), MenuItem("raise_half_pot", 6), MenuItem("raise_pot", 12),
                                      MenuItem("all_in", 194))})

    menu = build_user_prompt(state).split("Legal actions:\n")[1].splitlines()
    assert menu == [
        "1. check - put in no more chips",
        "2. raise_half_pot - your total this street becomes 6 chips (half the pot)",
        "3. raise_pot - your total this street becomes 12 chips (the size of the pot)",
        "4. all_in - your total this street becomes 194 chips (all your chips)",
    ]
    assert not any(word in line.split(" - ", 1)[1].split() for line in menu for word in ("bet", "raise"))


def test_a_call_that_uses_all_the_remaining_chips_says_so():
    state = flop_state()
    state = DecisionState(**{**state.__dict__, "stack": 74, "to_call": 74,
                             "menu": (MenuItem("fold"), MenuItem("call", 74))})

    menu = build_user_prompt(state).split("Legal actions:\n")[1].splitlines()
    assert menu == ["1. fold - give up the hand", "2. call - put in 74 more chips to match (all your chips)"]


def test_the_prompt_version_is_poker_v4_since_the_all_in_call_line_changed():
    assert PROMPT_VERSION == "poker-v4"


def test_this_hands_actions_are_told_as_you_and_opponent_by_street():
    prompt = build_user_prompt(flop_state())

    assert "Blinds posted: you 1 (small blind), opponent 2 (big blind)." in prompt
    assert "Preflop: you raise to 6; opponent calls 4." in prompt
    assert "Flop: opponent bets 6." in prompt
    assert "button" not in prompt.split("Actions this hand:")[1].split("Legal actions:")[0]


def test_from_the_big_blind_the_opponent_is_the_button():
    state = flop_state()
    state = DecisionState(**{**state.__dict__, "seat": "big_blind", "is_button": False})

    prompt = build_user_prompt(state)
    assert "Blinds posted: opponent 1 (small blind), you 2 (big blind)." in prompt
    assert "Preflop: opponent raises to 6; you call 4." in prompt
    assert "Flop: you bet 6." in prompt


def test_before_anyone_acts_the_history_says_so():
    state = DecisionState(**{**flop_state().__dict__, "board": (), "street": "preflop", "history": ()})

    assert "Preflop: no actions yet." in build_user_prompt(state)


def test_the_opponent_notes_block_appears_only_when_notes_are_given():
    notes = "never folds to bets | for 9 | against 0 | TENTATIVE"

    without = build_user_prompt(flop_state())
    with_notes = build_user_prompt(flop_state(), notes=notes)

    assert NOTES_HEADER not in without and notes not in without
    assert notes_block(notes) in with_notes
    assert with_notes.replace(notes_block(notes), "", 1) == without


def test_empty_notes_count_as_no_notes():
    assert build_user_prompt(flop_state(), notes="") == build_user_prompt(flop_state())


def test_the_tools_block_sits_before_the_notes_and_the_legal_actions_and_is_the_only_difference():
    from poker.prompt import tools_block

    tools = ["Equity (...):", "- Your equity against a random hand: 55.0%."]
    notes = "never folds to bets | for 9 | against 0 | TENTATIVE"

    without = build_user_prompt(flop_state(), notes=notes)
    with_tools = build_user_prompt(flop_state(), notes=notes, tools=tools)

    assert tools_block(tools) == "Equity (...):\n- Your equity against a random hand: 55.0%.\n\n"
    assert with_tools.index(tools_block(tools)) < with_tools.index(notes_block(notes)) < with_tools.index("Legal actions:")
    assert with_tools.replace(tools_block(tools), "", 1) == without
    assert build_user_prompt(flop_state(), tools=[]) == build_user_prompt(flop_state())
