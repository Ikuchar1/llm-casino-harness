"""Scenario-aware analysis: scenario runs grade only the first decision of each forced hand.

A scenario run (run_type "scenario") logs every decision of each forced hand, but
only the first one (is_scenario_cell true) is the graded chart cell. Follow-up
decisions are reported on their own line, returns are not reported, and a
scenario run is never pooled with a natural run.
"""

import importlib.util
from pathlib import Path

import pytest

from analysis.loading import Run, load_run
from analysis.metrics import (
    accuracy_grid,
    follow_up_rows,
    graded_rows,
    is_scenario_run,
    pooled_accuracy,
    summarize_run,
)
from analysis.report import BASIC_STRATEGY_RETURN, comparison_markdown, comparison_rows, results_markdown
from test_analysis_metrics import METADATA, decision, hand, write_run
from test_ev import exact_basic_strategy_return

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "analyze.py"
SCENARIO_METADATA = {**METADATA, "run_id": "s1", "run_type": "scenario"}


def cell(**kwargs):
    return {**decision(**kwargs), "run_type": "scenario", "is_scenario_cell": True}


def follow_up(**kwargs):
    return {**decision(**kwargs), "run_type": "scenario", "is_scenario_cell": False}


# Hand 1: hard 12 vs 4, doubled (wrong); then a follow-up hit that is correct.
# Hand 2: 8,8 vs 10, split (correct); then two follow-ups, one wrong, one invalid.
# Hand 3: soft 18 vs 9, stood (wrong).
SCENARIO_ROWS = [
    cell(hand_number=1, cards=("10", "2"), total=12, upcard="4", taken="double", optimal="stand"),
    follow_up(hand_number=1, cards=("10", "2", "3"), total=15, upcard="4", taken="hit", optimal="hit"),
    cell(hand_number=2, cards=("8", "8"), total=16, pair=True, upcard="10", taken="split", optimal="split"),
    follow_up(hand_number=2, cards=("8", "3"), total=11, upcard="10", taken="double", optimal="hit"),
    follow_up(hand_number=2, cards=("8", "9"), total=17, upcard="10", taken="stand", optimal="stand",
              invalid=True, reason="no_marker"),
    cell(hand_number=3, cards=("A", "7"), total=18, soft=True, upcard="9", taken="stand", optimal="hit"),
]
SCENARIO_HANDS = [hand(1, -2, 2), hand(2, 3, 3), hand(3, -1, 1)]


def scenario_run(rows=SCENARIO_ROWS, hands=SCENARIO_HANDS):
    return Run(name="scen", metadata=SCENARIO_METADATA, decisions=list(rows), hands=list(hands))


def natural_run():
    rows = [
        decision(hand_number=1, total=12, upcard="4", taken="double", optimal="stand"),
        decision(hand_number=2, taken="hit", optimal="hit"),
    ]
    return Run(name="nat", metadata=METADATA, decisions=rows, hands=[hand(1, -2), hand(2, 1)])


# --- which rows count ---------------------------------------------------------------


def test_scenario_rows_split_into_cells_and_follow_ups():
    run = scenario_run()
    assert is_scenario_run(run)
    assert [r["hand_number"] for r in graded_rows(run)] == [1, 2, 3]
    assert [r["hand_number"] for r in follow_up_rows(run)] == [1, 2, 2]


def test_missing_run_type_means_natural():
    run = natural_run()
    assert not is_scenario_run(run)
    assert graded_rows(run) == run.decisions
    assert follow_up_rows(run) == []


def test_load_run_refuses_a_directory_mixing_scenario_and_natural_rows(tmp_path):
    rows = [cell(), decision(hand_number=2)]
    write_run(tmp_path / "mixed", rows, [hand(1, -1), hand(2, -1)], METADATA)
    with pytest.raises(ValueError, match="scenario"):
        load_run(tmp_path / "mixed")


# --- cell metrics use only the scenario cells ------------------------------------------


def test_scenario_summary_cell_metrics_use_only_scenario_cells():
    s = summarize_run(scenario_run())
    assert s.is_scenario
    assert (s.accuracy.k, s.accuracy.n) == (1, 3)
    assert s.invalid.k == 0  # the only invalid action was a follow-up
    assert {g.label: (g.result.k, g.result.n) for g in s.by_hand_type} == {
        "hard": (0, 1), "soft": (0, 1), "pair": (1, 1),
    }
    assert sum(g.result.n for g in s.by_upcard) == 3
    assert sum(sum(row.values()) for row in s.confusion.values()) == 3
    assert s.confusion["stand"]["double"] == 1
    assert sum(s.frequency["model"].values()) == 3
    assert s.frequency["model"]["split"] == 1 and s.frequency["model"]["double"] == 1
    assert dict(s.mistakes) == {
        "doubled hard 12 vs 4 (optimal: stand)": 1,
        "stood on soft 18 vs 9 (optimal: hit)": 1,
    }


def test_scenario_summary_reports_follow_ups_separately():
    s = summarize_run(scenario_run())
    assert (s.follow_up.k, s.follow_up.n) == (1, 3)
    assert (s.follow_up_invalid.k, s.follow_up_invalid.n) == (1, 3)


def test_scenario_summary_has_no_returns():
    s = summarize_run(scenario_run())
    assert s.returns is None
    assert s.total_payout is None


def test_natural_summary_has_no_follow_up_line():
    s = summarize_run(natural_run())
    assert not s.is_scenario
    assert s.follow_up is None and s.follow_up_invalid is None
    assert s.returns.n == 2


def test_scenario_heatmap_grid_has_one_result_per_cell():
    grid = accuracy_grid(graded_rows(scenario_run()))
    assert len(grid) == 3
    assert all(p.n == 1 for p in grid.values())


# --- results.md ----------------------------------------------------------------------


def test_scenario_results_hide_returns_and_label_follow_ups():
    text = results_markdown(summarize_run(scenario_run()), [])
    assert "33.3% (1/3" in text
    assert "Follow-up decisions" in text and "1/3" in text
    assert "Mean return per hand" not in text
    assert "Net result" not in text
    assert "basic-strategy return" not in text
    assert "units/hand" not in text
    assert "not a natural sample" in text


def test_natural_results_quote_the_exact_basic_strategy_return():
    text = results_markdown(summarize_run(natural_run()), [])
    assert "-0.457% per hand (exact, computed; not from this run)" in text
    assert "-0.425%" in text and "-0.555% to -0.296%" in text
    assert "Follow-up decisions" not in text


def test_basic_strategy_return_constant_matches_the_exact_enumeration():
    assert round(exact_basic_strategy_return() * 100, 3) == round(BASIC_STRATEGY_RETURN * 100, 3) == -0.457


# --- never pool a natural and a scenario run --------------------------------------------


def test_pooled_accuracy_refuses_to_mix_run_types():
    with pytest.raises(ValueError, match="pool"):
        pooled_accuracy([summarize_run(natural_run()), summarize_run(scenario_run())])


def test_pooled_accuracy_of_same_type_runs():
    pooled = pooled_accuracy([summarize_run(natural_run()), summarize_run(natural_run())])
    assert (pooled.k, pooled.n) == (2, 4)


def test_comparison_puts_runs_side_by_side_with_their_type():
    summaries = [summarize_run(natural_run()), summarize_run(scenario_run())]
    text = comparison_markdown(summaries)
    assert "Run type" in text
    assert "| natural |" in text and "| scenario |" in text
    assert "not pooled" in text
    assert "not reported (scenario run)" in text
    rows = comparison_rows(summaries)
    assert [r["run_type"] for r in rows] == ["natural", "scenario"]
    assert rows[1]["decisions"] == 3
    assert rows[1]["mean_return_per_hand"] == "" and rows[1]["follow_up_accuracy"] == pytest.approx(1 / 3)
    assert rows[0]["follow_up_accuracy"] == ""


# --- end to end -----------------------------------------------------------------------


def test_cli_analyzes_a_scenario_run_and_a_comparison(tmp_path):
    spec = importlib.util.spec_from_file_location("analyze_script", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    write_run(tmp_path / "scen", SCENARIO_ROWS, SCENARIO_HANDS, SCENARIO_METADATA)
    write_run(tmp_path / "nat", natural_run().decisions, natural_run().hands, METADATA)
    out = tmp_path / "cmp"
    module.main([str(tmp_path / "nat"), str(tmp_path / "scen"), "--out", str(out)])
    for name in ["results.md", "accuracy_heatmap.png", "confusion_matrix.png", "action_frequency.png",
                 "accuracy_by_hand_type.png", "ev_loss_heatmap.png"]:
        assert (out / "scen" / name).exists(), name
    assert (out / "comparison_accuracy.png").exists()
    assert "scenario" in (out / "comparison.md").read_text()


# --- scenario heatmap ------------------------------------------------------------------


def test_scenario_heatmap_cell_shows_the_action_and_the_chart_action_when_wrong():
    from analysis.charts import scenario_cell_label

    assert scenario_cell_label(cell(taken="hit", optimal="hit")) == "H"
    assert scenario_cell_label(cell(taken="double", optimal="stand")) == "D (S)"
    assert scenario_cell_label(cell(taken="split", optimal="split")) == "P"
    assert scenario_cell_label(cell(taken="stand", optimal="hit", invalid=True, reason="no_marker")) == "inv (H)"


def test_scenario_heatmap_rows_drop_rows_outside_the_scenario_set():
    from analysis.charts import heatmap_rows_for

    labels = heatmap_rows_for(summarize_run(scenario_run()))
    assert labels == ["hard 12", "soft 18", "8,8"]
    natural = heatmap_rows_for(summarize_run(natural_run()))
    assert "hard 20" in natural and "soft 13" in natural  # natural runs keep every standard row


def test_scenario_results_skip_the_by_count_mistake_list():
    """Every cell is played once, so a by-count list would just be alphabetical ×1 entries."""
    text = results_markdown(summarize_run(scenario_run()), [])
    assert "Most common mistakes (top 10 by count)" not in text
    assert "×1" not in text
    assert "each cell is played once" in text.lower()
