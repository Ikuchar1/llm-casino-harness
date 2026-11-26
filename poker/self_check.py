"""Poker self-evaluation: after the first answer, one generic re-check turn.

The same mechanism as blackjack's (agent/prompt.py, agent/llm_player.py): the
conversation continues with a content-free re-check that names the first action and
nothing else, and the model gives a final answer in the same ACTION line format.
The final answer is the one played and graded.

Below that, option B (flags, recheck_prompt's `warnings`): harness warnings about a
likely mistake, shown in the re-check. Which one the full-tools setup wires is open.
"""

from typing import Optional, Sequence

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


def recheck_prompt(first_action: Optional[str], warnings: Sequence[str] = ()) -> str:
    """The re-check for a first answer (None = the first reply named no menu action).

    With no warnings this is the generic, content-free re-check. `warnings` (option B,
    from flags()) go in a list right after "You chose X.".
    """
    if first_action is None:
        return RECHECK_PROMPT_INVALID
    prompt = RECHECK_PROMPT.format(first_action=first_action)
    if not warnings:
        return prompt
    opening = f"You chose {first_action}. "
    listed = "".join(f"- {warning}\n" for warning in warnings)
    return f"{opening.rstrip()} The harness noticed:\n{listed}" + prompt.removeprefix(opening)


def final_choice(first: Optional[str], second: Optional[str]) -> Optional[str]:
    """The answer played: the re-check's menu action, or the first answer when the re-check named none.

    `first` is what the first reply would have played (its menu action, or the off-menu
    action it named, or None); `second` is the re-check's menu action or None. As in
    blackjack, a bad second reply never throws away a usable first one.
    """
    return second if second is not None else first


# ---------- Option B (not chosen yet): harness flags that make the re-check content-bearing ----------
# Blackjack's re-check is unconditional and content-free (CONTEXT.md, "Self-evaluation").
# These flags are the alternative the poker brief sketched: the harness names a likely
# mistake and the re-check (or only a flagged decision's re-check) shows it.

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
