"""Poker match metrics, in the priority order of docs/research/poker-eval-methods.md.

1. Per-bot habit metrics over the model's decisions, with Wilson 95% CIs
   (EXPLOIT_TARGETS says which ones each bot gets and which way an exploit moves them).
2. The trend within a match: each habit in the last window minus the first window,
   with Newcombe's hybrid score interval.
3. bb/100 over duplicate seed pairs (pair = hand_number // 2), mean ± 1.96 SE over
   pairs, and a paired comparison of two runs dealt the same seeds.
4. VPIP, PFR, AF and WTSD (descriptive).
5. Fallback rate, with a breakdown by parse_status.
6. Mean prompt tokens per decision, when the run logged them.

Every metric counts only the model's decisions (player == "model"). Equity is
Monte Carlo vs one random hand (poker.hands.equity_vs_random), seeded from a hash of
the cards so the same spot always gets the same number.
"""

import hashlib
import math
import random
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Callable, Optional

from analysis.loading import NOT_LOGGED, Run
from analysis.paired import PairingError
from analysis.stats import MeanCI, Proportion, mean_with_ci
from poker.engine import ALL_IN, BIG_BLIND, CALL, FOLD, MIN_RAISE, RAISE_HALF_POT, RAISE_POT, RAISE_TWO_THIRDS_POT
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


def _bot_raised_preflop(row: Row) -> bool:
    return any(item["street"] == "preflop" and item["seat"] != row["seat"] and item["action"] in AGGRESSIVE
               for item in row["history"])


def _folds(spots: list[Row]) -> Proportion:
    return Proportion(sum(row["action"] == FOLD for row in spots), len(spots))


def fold_to_bet_preflop(rows: list[Row]) -> Proportion:
    """Of the model's preflop decisions facing a bot raise (to_call > 0 and the history
    shows a bot raise; facing only the big blind doesn't count), the share it folded."""
    return _folds([row for row in _model(rows) if row["street"] == "preflop" and row["to_call"] > 0
                   and _bot_raised_preflop(row)])


def fold_to_bet_postflop(rows: list[Row]) -> Proportion:
    """Of the model's postflop decisions facing a bet or raise (to_call > 0, which
    heads-up postflop means the bot bet or raised), the share it folded."""
    return _folds([row for row in _model(rows) if row["street"] in POSTFLOP and row["to_call"] > 0])


def fold_to_bet_rate(rows: list[Row]) -> Proportion:
    """Maniac and rock: of the model's decisions facing a bot bet or raise, preflop
    (fold_to_bet_preflop) and postflop (fold_to_bet_postflop) together, the share it
    folded. Should go down vs the maniac and up vs the rock.
    """
    preflop, postflop = fold_to_bet_preflop(rows), fold_to_bet_postflop(rows)
    return Proportion(preflop.k + postflop.k, preflop.n + postflop.n)


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
    total = first_hands + last_hands
    return first_hands * n_hands // total, last_hands * n_hands // total


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


# 3. bb/100 over duplicate seed pairs -------------------------------------------------

HANDS_PER_PAIR = 2  # each seed is dealt twice, seats swapped (hands 2i and 2i+1)


def pair_index(hand_number: int) -> int:
    """The seed pair a hand belongs to (poker.runner.deal_schedule: seed i -> hands 2i, 2i+1)."""
    return hand_number // HANDS_PER_PAIR


def pair_bb100(hands: list[Row]) -> tuple[dict[int, float], int]:
    """({pair: the model's bb/100 over that pair's two hands}, pairs missing a hand).

    A pair's result is its two chip deltas summed, in big blinds, per hand, x 100.
    """
    by_pair: dict[int, list[int]] = {}
    for row in hands:
        by_pair.setdefault(pair_index(row["hand_number"]), []).append(row["chip_delta"][MODEL])
    complete = {pair: deltas for pair, deltas in by_pair.items() if len(deltas) == HANDS_PER_PAIR}
    results = {pair: sum(deltas) / BIG_BLIND / HANDS_PER_PAIR * 100 for pair, deltas in sorted(complete.items())}
    return results, len(by_pair) - len(complete)


@dataclass(frozen=True)
class BbPer100:
    """The model's bb/100: mean ± 1.96 SE over complete seed pairs."""

    pair_bb100: dict[int, float]
    incomplete_pairs: int
    mean: MeanCI


def bb_per_100(hands: list[Row]) -> BbPer100:
    results, incomplete = pair_bb100(hands)
    return BbPer100(results, incomplete, mean_with_ci(list(results.values())))


# 4. Descriptive profile: VPIP, PFR, AF, WTSD ---------------------------------------


@dataclass(frozen=True)
class Profile:
    """The model's playing style (descriptive, no test).

    vpip: hands where it put chips in voluntarily preflop (called or raised; the big
          blind's free check doesn't count), out of hands where it had a preflop decision.
    pfr:  hands where it raised preflop, same denominator.
    af:   aggression factor, postflop bets and raises / postflop calls (inf with no
          calls, nan with neither).
    wtsd: hands that reached showdown, out of hands that saw a flop.
    """

    vpip: Proportion
    pfr: Proportion
    af: float
    wtsd: Proportion
    postflop_bets_raises: int = 0  # AF's numerator
    postflop_calls: int = 0  # AF's denominator


def player_profile(decisions: list[Row], hands: list[Row]) -> Profile:
    preflop: dict[int, list[str]] = {}
    postflop_aggressive = postflop_calls = 0
    for row in _model(decisions):
        if row["street"] == "preflop":
            preflop.setdefault(row["hand_number"], []).append(row["action"])
        elif _is_aggressive(row):
            postflop_aggressive += 1
        elif row["action"] == CALL:
            postflop_calls += 1
    vpip = sum(any(action == CALL or action in AGGRESSIVE for action in actions) for actions in preflop.values())
    pfr = sum(any(action in AGGRESSIVE for action in actions) for actions in preflop.values())
    if postflop_calls:
        af = postflop_aggressive / postflop_calls
    else:
        af = math.inf if postflop_aggressive else math.nan
    saw_flop = [row for row in hands if len(row["board"]) >= 3]
    return Profile(
        vpip=Proportion(vpip, len(preflop)),
        pfr=Proportion(pfr, len(preflop)),
        af=af,
        wtsd=Proportion(sum(bool(row["showdown"]) for row in saw_flop), len(saw_flop)),
        postflop_bets_raises=postflop_aggressive,
        postflop_calls=postflop_calls,
    )


# 5. Fallbacks and parse status ------------------------------------------------------


@dataclass(frozen=True)
class OutputQuality:
    """fallback: the model's decisions that fell back to check or fold (decision 12).
    parse_status: model decisions per parser status ("not logged" for scripted players)."""

    fallback: Proportion
    parse_status: dict[str, int]


def output_quality(rows: list[Row]) -> OutputQuality:
    mine = _model(rows)
    return OutputQuality(
        fallback=Proportion(sum(bool(row["fallback"]) for row in mine), len(mine)),
        parse_status=dict(Counter(row.get("parse_status") or NOT_LOGGED for row in mine)),
    )


# 6. Prompt length --------------------------------------------------------------------


def mean_prompt_tokens(rows: list[Row]) -> Optional[float]:
    """Mean prompt_tokens over the model's decisions that logged it; None if none did
    (scripted players, or runs from before the column existed)."""
    counts = [row["prompt_tokens"] for row in _model(rows) if row.get("prompt_tokens") is not None]
    return sum(counts) / len(counts) if counts else None


# Paired comparison of two runs on the same seeds ------------------------------------

BOOTSTRAP_RESAMPLES = 10_000
BOOTSTRAP_SEED = 480  # fixed, so the bootstrap interval is the same every time it is run


@dataclass(frozen=True)
class RunComparison:
    """Run B minus run A on the same seed pairs (e.g. memory minus plain).

    pair_differences: {pair: B's bb/100 - A's bb/100} over pairs complete in both.
    difference: their mean ± 1.96 SE. bootstrap_low/high: the paired bootstrap 95%
    percentile interval of the mean; bootstrap_p: its two-sided p-value for "no change".
    habits: each habit metric B - A over the decisions in those same common pairs
    (decisions are not paired across runs, so the interval is Newcombe's for
    independent rates).
    """

    a: str
    b: str
    pair_differences: dict[int, float]
    unmatched_pairs: int  # pairs complete in only one of the runs
    difference: MeanCI
    bootstrap_low: float
    bootstrap_high: float
    bootstrap_p: float
    habits: dict[str, RateDifference]


def compare_runs(a: Run, b: Run) -> RunComparison:
    """Pair two runs seed pair by seed pair. PairingError unless both were dealt the
    same seed list against the same bot."""
    for key, label in (("seeds", "seed list"), ("bot", "bot")):
        for run in (a, b):
            if run.metadata.get(key) is None:
                raise PairingError(f"cannot pair {a.name} with {b.name}: {run.name}'s metadata has no '{key}'")
        if a.metadata[key] != b.metadata[key]:
            raise PairingError(f"cannot pair {a.name} with {b.name}: the {label} differs")
    results_a, _ = pair_bb100(a.hands)
    results_b, _ = pair_bb100(b.hands)
    common = sorted(set(results_a) & set(results_b))
    differences = {pair: results_b[pair] - results_a[pair] for pair in common}
    low, high, p_value = paired_bootstrap(list(differences.values()))
    bot = a.metadata.get("bot", "")
    in_common = set(common)
    habits_a, habits_b = (habit_metrics([row for row in run.decisions if pair_index(row["hand_number"]) in in_common], bot)
                          for run in (a, b))
    return RunComparison(
        a=a.name, b=b.name,
        pair_differences=differences,
        unmatched_pairs=len(set(results_a) ^ set(results_b)),
        difference=mean_with_ci(list(differences.values())),
        bootstrap_low=low, bootstrap_high=high, bootstrap_p=p_value,
        habits={name: rate_difference(habits_a[name].rate, habits_b[name].rate) for name in habits_a},
    )


def paired_bootstrap(differences: list[float], resamples: int = BOOTSTRAP_RESAMPLES,
                     seed: int = BOOTSTRAP_SEED) -> tuple[float, float, float]:
    """(low, high, p) for the mean of per-pair differences: resample the pairs with
    replacement; the 2.5th and 97.5th percentiles of the resampled means are the
    interval, and p = 2 x the smaller share of resampled means on either side of 0.
    nan for no pairs.
    """
    if not differences:
        return math.nan, math.nan, math.nan
    rng = random.Random(seed)
    n = len(differences)
    means = sorted(sum(rng.choices(differences, k=n)) / n for _ in range(resamples))
    low, high = means[int(0.025 * resamples)], means[int(0.975 * resamples) - 1]
    below = sum(mean <= 0 for mean in means) / resamples
    above = sum(mean >= 0 for mean in means) / resamples
    return low, high, min(1.0, 2 * min(below, above))


# JSON-ready summaries (scripts/analyze_poker.py) ------------------------------------


def _number(value: Optional[float]) -> Optional[float]:
    """nan and inf become None, so summary.json stays strict JSON."""
    if value is None or math.isnan(value) or math.isinf(value):
        return None
    return value


def _proportion(rate: Proportion) -> dict[str, Any]:
    return {"k": rate.k, "n": rate.n, "rate": _number(rate.rate), "low": _number(rate.low), "high": _number(rate.high)}


def _difference(diff: RateDifference) -> dict[str, Any]:
    return {"before": _proportion(diff.before), "after": _proportion(diff.after),
            "difference": _number(diff.difference), "low": _number(diff.low), "high": _number(diff.high)}


def _mean(mean: MeanCI) -> dict[str, Any]:
    return {"mean": _number(mean.mean), "low": _number(mean.low), "high": _number(mean.high), "n": mean.n}


def _habit_split(name: str, rows: list[Row]) -> dict[str, Any]:
    """fold_to_bet_rate's preflop and postflop parts; nothing for the other habits."""
    if name != "fold_to_bet_rate":
        return {}
    return {"fold_to_bet_preflop": _proportion(fold_to_bet_preflop(rows)),
            "fold_to_bet_postflop": _proportion(fold_to_bet_postflop(rows))}


def summarize_run(run: Run, first_hands: int = FIRST_HANDS, last_hands: int = LAST_HANDS) -> dict[str, Any]:
    """Every metric for one run, as plain JSON-ready values."""
    bot = run.metadata.get("bot", "")
    n_hands = max((row["hand_number"] for row in run.hands), default=-1) + 1
    first, last = trend_windows(n_hands, first_hands, last_hands)
    bb = bb_per_100(run.hands)
    profile = player_profile(run.decisions, run.hands)
    quality = output_quality(run.decisions)
    return {
        "run": run.name,
        "run_id": run.run_id,
        "model": run.metadata.get("model"),
        "setup": run.metadata.get("setup"),
        "bot": bot,
        "hands": len(run.hands),
        "pairs": len(bb.pair_bb100),
        "habits": {name: {**_proportion(habit.rate), "target": habit.target, **_habit_split(name, run.decisions)}
                   for name, habit in habit_metrics(run.decisions, bot).items()},
        "trend": {"first_hands": first, "last_hands": last,
                  "habits": {name: _difference(diff) for name, diff in
                             habit_trends(run.decisions, bot, n_hands, first_hands, last_hands).items()}},
        "bb_per_100": {**_mean(bb.mean), "pairs": len(bb.pair_bb100), "incomplete_pairs": bb.incomplete_pairs},
        "profile": {"vpip": _proportion(profile.vpip), "pfr": _proportion(profile.pfr),
                    "af": _number(profile.af), "af_bets_raises": profile.postflop_bets_raises,
                    "af_calls": profile.postflop_calls, "wtsd": _proportion(profile.wtsd)},
        "fallback": _proportion(quality.fallback),
        "parse_status": quality.parse_status,
        "prompt_tokens_mean": _number(mean_prompt_tokens(run.decisions)),
    }


def summarize_comparison(comparison: RunComparison) -> dict[str, Any]:
    """A paired comparison as plain JSON-ready values (B - A)."""
    return {
        "a": comparison.a,
        "b": comparison.b,
        "pairs": len(comparison.pair_differences),
        "unmatched_pairs": comparison.unmatched_pairs,
        "bb_per_100_difference": _mean(comparison.difference),
        "bootstrap_low": _number(comparison.bootstrap_low),
        "bootstrap_high": _number(comparison.bootstrap_high),
        "bootstrap_p": _number(comparison.bootstrap_p),
        "habits": {name: _difference(diff) for name, diff in comparison.habits.items()},
        "pair_differences": {str(pair): value for pair, value in comparison.pair_differences.items()},
    }
