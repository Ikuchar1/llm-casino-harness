"""EV loss: how much expected value each decision gave up, in units per 1-unit bet.

    EV loss = EV(basic-strategy action) - EV(action the game actually played)

"Basic-strategy action" is the logged optimal_action, the same best legal
action decisions are graded against, so a correct decision always has an EV
loss of exactly 0. EVs come from blackjack/ev.py (6 decks, the player's cards
and the dealer's upcard removed from the shoe, dealer has no blackjack).

Two choices to know about:
- Invalid actions are charged for the stand the game played as the fallback,
  and are also summarized on their own.
- In a few composition-dependent spots (e.g. a three-card 16 vs 10) standing
  beats the chart's hit. A model that stands there is graded incorrect but its
  EV loss is slightly negative. Losses are not clipped at 0, so totals stay honest.

Scenario runs (run_type "scenario") only count the graded cell of each
scenario hand (is_scenario_cell true), matching how scenario accuracy works.
"""

import math
import statistics
from collections import defaultdict
from dataclasses import dataclass

from analysis.loading import Run
from analysis.metrics import (
    HAND_TYPES,
    Row,
    describe_mistake,
    graded_rows,
    hand_type,
    heatmap_row_label,
    is_scenario_run,
    upcard_label,
)
from blackjack.ev import DOUBLE, SPLIT, action_evs, best_action

COSTLIEST_LIMIT = 10


# --- one decision -----------------------------------------------------------------


@dataclass(frozen=True)
class DecisionEV:
    """EVs for one logged decision."""

    evs: dict[str, float]  # EV of every legal action
    ev_taken: float  # EV of what the game played (the stand fallback for invalid actions)
    ev_optimal: float  # EV of the basic-strategy action
    ev_best: float  # highest EV of any legal action (can beat the chart in rare spots)

    @property
    def loss(self) -> float:
        return self.ev_optimal - self.ev_taken


def _legal_actions(row: Row) -> list[str]:
    """The logged legal actions; older or hand-made rows without them get them rebuilt."""
    if row.get("legal_actions"):
        return list(row["legal_actions"])
    actions = ["hit", "stand"]
    if len(row["player_cards"]) == 2:
        actions.append(DOUBLE)
    if row["is_pair"]:
        actions.append(SPLIT)
    return actions


def decision_ev(row: Row) -> DecisionEV:
    """EVs and EV loss for one decision row (see the module docstring)."""
    legal = _legal_actions(row)
    # On a split hand, the other hand's first card (same value as ours) is also gone.
    extra = (row["player_cards"][0],) if row.get("from_split") else ()
    evs = action_evs(
        row["player_cards"],
        row["dealer_upcard"],
        can_double=DOUBLE in legal,
        can_split=SPLIT in legal,
        extra_removed=extra,
    )
    return DecisionEV(
        evs=evs,
        ev_taken=evs[row["action_taken"]],
        ev_optimal=evs[row["optimal_action"]],
        ev_best=evs[best_action(evs)],
    )


# --- summaries --------------------------------------------------------------------


@dataclass(frozen=True)
class LossGroup:
    """EV loss over a group of decisions."""

    label: str
    n: int
    total: float

    @property
    def mean(self) -> float:
        return self.total / self.n if self.n else math.nan


@dataclass
class EVLossSummary:
    """Every EV-loss number results.md and the comparison table need, for one run."""

    n_decisions: int
    n_hands: int
    total: float
    n_mistakes: int
    mistakes_total: float
    invalid: LossGroup
    by_hand_type: list[LossGroup]
    costliest: list[LossGroup]  # mistake types ranked by total EV loss
    n_negative: int  # decisions where the model's choice had higher EV than the chart's
    negative_total: float

    @property
    def mean_per_decision(self) -> float:
        return self.total / self.n_decisions if self.n_decisions else math.nan

    @property
    def mean_per_hand(self) -> float:
        return self.total / self.n_hands if self.n_hands else math.nan

    @property
    def mean_per_mistake(self) -> float:
        return self.mistakes_total / self.n_mistakes if self.n_mistakes else math.nan


def summarize_ev_loss(rows: list[Row], n_hands: int) -> EVLossSummary:
    """EV-loss metrics for these decision rows. n_hands is the per-hand denominator."""
    losses = [decision_ev(row).loss for row in rows]
    mistakes = [(row, loss) for row, loss in zip(rows, losses) if not row["correct"]]
    invalid = [loss for row, loss in zip(rows, losses) if row["invalid"]]
    negative = [loss for loss in losses if loss < 0]

    by_type = [
        LossGroup(kind, *_count_and_sum([loss for row, loss in zip(rows, losses) if hand_type(row) == kind]))
        for kind in HAND_TYPES
    ]

    per_mistake_type: dict[str, list[float]] = defaultdict(list)
    for row, loss in mistakes:
        per_mistake_type[describe_mistake(row)].append(loss)
    costliest = sorted(
        (LossGroup(label, len(values), sum(values)) for label, values in per_mistake_type.items()),
        key=lambda g: (-g.total, g.label),
    )[:COSTLIEST_LIMIT]

    return EVLossSummary(
        n_decisions=len(rows),
        n_hands=n_hands,
        total=sum(losses),
        n_mistakes=len(mistakes),
        mistakes_total=sum(loss for _, loss in mistakes),
        invalid=LossGroup("invalid actions", *_count_and_sum(invalid)),
        by_hand_type=by_type,
        costliest=costliest,
        n_negative=len(negative),
        negative_total=sum(negative),
    )


def _count_and_sum(values: list[float]) -> tuple[int, float]:
    return len(values), sum(values)


def summarize_run_ev_loss(run: Run) -> EVLossSummary:
    """EV loss for a run. Per-hand means use every hand of a natural run (blackjacks too),
    and the number of scenario hands with a graded cell for a scenario run."""
    rows = graded_rows(run)
    n_hands = len({row["hand_number"] for row in rows}) if is_scenario_run(run) else len(run.hands)
    return summarize_ev_loss(rows, n_hands)


@dataclass(frozen=True)
class GridCell:
    n: int
    mean: float


def ev_loss_grid(rows: list[Row]) -> dict[tuple[str, str], GridCell]:
    """{(heatmap row label, upcard): mean EV loss}, same layout as the accuracy heatmap."""
    cells: dict[tuple[str, str], list[float]] = defaultdict(list)
    for row in rows:
        cells[(heatmap_row_label(row), upcard_label(row["dealer_upcard"]))].append(decision_ev(row).loss)
    return {key: GridCell(len(values), statistics.fmean(values)) for key, values in cells.items()}
