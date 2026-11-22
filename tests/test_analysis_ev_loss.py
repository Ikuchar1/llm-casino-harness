"""Tests for EV loss per decision and its summaries (analysis/ev_loss.py)."""

import math

import pytest

from analysis.ev_loss import (
    decision_ev,
    ev_loss_grid,
    graded_rows,
    is_scenario_run,
    summarize_ev_loss,
)
from analysis.loading import Run
from blackjack.ev import action_evs
from test_analysis_metrics import METADATA, decision


def test_correct_decision_has_zero_ev_loss():
    row = decision(cards=("10", "6"), total=16, upcard="10", taken="hit", optimal="hit")
    assert decision_ev(row).loss == 0


def test_doubling_hard_17_vs_10_is_costly():
    row = decision(cards=("10", "7"), total=17, upcard="10", taken="double", optimal="stand")
    evs = action_evs(["10", "7"], "10", can_double=True, can_split=False)
    result = decision_ev(row)
    assert result.loss == pytest.approx(evs["stand"] - evs["double"])
    assert result.loss > 0.5


def test_invalid_action_is_charged_for_the_stand_fallback():
    row = decision(cards=("6", "5"), total=11, upcard="6", taken="stand", optimal="double", invalid=True)
    evs = action_evs(["6", "5"], "6", can_double=True, can_split=False)
    assert decision_ev(row).loss == pytest.approx(evs["double"] - evs["stand"])


def test_legal_actions_come_from_the_log_when_present():
    # Three cards: double isn't legal, so only hit and stand are valued.
    row = decision(cards=("5", "3", "3"), total=11, upcard="6", taken="hit", optimal="hit")
    row["legal_actions"] = ["hit", "stand"]
    assert set(decision_ev(row).evs) == {"hit", "stand"}


def test_split_hand_also_removes_the_other_split_card():
    row = decision(cards=("8", "3"), total=11, upcard="6", taken="double", optimal="double")
    row["from_split"] = True
    plain = action_evs(["8", "3"], "6", can_double=True, can_split=False)
    assert decision_ev(row).evs != plain


def test_model_can_beat_the_chart_giving_negative_loss():
    # Three-card 16 vs 10: the chart says hit, but standing is slightly better.
    row = decision(cards=("4", "5", "7"), total=16, upcard="10", taken="stand", optimal="hit")
    row["legal_actions"] = ["hit", "stand"]
    result = decision_ev(row)
    assert result.loss < 0
    assert result.ev_best == result.ev_taken


# --- scenario runs -----------------------------------------------------------


def scenario_run(rows):
    return Run(name="s", metadata={**METADATA, "run_type": "scenario"}, decisions=rows, hands=[])


def test_scenario_run_uses_only_the_scenario_cells():
    first = {**decision(hand_number=1), "run_type": "scenario", "is_scenario_cell": True}
    later = {**decision(hand_number=1), "run_type": "scenario", "is_scenario_cell": False}
    run = scenario_run([first, later])
    assert is_scenario_run(run)
    assert graded_rows(run) == [first]


def test_natural_run_uses_every_decision():
    rows = [decision(), decision(hand_number=2)]
    run = Run(name="n", metadata=METADATA, decisions=rows, hands=[])
    assert not is_scenario_run(run)
    assert graded_rows(run) == rows


# --- summary -----------------------------------------------------------------


ROWS = [
    decision(hand_number=1, cards=("10", "7"), total=17, upcard="10", taken="double", optimal="stand"),
    decision(hand_number=1, cards=("10", "7"), total=17, upcard="10", taken="double", optimal="stand"),
    decision(hand_number=2, cards=("10", "6"), total=16, upcard="10", taken="hit", optimal="hit"),
    decision(hand_number=3, cards=("6", "5"), total=11, upcard="6", taken="stand", optimal="double",
             invalid=True, reason="no_marker"),
    decision(hand_number=4, cards=("8", "8"), total=16, pair=True, upcard="6", taken="stand", optimal="split"),
]


def test_summary_totals_and_means():
    s = summarize_ev_loss(ROWS, n_hands=5)
    losses = [decision_ev(row).loss for row in ROWS]
    assert s.n_decisions == 5
    assert s.total == pytest.approx(sum(losses))
    assert s.mean_per_decision == pytest.approx(sum(losses) / 5)
    assert s.mean_per_hand == pytest.approx(sum(losses) / 5)
    assert s.n_mistakes == 4
    assert s.mean_per_mistake == pytest.approx(sum(losses) / 4)


def test_summary_reports_invalid_actions_separately():
    s = summarize_ev_loss(ROWS, n_hands=5)
    assert s.invalid.n == 1
    assert s.invalid.total == pytest.approx(decision_ev(ROWS[3]).loss)


def test_summary_by_hand_type():
    by_type = {g.label: g for g in summarize_ev_loss(ROWS, n_hands=5).by_hand_type}
    assert by_type["hard"].n == 4
    assert by_type["pair"].n == 1
    assert by_type["soft"].n == 0 and math.isnan(by_type["soft"].mean)


def test_costliest_mistakes_ranked_by_total_loss():
    top = summarize_ev_loss(ROWS, n_hands=5).costliest
    assert top[0].label == "doubled hard 17 vs 10 (optimal: stand)"
    assert top[0].n == 2
    assert top[0].total == pytest.approx(2 * decision_ev(ROWS[0]).loss)
    assert all(a.total >= b.total for a, b in zip(top, top[1:]))
    assert "hit hard 16 vs 10" not in [g.label.split(" (")[0] for g in top]  # correct decisions aren't mistakes


def test_empty_rows_give_nan_means():
    s = summarize_ev_loss([], n_hands=0)
    assert s.total == 0 and math.isnan(s.mean_per_decision) and math.isnan(s.mean_per_hand)


def test_ev_loss_grid_mean_per_cell():
    grid = ev_loss_grid(ROWS)
    assert grid[("hard 17", "10")].n == 2
    assert grid[("hard 17", "10")].mean == pytest.approx(decision_ev(ROWS[0]).loss)
    assert ("8,8", "6") in grid


# --- whole-run summary ---------------------------------------------------------


def test_run_summary_carries_ev_loss_and_scenario_runs_count_scenario_hands():
    from analysis.metrics import summarize_run

    rows = [
        {**ROWS[0], "run_type": "scenario", "is_scenario_cell": True, "hand_number": 1},
        {**ROWS[1], "run_type": "scenario", "is_scenario_cell": False, "hand_number": 1},
        {**ROWS[2], "run_type": "scenario", "is_scenario_cell": True, "hand_number": 2},
    ]
    s = summarize_run(scenario_run(rows)).ev_loss
    assert s.n_decisions == 2
    assert s.n_hands == 2
    assert s.total == pytest.approx(decision_ev(ROWS[0]).loss)
