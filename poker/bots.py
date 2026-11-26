"""The leak bots (docs/poker-plan.md, decisions 3 and 9).

Each bot is a pure function of the DecisionState, with no hidden randomness, so
duplicate dealing deals both seats the same spots. Bots set `bot_sizing = True`, so
the engine adds the bot-only sizes to their menu: one fixed bet size, 2/3 pot
(already raised to the min raise when 2/3 pot is below it), plus the min raise.
"""

import hashlib
import random
from typing import Optional

from poker.cards import RANKS
from poker.engine import CALL, CHECK, FOLD, MIN_RAISE, RAISE_TWO_THIRDS_POT, DecisionState
from poker.hands import TRIPS, TWO_PAIR, category, equity_vs_random


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


RAISE_CAP = 3
_CALM_ACTIONS = (FOLD, CHECK, CALL)


def _raises_this_street(state: DecisionState) -> int:
    """Every bet or raise so far on this street, by either player (blinds not counted)."""
    return sum(1 for action in state.history if action.street == state.street and action.action not in _CALM_ACTIONS)


class Rock(_Bot):
    """Plays only premium hands preflop and only top pair or better after the flop."""

    name = "rock"

    def decide(self, state: DecisionState) -> Optional[str]:
        strong = _has_top_pair_or_better(state) if state.board else _is_premium(state.hole_cards)
        return _bet_or_call(state) if strong else _check_or_fold(state)


# Preflop premium range: TT+ and AQ+ (AQs, AQo, AKs, AKo).
_PREMIUM_PAIR_MIN = "T"
_PREMIUM_ACE_KICKERS = ("Q", "K")


def _is_premium(hole_cards: tuple[str, ...]) -> bool:
    high, low = sorted((card[0] for card in hole_cards), key=RANKS.index, reverse=True)
    if high == low:
        return RANKS.index(high) >= RANKS.index(_PREMIUM_PAIR_MIN)
    return high == "A" and low in _PREMIUM_ACE_KICKERS


def _has_top_pair_or_better(state: DecisionState) -> bool:
    """One hole card pairs the highest board card, a pocket pair above the board, trips or
    better that beats what the board alone makes, or two pair with both pairs made by the
    hole cards. A lower pair on a paired board (JJ on A-A-5, x4 on 9-9-4) does not count.
    """
    board = {RANKS.index(card[0]) for card in state.board}
    top = max(board)
    hole = [RANKS.index(card[0]) for card in state.hole_cards]
    if top in hole or (hole[0] == hole[1] and hole[0] > top):
        return True
    made = category([*state.hole_cards, *state.board])
    if made >= TRIPS:
        return made > category(list(state.board))
    return made == TWO_PAIR and hole[0] != hole[1] and all(rank in board for rank in hole)


class Control(_Bot):
    """The no-leak control: plain equity-threshold play with no single habit (not GTO).

    Equity is Monte Carlo against a random hand, seeded from a hash of the cards so the
    same spot always gets the same answer. Raises 2/3 pot above RAISE_EQUITY, calls with
    the pot odds, else checks or folds. When checked to, the same hash also picks about
    BLUFF_SHARE of spots to bet 2/3 pot regardless.
    """

    name = "control"

    def decide(self, state: DecisionState) -> Optional[str]:
        equity = equity_vs_random(list(state.hole_cards), list(state.board), EQUITY_SAMPLES, _card_rng(state))
        if equity > RAISE_EQUITY:
            return _bet_or_call(state)
        if not state.to_call and _is_bluff_spot(state):
            return _bet_or_call(state)
        if equity >= _pot_odds(state):
            return _check_or_call(state)
        return _check_or_fold(state)


EQUITY_SAMPLES = 500  # about 6 ms a decision
RAISE_EQUITY = 0.65
BLUFF_SHARE = 0.05


def _card_digest(state: DecisionState) -> bytes:
    """A stable hash of the hole cards and board (Python's hash() changes between runs)."""
    cards = ",".join(sorted(state.hole_cards)) + "|" + ",".join(state.board)
    return hashlib.sha256(cards.encode()).digest()


def _card_rng(state: DecisionState) -> random.Random:
    return random.Random(int.from_bytes(_card_digest(state)[:8], "big"))


def _is_bluff_spot(state: DecisionState) -> bool:
    """About BLUFF_SHARE of card spots, from hash bytes the equity seed doesn't use."""
    return int.from_bytes(_card_digest(state)[8:16], "big") / 2**64 < BLUFF_SHARE


def _pot_odds(state: DecisionState) -> float:
    """The share of the final pot this call pays for: to_call / (pot + to_call)."""
    return state.to_call / (state.pot + state.to_call)


def _can_raise(state: DecisionState) -> bool:
    return any(item.action == MIN_RAISE for item in state.menu)


def _check_or_call(state: DecisionState) -> str:
    return CALL if state.to_call else CHECK


def _bet_or_call(state: DecisionState) -> str:
    """Bet or raise the fixed 2/3 pot, or check or call when raising is not legal."""
    return RAISE_TWO_THIRDS_POT if _can_raise(state) else _check_or_call(state)


def _check_or_fold(state: DecisionState) -> str:
    return FOLD if state.to_call else CHECK


BOTS = {bot.name: bot for bot in (CallingStation, Maniac, Rock, Control)}


def make_bot(name: str) -> _Bot:
    """A fresh bot by its registry name, e.g. make_bot("rock")."""
    return BOTS[name]()
