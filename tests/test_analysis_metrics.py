"""Tests for the metric functions (analysis/metrics.py) on small hand-made rows.

The fixture rows only carry the fields the metrics read, not every logged field.
"""

import json
import math

import pytest

from analysis.loading import load_run
from analysis.metrics import (
    PAIR_ROWS,
    accuracy,
    accuracy_by_hand_type,
    accuracy_by_upcard,
    accuracy_grid,
    action_frequency,
    chosen_action,
    confusion_matrix,
    describe_situation,
    hand_type,
    heatmap_row_label,
    heatmap_row_labels,
    invalid_summary,
    mean_of_field,
    return_summary,
    summarize_run,
    top_mistakes,
    upcard_label,
)


def decision(
    cards=("10", "6"),
    total=16,
    soft=False,
    pair=False,
    upcard="10",
    taken="stand",
    optimal="hit",
    invalid=False,
    reason=None,
    hand_number=1,
    latency=1.0,
    eval_count=50,
):
    """One decision row with just the fields analysis uses."""
    return {
        "hand_number": hand_number,
        "player_cards": list(cards),
        "total": total,
        "is_soft": soft,
        "is_pair": pair,
        "dealer_upcard": upcard,
        "action_taken": taken,
        "parsed_action": None if invalid else taken,
        "optimal_action": optimal,
        "correct": (not invalid) and taken == optimal,
        "invalid": invalid,
        "invalid_reason": reason,
        "latency_s": latency,
        "eval_count": eval_count,
    }


def hand(number, payout, num_decisions=1):
    return {"hand_number": number, "payout": payout, "num_decisions": num_decisions}


# --- small helpers -----------------------------------------------------------


def test_hand_type_pair_wins_over_soft_and_hard():
    assert hand_type(decision(cards=("A", "A"), total=12, soft=True, pair=True)) == "pair"
    assert hand_type(decision(cards=("A", "6"), total=17, soft=True)) == "soft"
    assert hand_type(decision()) == "hard"


def test_upcard_label_folds_face_cards_into_10():
    assert [upcard_label(r) for r in ["J", "Q", "K", "10", "A", "7"]] == ["10", "10", "10", "10", "A", "7"]


def test_chosen_action_is_invalid_for_invalid_rows_even_though_the_engine_stood():
    assert chosen_action(decision(taken="stand", invalid=True, reason="no_marker")) == "invalid"
    assert chosen_action(decision(taken="double")) == "double"


def test_describe_situation_for_each_hand_type():
    assert describe_situation(decision(total=12, upcard="4")) == "hard 12 vs 4"
    assert describe_situation(decision(cards=("A", "6"), total=17, soft=True, upcard="K")) == "soft 17 vs 10"
    assert describe_situation(decision(cards=("J", "Q"), total=20, pair=True, upcard="A")) == "pair 10,10 vs A"
    assert describe_situation(decision(cards=("A", "A"), total=12, soft=True, pair=True)) == "pair A,A vs 10"


# --- accuracy and invalid rate -------------------------------------------------


def test_accuracy_counts_invalid_actions_as_incorrect_and_keeps_them_in_the_denominator():
    rows = [
        decision(taken="hit", optimal="hit"),
        decision(taken="hit", optimal="hit"),
        decision(taken="stand", optimal="hit"),
        decision(taken="stand", optimal="stand", invalid=True, reason="no_marker"),
    ]
    result = accuracy(rows)
    assert (result.k, result.n) == (2, 4)
    assert result.rate == 0.5
    assert result.low < 0.5 < result.high


def test_accuracy_of_no_decisions_is_nan():
    result = accuracy([])
    assert result.n == 0 and math.isnan(result.rate)


def test_invalid_summary_counts_reasons():
    rows = [
        decision(),
        decision(invalid=True, reason="no_marker"),
        decision(invalid=True, reason="no_marker"),
        decision(invalid=True, reason="illegal_action"),
    ]
    rate, reasons = invalid_summary(rows)
    assert (rate.k, rate.n) == (3, 4)
    assert reasons == {"no_marker": 2, "illegal_action": 1}


# --- return per hand -------------------------------------------------------------


def test_return_summary_uses_every_hand_including_ones_without_decisions():
    hands = [hand(1, 1.5, num_decisions=0), hand(2, -1), hand(3, 2), hand(4, -2.5)]
    result = return_summary(hands)
    assert result.n == 4
    assert result.mean == pytest.approx(0.0)
    assert result.half_width > 0


# --- breakdowns ----------------------------------------------------------------


def test_accuracy_by_hand_type_lists_all_three_types_with_small_sample_flags():
    rows = [
        decision(taken="hit", optimal="hit"),
        decision(cards=("A", "6"), total=17, soft=True, taken="double", optimal="double"),
        decision(cards=("A", "6"), total=17, soft=True, taken="stand", optimal="double"),
    ] + [decision(taken="hit", optimal="hit") for _ in range(30)]
    table = accuracy_by_hand_type(rows)
    assert [group.label for group in table] == ["hard", "soft", "pair"]
    hard, soft, pair = table
    assert (hard.result.k, hard.result.n, hard.small_sample) == (31, 31, False)
    assert (soft.result.k, soft.result.n, soft.small_sample) == (1, 2, True)
    assert pair.result.n == 0 and pair.small_sample


def test_accuracy_by_upcard_orders_2_to_10_then_ace_and_merges_face_cards():
    rows = [
        decision(upcard="K", taken="hit", optimal="hit"),
        decision(upcard="10", taken="stand", optimal="hit"),
        decision(upcard="A", taken="hit", optimal="hit"),
    ]
    table = accuracy_by_upcard(rows)
    assert [group.label for group in table] == ["2", "3", "4", "5", "6", "7", "8", "9", "10", "A"]
    by_label = {group.label: group.result for group in table}
    assert (by_label["10"].k, by_label["10"].n) == (1, 2)
    assert (by_label["A"].k, by_label["A"].n) == (1, 1)
    assert by_label["5"].n == 0


def test_confusion_matrix_rows_are_optimal_and_columns_are_chosen_including_invalid():
    rows = [
        decision(taken="double", optimal="stand"),
        decision(taken="double", optimal="stand"),
        decision(taken="stand", optimal="stand"),
        decision(taken="stand", optimal="hit", invalid=True, reason="no_marker"),
    ]
    matrix = confusion_matrix(rows)
    assert matrix["stand"]["double"] == 2
    assert matrix["stand"]["stand"] == 1
    assert matrix["hit"]["invalid"] == 1
    assert matrix["hit"]["stand"] == 0  # the fallback stand is not counted as a stand choice
    assert matrix["split"]["split"] == 0  # every cell exists, even empty ones


def test_action_frequency_compares_model_choices_with_basic_strategy():
    rows = [
        decision(taken="double", optimal="stand"),
        decision(taken="double", optimal="hit"),
        decision(taken="hit", optimal="hit"),
        decision(taken="stand", optimal="stand", invalid=True, reason="no_marker"),
    ]
    freq = action_frequency(rows)
    assert freq["model"] == {"hit": 1, "stand": 0, "double": 2, "split": 0, "invalid": 1}
    assert freq["basic_strategy"] == {"hit": 2, "stand": 2, "double": 0, "split": 0, "invalid": 0}


def test_top_mistakes_are_phrased_and_sorted_by_count():
    rows = [
        decision(total=12, cards=("K", "2"), upcard="4", taken="double", optimal="stand"),
        decision(total=12, cards=("7", "5"), upcard="4", taken="double", optimal="stand"),
        decision(total=12, cards=("9", "3"), upcard="4", taken="double", optimal="stand"),
        decision(total=16, upcard="10", taken="stand", optimal="hit"),
        decision(total=16, upcard="10", taken="hit", optimal="hit"),  # correct, not a mistake
        decision(total=16, upcard="10", taken="stand", optimal="hit", invalid=True, reason="no_marker"),
    ]
    mistakes = top_mistakes(rows)
    assert mistakes[0] == ("doubled hard 12 vs 4 (optimal: stand)", 3)
    assert ("stood on hard 16 vs 10 (optimal: hit)", 1) in mistakes
    assert ("invalid action on hard 16 vs 10 (optimal: hit)", 1) in mistakes
    assert len(mistakes) == 3


def test_top_mistakes_limit():
    rows = [decision(total=t, taken="stand", optimal="hit") for t in range(5, 17)]
    assert len(top_mistakes(rows, limit=10)) == 10


# --- heatmap grid ----------------------------------------------------------------


def test_heatmap_row_label():
    assert heatmap_row_label(decision(total=12)) == "hard 12"
    assert heatmap_row_label(decision(cards=("A", "7"), total=18, soft=True)) == "soft 18"
    assert heatmap_row_label(decision(cards=("8", "8"), total=16, pair=True)) == "8,8"


def test_heatmap_row_labels_has_the_standard_rows_plus_any_extra_totals_seen():
    standard = heatmap_row_labels([])
    assert standard[0] == "hard 5" and "hard 20" in standard and "hard 4" not in standard
    assert "soft 13" in standard and "soft 20" in standard
    assert standard[-len(PAIR_ROWS):] == PAIR_ROWS
    # A hard 4 can come up after a split (2,2 that can't be split again).
    extended = heatmap_row_labels([decision(cards=("2", "2"), total=4)])
    assert extended[0] == "hard 4"


def test_accuracy_grid_keys_by_row_label_and_upcard():
    rows = [
        decision(total=12, upcard="4", taken="double", optimal="stand"),
        decision(total=12, upcard="4", taken="stand", optimal="stand"),
        decision(total=12, upcard="Q", taken="hit", optimal="hit"),
    ]
    grid = accuracy_grid(rows)
    assert (grid[("hard 12", "4")].k, grid[("hard 12", "4")].n) == (1, 2)
    assert grid[("hard 12", "10")].n == 1
    assert ("hard 13", "4") not in grid  # empty cells are simply missing


# --- misc + whole-run summary ------------------------------------------------------


def test_mean_of_field_skips_missing_values():
    rows = [decision(latency=1.0), decision(latency=3.0), {**decision(), "latency_s": None}]
    assert mean_of_field(rows, "latency_s") == 2.0
    assert math.isnan(mean_of_field([], "latency_s"))


def write_run(directory, decisions, hands, metadata):
    directory.mkdir()
    (directory / "decisions.jsonl").write_text("".join(json.dumps(r) + "\n" for r in decisions))
    (directory / "hands.jsonl").write_text("".join(json.dumps(r) + "\n" for r in hands))
    (directory / "metadata.json").write_text(json.dumps(metadata))


METADATA = {
    "run_id": "r1",
    "model": "fake:1b",
    "model_digest": "abc",
    "harness_config": "baseline",
    "prompt_version": "baseline-v2",
    "run_seed": 7,
}


def test_load_run_reads_all_three_files(tmp_path):
    rows = [{**decision(), "prompt_version": "baseline-v2"}]
    write_run(tmp_path / "run", rows, [hand(1, -1)], METADATA)
    run = load_run(tmp_path / "run")
    assert run.name == "run"
    assert run.decisions == rows
    assert run.hands == [hand(1, -1)]
    assert run.prompt_version == "baseline-v2"


def test_load_run_marks_a_missing_prompt_version_as_not_logged(tmp_path):
    metadata = {k: v for k, v in METADATA.items() if k != "prompt_version"}
    write_run(tmp_path / "old", [decision()], [hand(1, -1)], metadata)
    assert load_run(tmp_path / "old").prompt_version == "not logged"


def test_load_run_refuses_a_run_that_mixes_prompt_versions(tmp_path):
    rows = [{**decision(), "prompt_version": "a"}, {**decision(), "prompt_version": "b"}]
    write_run(tmp_path / "mixed", rows, [hand(1, -1)], METADATA)
    with pytest.raises(ValueError, match="prompt"):
        load_run(tmp_path / "mixed")


def test_summarize_run_headline_numbers(tmp_path):
    rows = [
        decision(hand_number=1, taken="hit", optimal="hit", latency=2.0, eval_count=40),
        decision(hand_number=1, taken="double", optimal="stand", latency=4.0, eval_count=60),
    ]
    hands = [hand(1, -2, num_decisions=2), hand(2, 1.5, num_decisions=0)]
    write_run(tmp_path / "run", rows, hands, METADATA)
    summary = summarize_run(load_run(tmp_path / "run"))
    assert (summary.accuracy.k, summary.accuracy.n) == (1, 2)
    assert summary.invalid.k == 0
    assert summary.returns.n == 2 and summary.returns.mean == pytest.approx(-0.25)
    assert summary.total_payout == pytest.approx(-0.5)
    assert summary.decisions_per_hand == 1.0
    assert summary.mean_latency_s == 3.0
    assert summary.mean_eval_count == 50.0
