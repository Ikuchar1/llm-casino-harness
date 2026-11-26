"""The leak bots (docs/poker-plan.md, decisions 3 and 9).

Each bot is a pure function of the DecisionState, with no hidden randomness, so
duplicate dealing deals both seats the same spots. Bots set `bot_sizing = True`, so
the engine adds the bot-only sizes to their menu: one fixed bet size, 2/3 pot
(already raised to the min raise when 2/3 pot is below it), plus the min raise.
"""

from typing import Optional

from poker.cards import RANKS
from poker.engine import CALL, CHECK, FOLD, MIN_RAISE, RAISE_TWO_THIRDS_POT, DecisionState


class _Bot:
    name = ""
    bot_sizing = True

    def decide(self, state: DecisionState) -> Optional[str]:
        raise NotImplementedError


class CallingStation(_Bot):
    """Never folds, never raises: always checks or calls, all-ins included."""

    name = "calling_station"

    def decide(self, state: DecisionState) -> Optional[str]:
        return _check_or_call(state)


class Maniac(_Bot):
    """Always bets or raises when it can, and never folds.

    Bets 2/3 pot, or min-raises when facing a bet (the big blind counts as one). Once
    the street has seen RAISE_CAP bets and raises from either player, it only calls.
    """

    name = "maniac"

    def decide(self, state: DecisionState) -> Optional[str]:
        if not _can_raise(state) or _raises_this_street(state) >= RAISE_CAP:
            return _check_or_call(state)
        return MIN_RAISE if state.to_call else RAISE_TWO_THIRDS_POT


class Rock(_Bot):
    """Plays only premium hands preflop and only top pair or better after the flop."""

    name = "rock"

    def decide(self, state: DecisionState) -> Optional[str]:
        if _is_premium(state.hole_cards):
            return _bet_or_call(state)
        return _check_or_fold(state)


# Preflop premium range: TT+ and AQ+ (AQs, AQo, AKs, AKo).
_PREMIUM_PAIR_MIN = "T"
_PREMIUM_ACE_KICKERS = ("Q", "K")


def _is_premium(hole_cards: tuple[str, ...]) -> bool:
    high, low = sorted((card[0] for card in hole_cards), key=RANKS.index, reverse=True)
    if high == low:
        return RANKS.index(high) >= RANKS.index(_PREMIUM_PAIR_MIN)
    return high == "A" and low in _PREMIUM_ACE_KICKERS


RAISE_CAP = 3
_CALM_ACTIONS = (FOLD, CHECK, CALL)


def _raises_this_street(state: DecisionState) -> int:
    """Every bet or raise so far on this street, by either player (blinds not counted)."""
    return sum(1 for action in state.history if action.street == state.street and action.action not in _CALM_ACTIONS)


def _can_raise(state: DecisionState) -> bool:
    return any(item.action == MIN_RAISE for item in state.menu)


def _check_or_call(state: DecisionState) -> str:
    return CALL if state.to_call else CHECK


def _bet_or_call(state: DecisionState) -> str:
    """Bet or raise the fixed 2/3 pot, or check or call when raising is not legal."""
    return RAISE_TWO_THIRDS_POT if _can_raise(state) else _check_or_call(state)


def _check_or_fold(state: DecisionState) -> str:
    return FOLD if state.to_call else CHECK


BOTS = {bot.name: bot for bot in (CallingStation, Maniac, Rock)}


def make_bot(name: str) -> _Bot:
    """A fresh bot by its registry name, e.g. make_bot("rock")."""
    return BOTS[name]()
