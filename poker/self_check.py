"""Poker self-evaluation: after the first answer, one generic re-check turn.

The same mechanism as blackjack's (agent/prompt.py, agent/llm_player.py): the
conversation continues with a content-free re-check that names the first action and
nothing else, and the model gives a final answer in the same ACTION line format.
The final answer is the one played and graded.

Below that, flags(): the harness's warnings about a likely mistake in the first answer.
They are a logged-only diagnostic (the "flags" field of a decision row) and are never
shown to the model, so the re-check stays generic, as CONTEXT.md defines self-evaluation.
"""

from typing import Optional

from poker.engine import CALL, CHECK, FOLD, DecisionState
from poker.equity_info import EquityInfo

# How the reply must end, word for word as in the poker system prompt's format instruction.
ACTION_LINE_FORM = (
    "a final line of exactly the form `ACTION: <action name>`, using the exact action name of one item "
    "in the numbered list"
)

# Bump if either text changes; it is recorded in the run metadata and checked on resume.
SELF_CHECK_VERSION = "poker-self-check-v1"
RECHECK_PROMPT = (
    "You chose {first_action}. Before you commit, re-check that choice against your cards, the board, "
    f"the pot and the numbered list. Briefly explain your re-check, then give your final answer as {ACTION_LINE_FORM}."
)
RECHECK_PROMPT_INVALID = (
    "Your reply did not name an action from the numbered list. Re-check your cards, the board, the pot "
    f"and the numbered list. Briefly explain your re-check, then give your final answer as {ACTION_LINE_FORM}."
)


def recheck_prompt(first_action: Optional[str]) -> str:
    """The generic, content-free re-check for a first answer (None = it named nothing the engine applies)."""
    if first_action is None:
        return RECHECK_PROMPT_INVALID
    return RECHECK_PROMPT.format(first_action=first_action)


def final_choice(first: Optional[str], second: Optional[str]) -> Optional[str]:
    """The answer played: the re-check's menu action, or the first answer when the re-check named none.

    `first` is what the first reply would have played (its menu action, or the off-menu
    action it named, or None); `second` is the re-check's usable choice (a menu action or
    an off-menu name the engine still applies, DecisionState.applied_action) or None. As
    in blackjack, a bad second reply never throws away a usable first one.
    """
    return second if second is not None else first


# ---------- Flags: a logged-only diagnostic, never shown to the model ----------
# They count how often the first answer made an obvious mistake, so the analysis can
# tell whether the generic re-check fixes such answers.

# A call is flagged when its equity is this far (absolute share) below the pot odds.
CALL_GAP = 0.10
# A fold facing a bet is flagged at or above this equity against a random hand.
HIGH_EQUITY = 0.70

FREE_FOLD = "You chose fold, but check is on the list and costs no chips."
CALL_BELOW_ODDS = (
    "Your equity against a random hand ({equity}) is far below the {needed} this call needs to break even."
)
HIGH_EQUITY_FOLD = "You are folding with {equity} equity against a random hand."


def flags(state: DecisionState, action: Optional[str], info: EquityInfo) -> list[str]:
    """The harness's warnings about a first answer (empty when nothing looks wrong)."""
    can_check = any(item.action == CHECK for item in state.menu)
    warnings = []
    if action == FOLD and can_check:
        warnings.append(FREE_FOLD)
    if action == CALL and info.pot_odds is not None and info.equity < info.pot_odds - CALL_GAP:
        warnings.append(CALL_BELOW_ODDS.format(equity=_percent(info.equity), needed=_percent(info.pot_odds)))
    if action == FOLD and not can_check and info.equity >= HIGH_EQUITY:
        warnings.append(HIGH_EQUITY_FOLD.format(equity=_percent(info.equity)))
    return warnings


def _percent(share: float) -> str:
    return f"{100 * share:.1f}%"
