"""Poker match metrics, in the priority order of docs/research/poker-eval-methods.md.

1. Per-bot habit metrics over the model's decisions, with Wilson 95% CIs.

Every metric counts only the model's decisions (player == "model"). Equity is
Monte Carlo vs one random hand (poker.hands.equity_vs_random), seeded from a hash of
the cards so the same spot always gets the same number.
"""

import hashlib
import math
import random
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Callable, Optional

from analysis.stats import Proportion
from poker.engine import ALL_IN, FOLD, MIN_RAISE, RAISE_HALF_POT, RAISE_POT, RAISE_TWO_THIRDS_POT
from poker.hands import equity_vs_random

Row = dict[str, Any]

MODEL = "model"
POSTFLOP = ("flop", "turn", "river")
AGGRESSIVE = (RAISE_HALF_POT, RAISE_POT, ALL_IN, RAISE_TWO_THIRDS_POT, MIN_RAISE)

EQUITY_SAMPLES = 500  # Monte Carlo samples per spot, as the control bot uses (about 0.02 standard error)
BLUFF_EQUITY = 0.30  # a bet or raise below this equity vs random is a bluff
VALUE_EQUITY = 0.60  # at or above this equity vs random, a hand is worth a value bet
MEDIUM_EQUITY_LOW = 0.40  # a medium hand (for calling down the maniac's river bet) is in
MEDIUM_EQUITY_HIGH = 0.65  # [MEDIUM_EQUITY_LOW, MEDIUM_EQUITY_HIGH] equity vs random


def equity(row: Row) -> float:
    """The decision's equity vs one random hand (deterministic for the same cards)."""
    return _equity(tuple(sorted(row["hole_cards"])), tuple(row["board"]))


@lru_cache(maxsize=None)
def _equity(hole: tuple[str, ...], board: tuple[str, ...]) -> float:
    digest = hashlib.sha256((",".join(hole) + "|" + ",".join(board)).encode()).digest()
    rng = random.Random(int.from_bytes(digest[:8], "big"))
    return equity_vs_random(list(hole), list(board), EQUITY_SAMPLES, rng)


def _model(rows: list[Row]) -> list[Row]:
    return [row for row in rows if row.get("player") == MODEL]


def _is_aggressive(row: Row) -> bool:
    return row["action"] in AGGRESSIVE


def bluff_rate(rows: list[Row]) -> Proportion:
    """Calling station: of the model's postflop bets and raises, the share made with
    equity < BLUFF_EQUITY. Should go down. Preflop is left out: no two cards are below
    30% vs random before the flop, so preflop raises would only dilute the rate.
    """
    bets = [row for row in _model(rows) if row["street"] in POSTFLOP and _is_aggressive(row)]
    return Proportion(sum(equity(row) < BLUFF_EQUITY for row in bets), len(bets))


def _can_raise(row: Row) -> bool:
    return any(item["action"] in AGGRESSIVE for item in row["menu"])


def value_bet_rate(rows: list[Row]) -> Proportion:
    """Calling station: of the model's postflop decisions with equity >= VALUE_EQUITY and
    a bet or raise on the menu, the share where it bet or raised. Should go up.
    """
    spots = [row for row in _model(rows) if row["street"] in POSTFLOP and _can_raise(row)
             and equity(row) >= VALUE_EQUITY]
    return Proportion(sum(_is_aggressive(row) for row in spots), len(spots))


def fold_to_bet_rate(rows: list[Row]) -> Proportion:
    """Maniac and rock: of the model's postflop decisions facing a bet or raise
    (to_call > 0, which heads-up postflop means the bot bet or raised), the share it
    folded. Should go down vs the maniac and up vs the rock.
    """
    faced = [row for row in _model(rows) if row["street"] in POSTFLOP and row["to_call"] > 0]
    return Proportion(sum(row["action"] == FOLD for row in faced), len(faced))


def call_down_rate(rows: list[Row]) -> Proportion:
    """Maniac: of the model's river decisions facing a bet or raise with a medium hand
    (MEDIUM_EQUITY_LOW <= equity <= MEDIUM_EQUITY_HIGH), the share it did not fold
    (called or raised). Should go up.
    """
    spots = [row for row in _model(rows) if row["street"] == "river" and row["to_call"] > 0
             and MEDIUM_EQUITY_LOW <= equity(row) <= MEDIUM_EQUITY_HIGH]
    return Proportion(sum(row["action"] != FOLD for row in spots), len(spots))


def preflop_open_rate(rows: list[Row]) -> Proportion:
    """Rock: of the model's preflop decisions where nobody has bet or raised yet (the
    button first to act, facing only the big blind, or the big blind after a limp), the
    share where it raised. Should go up (steal more).
    """
    spots = [row for row in _model(rows) if row["street"] == "preflop"
             and not any(action["action"] in AGGRESSIVE for action in row["history"])]
    return Proportion(sum(_is_aggressive(row) for row in spots), len(spots))


HabitFunction = Callable[[list[Row]], Proportion]

HABIT_FUNCTIONS: dict[str, HabitFunction] = {
    "bluff_rate": bluff_rate,
    "value_bet_rate": value_bet_rate,
    "fold_to_bet_rate": fold_to_bet_rate,
    "call_down_rate": call_down_rate,
    "preflop_open_rate": preflop_open_rate,
}

# Per bot: each habit metric and the way a model exploiting the bot moves it.
# The control has no habit to exploit, so it gets every metric with no target.
EXPLOIT_TARGETS: dict[str, dict[str, Optional[str]]] = {
    "calling_station": {"bluff_rate": "down", "value_bet_rate": "up"},
    "maniac": {"fold_to_bet_rate": "down", "call_down_rate": "up"},
    "rock": {"preflop_open_rate": "up", "fold_to_bet_rate": "up"},
    "control": {name: None for name in HABIT_FUNCTIONS},
}


@dataclass(frozen=True)
class Habit:
    """One habit metric: the rate (k/n, Wilson CI) and "up", "down" or None (descriptive)."""

    name: str
    rate: Proportion
    target: Optional[str]


def habit_metrics(rows: list[Row], bot: str) -> dict[str, Habit]:
    """The bot's habit metrics over these rows. An unknown bot gets every metric, descriptive."""
    return {name: Habit(name, HABIT_FUNCTIONS[name](rows), target) for name, target in _targets(bot).items()}


def _targets(bot: str) -> dict[str, Optional[str]]:
    return EXPLOIT_TARGETS.get(bot, EXPLOIT_TARGETS["control"])


@dataclass(frozen=True)
class RateDifference:
    """after.rate - before.rate for two independent rates, with a 95% CI."""

    before: Proportion
    after: Proportion
    low: float
    high: float

    @property
    def difference(self) -> float:
        return self.after.rate - self.before.rate


def rate_difference(before: Proportion, after: Proportion) -> RateDifference:
    """after - before with Newcombe's hybrid score interval for independent proportions
    (Newcombe 1998, method 10): each rate's Wilson interval, combined. nan if either is empty.
    """
    if not before.n or not after.n:
        return RateDifference(before, after, math.nan, math.nan)
    diff = after.rate - before.rate
    low = diff - math.sqrt((after.rate - after.low) ** 2 + (before.high - before.rate) ** 2)
    high = diff + math.sqrt((after.high - after.rate) ** 2 + (before.rate - before.low) ** 2)
    return RateDifference(before, after, low, high)


# 2. Trend within a match -------------------------------------------------------------

FIRST_HANDS = 100  # the early window: hands before memory has much to go on
LAST_HANDS = 500  # the late window of a 1,000-hand match


def trend_windows(n_hands: int, first_hands: int = FIRST_HANDS, last_hands: int = LAST_HANDS) -> tuple[int, int]:
    """(first, last) window sizes in hands. When the two don't fit in n_hands, both
    shrink by the same factor (60 hands -> 10 and 50), so the windows never overlap.
    """
    if first_hands + last_hands <= n_hands:
        return first_hands, last_hands
    scale = n_hands / (first_hands + last_hands)
    first = int(first_hands * scale)
    return first, int(last_hands * scale)


def habit_trends(rows: list[Row], bot: str, n_hands: int, first_hands: int = FIRST_HANDS,
                 last_hands: int = LAST_HANDS) -> dict[str, RateDifference]:
    """Each habit metric in the last window minus the first window (Newcombe CI).

    Hands are numbered 0..n_hands-1; the first window is the lowest hand numbers and
    the last window the highest, sized by trend_windows.
    """
    first, last = trend_windows(n_hands, first_hands, last_hands)
    early = [row for row in rows if row["hand_number"] < first]
    late = [row for row in rows if row["hand_number"] >= n_hands - last]
    return {name: rate_difference(HABIT_FUNCTIONS[name](early), HABIT_FUNCTIONS[name](late))
            for name in _targets(bot)}
