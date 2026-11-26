"""Tests for poker self-evaluation (poker/self_check.py): the re-check turn that follows the
first answer, mirroring blackjack's (agent/prompt.recheck_prompt), and the final choice.
"""

from poker.engine import DecisionState, MenuItem
from poker.equity_info import EquityInfo
from poker.prompt import build_system_prompt
from poker.self_check import (
    ACTION_LINE_FORM, CALL_BELOW_ODDS, FREE_FOLD, HIGH_EQUITY_FOLD, RECHECK_PROMPT_INVALID, final_choice, flags,
    recheck_prompt,
)


def test_the_re_check_names_only_the_first_action_and_asks_for_the_same_action_line():
    prompt = recheck_prompt("call")
    assert prompt.startswith("You chose call. Before you commit, re-check that choice")
    assert ACTION_LINE_FORM in prompt and ACTION_LINE_FORM in build_system_prompt()
    assert recheck_prompt(None) == RECHECK_PROMPT_INVALID
    assert RECHECK_PROMPT_INVALID.startswith("Your reply did not name an action from the numbered list.")


def test_the_final_choice_is_the_re_checked_menu_action_or_the_first_answer_when_the_re_check_named_none():
    assert final_choice("call", "fold") == "fold"
    assert final_choice("call", None) == "call"
    assert final_choice(None, None) is None


def _state(to_call, pot=6, menu=None):
    if menu is None:
        menu = (MenuItem("fold"), MenuItem("call", to_call)) if to_call else (MenuItem("check"),)
    return DecisionState(
        seat="button", hole_cards=("7c", "2d"), board=(), street="preflop", pot=pot, stack=199,
        opponent_stack=199, to_call=to_call, is_button=True, history=(), menu=menu,
    )


def _info(equity, state):
    pot_odds = state.to_call / (state.pot + state.to_call) if state.to_call else None
    return EquityInfo(equity=equity, seed=0, samples=1, pot_odds=pot_odds, to_call=state.to_call,
                      pot_after_call=state.pot + state.to_call)


def test_the_harness_flags_a_free_fold_a_call_far_below_pot_odds_and_a_fold_with_very_high_equity():
    free = _state(0, menu=(MenuItem("fold"), MenuItem("check")))
    assert flags(free, "fold", _info(0.3, free)) == [FREE_FOLD]
    facing = _state(4)  # the call needs 40% equity
    assert flags(facing, "call", _info(0.25, facing)) == [CALL_BELOW_ODDS.format(equity="25.0%", needed="40.0%")]
    assert flags(facing, "call", _info(0.35, facing)) == []
    assert flags(facing, "fold", _info(0.75, facing)) == [HIGH_EQUITY_FOLD.format(equity="75.0%")]
    assert flags(facing, "fold", _info(0.5, facing)) == []

