"""Every metric the paper reports, computed only from logged rows.

Terms follow CONTEXT.md: a *decision* is one action the model chose; a *correct
decision* matches the best legal basic-strategy action; an *invalid action* is a
reply that couldn't be parsed or named an illegal action. Invalid actions count
as incorrect and stay in the denominator of decision accuracy.

Decision rows are the dicts in decisions.jsonl; hand rows are the dicts in
hands.jsonl (see agent/run_log.py for the full field lists).
"""

import math
import statistics
from collections import Counter
from dataclasses import dataclass
from typing import Any

from analysis.loading import Run
from analysis.stats import MeanCI, Proportion, mean_with_ci

Row = dict[str, Any]

ACTIONS = ["hit", "stand", "double", "split"]
CHOSEN_COLUMNS = ACTIONS + ["invalid"]  # what the model "chose"; invalid is its own column
HAND_TYPES = ["hard", "soft", "pair"]
UPCARDS = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "A"]
SMALL_SAMPLE_N = 30  # groups with fewer decisions than this are flagged "small sample"

HARD_ROWS = [f"hard {t}" for t in range(5, 21)]
SOFT_ROWS = [f"soft {t}" for t in range(13, 21)]
PAIR_ROWS = [f"{r},{r}" for r in ["2", "3", "4", "5", "6", "7", "8", "9", "10", "A"]]

# How each chosen action reads in a mistake description ("doubled hard 12 vs 4").
_MISTAKE_VERBS = {
    "hit": "hit",
    "stand": "stood on",
    "double": "doubled",
    "split": "split",
    "invalid": "invalid action on",
}


# --- small helpers -------------------------------------------------------------


def upcard_label(rank: str) -> str:
    """Chart column for a dealer upcard: J, Q and K become "10"."""
    return "10" if rank in ("J", "Q", "K") else rank


def hand_type(row: Row) -> str:
    """"pair" when splitting was legal (is_pair), else "soft" or "hard"."""
    if row["is_pair"]:
        return "pair"
    return "soft" if row["is_soft"] else "hard"


def chosen_action(row: Row) -> str:
    """What the model chose: its action, or "invalid" (the engine's fallback stand is not a choice)."""
    return "invalid" if row["invalid"] else row["action_taken"]


def _pair_label(row: Row) -> str:
    """"8,8", "10,10" (for any two 10-value cards) or "A,A"."""
    rank = upcard_label(row["player_cards"][0])
    return f"{rank},{rank}"


def describe_situation(row: Row) -> str:
    """Short name for the spot, e.g. "hard 12 vs 4", "soft 17 vs 10", "pair 8,8 vs A"."""
    kind = hand_type(row)
    player = f"pair {_pair_label(row)}" if kind == "pair" else f"{kind} {row['total']}"
    return f"{player} vs {upcard_label(row['dealer_upcard'])}"


def mean_of_field(rows: list[Row], field: str) -> float:
    """Mean of a numeric field, skipping rows where it is missing. nan if there are none."""
    values = [row[field] for row in rows if row.get(field) is not None]
    return statistics.fmean(values) if values else math.nan


# --- which rows count ------------------------------------------------------------
#
# A scenario run (run_type "scenario") logs every decision of each forced hand, but
# only the first one (is_scenario_cell true) is the graded chart cell. Every cell
# metric (accuracy, breakdowns, confusion matrix, action frequency, heatmaps) uses
# only those rows. Rows without a run_type come from natural runs.


def is_scenario_run(run: Run) -> bool:
    return run.metadata.get("run_type") == "scenario" or any(r.get("run_type") == "scenario" for r in run.decisions)


def graded_rows(run: Run) -> list[Row]:
    """Every decision for a natural run; only the scenario cells for a scenario run."""
    if is_scenario_run(run):
        return [row for row in run.decisions if row.get("is_scenario_cell")]
    return list(run.decisions)


def follow_up_rows(run: Run) -> list[Row]:
    """The later decisions of each scenario hand (not graded as cells); empty for a natural run."""
    if is_scenario_run(run):
        return [row for row in run.decisions if not row.get("is_scenario_cell")]
    return []


# --- headline metrics -------------------------------------------------------------


def accuracy(rows: list[Row]) -> Proportion:
    """Decision accuracy: correct decisions / all decisions (invalid ones included)."""
    return Proportion(sum(1 for row in rows if row["correct"]), len(rows))


def invalid_summary(rows: list[Row]) -> tuple[Proportion, dict[str, int]]:
    """Invalid-action rate, plus how many invalid actions had each invalid_reason."""
    reasons = Counter(row["invalid_reason"] or "unknown" for row in rows if row["invalid"])
    return Proportion(sum(reasons.values()), len(rows)), dict(reasons)


def return_summary(hands: list[Row]) -> MeanCI:
    """Mean payout per hand in units, over every hand (blackjacks with no decisions too)."""
    return mean_with_ci([hand["payout"] for hand in hands])


# --- breakdowns -------------------------------------------------------------------


@dataclass(frozen=True)
class Group:
    """One row of a breakdown table."""

    label: str
    result: Proportion

    @property
    def small_sample(self) -> bool:
        return self.result.n < SMALL_SAMPLE_N


def _grouped_accuracy(rows: list[Row], key, labels: list[str]) -> list[Group]:
    """Accuracy for each label, in the given order (labels with no rows get n = 0)."""
    return [Group(label, accuracy([row for row in rows if key(row) == label])) for label in labels]


def accuracy_by_hand_type(rows: list[Row]) -> list[Group]:
    """Accuracy for hard, soft and pair decisions."""
    return _grouped_accuracy(rows, hand_type, HAND_TYPES)


def accuracy_by_upcard(rows: list[Row]) -> list[Group]:
    """Accuracy for each dealer upcard 2..10, A (face cards counted as 10)."""
    return _grouped_accuracy(rows, lambda row: upcard_label(row["dealer_upcard"]), UPCARDS)


def confusion_matrix(rows: list[Row]) -> dict[str, dict[str, int]]:
    """matrix[optimal][chosen] = count. Every action pair is present, including zeros."""
    matrix = {optimal: {chosen: 0 for chosen in CHOSEN_COLUMNS} for optimal in ACTIONS}
    for row in rows:
        matrix[row["optimal_action"]][chosen_action(row)] += 1
    return matrix


def action_frequency(rows: list[Row]) -> dict[str, dict[str, int]]:
    """How often the model chose each action vs how often basic strategy called for it.

    Basic strategy counts are the optimal actions at the decisions the model
    actually faced (not a separate basic-strategy player's own hands).
    """
    model = Counter(chosen_action(row) for row in rows)
    optimal = Counter(row["optimal_action"] for row in rows)
    return {
        "model": {action: model[action] for action in CHOSEN_COLUMNS},
        "basic_strategy": {action: optimal[action] for action in CHOSEN_COLUMNS},
    }


def describe_mistake(row: Row) -> str:
    """E.g. "doubled hard 12 vs 4 (optimal: stand)"."""
    verb = _MISTAKE_VERBS[chosen_action(row)]
    return f"{verb} {describe_situation(row)} (optimal: {row['optimal_action']})"


def top_mistakes(rows: list[Row], limit: int = 10) -> list[tuple[str, int]]:
    """The most common incorrect decisions as (description, count), most frequent first.

    Ties are broken alphabetically so the list is the same on every run.
    """
    counts = Counter(describe_mistake(row) for row in rows if not row["correct"])
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:limit]


# --- heatmap grid ------------------------------------------------------------------


def heatmap_row_label(row: Row) -> str:
    """Heatmap row: "hard 12", "soft 18" or a pair like "8,8"."""
    kind = hand_type(row)
    return _pair_label(row) if kind == "pair" else f"{kind} {row['total']}"


def heatmap_row_labels(rows: list[Row]) -> list[str]:
    """Hard 5-20, soft 13-20, then the ten pairs; plus any other hard/soft total seen.

    Extra totals (e.g. hard 4 from a 2,2 that can no longer be split) are slotted
    into their group in numeric order so no decision is dropped from the heatmap.
    """
    def totals(kind: str, standard: range) -> list[str]:
        seen = {row["total"] for row in rows if hand_type(row) == kind}
        return [f"{kind} {t}" for t in sorted(seen | set(standard))]

    return totals("hard", range(5, 21)) + totals("soft", range(13, 21)) + PAIR_ROWS


def accuracy_grid(rows: list[Row]) -> dict[tuple[str, str], Proportion]:
    """{(row label, upcard): accuracy}. Cells with no decisions are absent."""
    cells: dict[tuple[str, str], list[Row]] = {}
    for row in rows:
        cells.setdefault((heatmap_row_label(row), upcard_label(row["dealer_upcard"])), []).append(row)
    return {key: accuracy(cell_rows) for key, cell_rows in cells.items()}


# --- whole-run summary ---------------------------------------------------------------


@dataclass
class RunSummary:
    """Every number results.md and the comparison table need, for one run."""

    run: Run
    accuracy: Proportion  # scenario runs: scenario cells only
    invalid: Proportion
    invalid_reasons: dict[str, int]
    returns: MeanCI | None  # None for scenario runs (not a natural sample)
    total_payout: float | None
    by_hand_type: list[Group]
    by_upcard: list[Group]
    confusion: dict[str, dict[str, int]]
    frequency: dict[str, dict[str, int]]
    mistakes: list[tuple[str, int]]
    decisions_per_hand: float
    mean_latency_s: float
    mean_eval_count: float
    ev_loss: Any = None  # analysis.ev_loss.EVLossSummary (Any avoids a circular import)
    is_scenario: bool = False
    follow_up: Proportion | None = None  # scenario runs: accuracy of the non-cell decisions
    follow_up_invalid: Proportion | None = None

    @property
    def run_type(self) -> str:
        return "scenario" if self.is_scenario else "natural"


def summarize_run(run: Run) -> RunSummary:
    """Compute every metric for one run (scenario runs: cell metrics on the scenario cells only)."""
    from analysis.ev_loss import summarize_run_ev_loss  # here, not at the top: ev_loss imports this module

    scenario = is_scenario_run(run)
    rows = graded_rows(run)
    invalid, reasons = invalid_summary(rows)
    follow_ups = follow_up_rows(run)
    return RunSummary(
        run=run,
        accuracy=accuracy(rows),
        invalid=invalid,
        invalid_reasons=reasons,
        returns=None if scenario else return_summary(run.hands),
        total_payout=None if scenario else sum(hand["payout"] for hand in run.hands),
        by_hand_type=accuracy_by_hand_type(rows),
        by_upcard=accuracy_by_upcard(rows),
        confusion=confusion_matrix(rows),
        frequency=action_frequency(rows),
        mistakes=top_mistakes(rows),
        decisions_per_hand=len(run.decisions) / len(run.hands) if run.hands else math.nan,
        mean_latency_s=mean_of_field(run.decisions, "latency_s"),
        mean_eval_count=mean_of_field(run.decisions, "eval_count"),
        ev_loss=summarize_run_ev_loss(run),
        is_scenario=scenario,
        follow_up=accuracy(follow_ups) if scenario else None,
        follow_up_invalid=invalid_summary(follow_ups)[0] if scenario else None,
    )


def pooled_accuracy(summaries: list[RunSummary]) -> Proportion:
    """One accuracy over several runs of the same type.

    A natural run and a scenario run measure different things (natural dealing
    weights cells by how often they occur, the scenario set weights every cell
    once), so they are never pooled; compare them side by side instead.
    """
    types = {s.run_type for s in summaries}
    if len(types) > 1:
        raise ValueError(f"refusing to pool runs of different types {sorted(types)}; compare them side by side")
    return Proportion(sum(s.accuracy.k for s in summaries), sum(s.accuracy.n for s in summaries))
