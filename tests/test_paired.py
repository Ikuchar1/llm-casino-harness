"""Tests for paired config-vs-baseline statistics (analysis/paired.py)."""

import math

import pytest

from analysis.loading import Run
from analysis.paired import (
    PairingError,
    accuracy_by_coverage,
    compare_to_baseline,
    exact_mcnemar_p,
    first_decisions,
    flip_stats,
    holm_adjust,
    later_decisions,
    newcombe_paired_diff_ci,
    pair_runs,
    run_kind,
)
from analysis.stats import wilson_interval

# --- synthetic runs -----------------------------------------------------------------

# One fixed spot per hand: hard 16 vs 10, where hit is correct and stand is wrong.
CARDS = ["10", "6"]
UPCARD = "10"


def row(hand_number, correct, index=0, invalid=False, scenario_id=None, cards=CARDS, upcard=UPCARD, **extra):
    taken = "stand" if invalid else ("hit" if correct else "stand")
    r = {
        "hand_number": hand_number,
        "decision_index": index,
        "split_hand_index": 0,
        "from_split": False,
        "player_cards": list(cards),
        "total": 16,
        "is_soft": False,
        "is_pair": False,
        "dealer_upcard": upcard,
        "legal_actions": ["hit", "stand", "double"],
        "action_taken": taken,
        "parsed_action": None if invalid else taken,
        "optimal_action": "hit",
        "correct": bool(correct) and not invalid,
        "invalid": invalid,
        "invalid_reason": "no_action" if invalid else None,
    }
    if scenario_id is not None:
        r["run_type"] = "scenario"
        r["scenario_id"] = scenario_id
        r["is_scenario_cell"] = index == 0
    r.update(extra)
    return r


def natural_run(correct_flags, name="run", model="qwen2.5:7b", seed=2026, config="baseline", extra_rows=(),
                n_hands=None):
    """One decision per hand; correct_flags[i] is hand i+1's first-decision correctness (None = no decision)."""
    decisions = [row(i + 1, flag) for i, flag in enumerate(correct_flags) if flag is not None]
    decisions += list(extra_rows)
    decisions.sort(key=lambda r: (r["hand_number"], r["decision_index"]))
    n = n_hands if n_hands is not None else len(correct_flags)
    hands = [{"hand_number": i + 1, "payout": 0} for i in range(n)]
    metadata = {"model": model, "run_seed": seed, "harness_config": config, "n_hands": n}
    return Run(name=name, metadata=metadata, decisions=decisions, hands=hands)


def scenario_run(cells, name="scen", model="qwen2.5:7b", seed=2026, config="baseline"):
    """cells: {scenario_id: correct}. Each scenario also gets a later (non-cell) decision that is correct."""
    decisions, hands = [], []
    for number, (sid, flag) in enumerate(cells.items(), start=1):
        decisions.append(row(number, flag, scenario_id=sid))
        decisions.append(row(number, True, index=1, scenario_id=sid))
        hands.append({"hand_number": number, "payout": 0, "run_type": "scenario", "scenario_id": sid})
    metadata = {"model": model, "run_seed": seed, "harness_config": config, "run_type": "scenario",
                "scenario_set_version": "scenarios-v1"}
    return Run(name=name, metadata=metadata, decisions=decisions, hands=hands)


def flags(a, b, c, d):
    """Baseline and config correctness lists with a both-right, b base-only, c config-only, d both-wrong."""
    base = [True] * a + [True] * b + [False] * c + [False] * d
    conf = [True] * a + [False] * b + [True] * c + [False] * d
    return base, conf


# --- exact McNemar ------------------------------------------------------------------


def test_exact_mcnemar_known_values():
    assert exact_mcnemar_p(0, 6) == pytest.approx(2 / 64)
    assert exact_mcnemar_p(6, 0) == pytest.approx(2 / 64)
    assert exact_mcnemar_p(1, 9) == pytest.approx(22 / 1024)
    assert exact_mcnemar_p(5, 5) == 1.0
    assert exact_mcnemar_p(0, 0) == 1.0


def test_exact_mcnemar_never_exceeds_one():
    assert exact_mcnemar_p(4, 5) == 1.0


# --- Holm ---------------------------------------------------------------------------


def test_holm_known_values_in_original_order():
    assert holm_adjust([0.01, 0.04, 0.03]) == pytest.approx([0.03, 0.06, 0.06])


def test_holm_is_monotone_and_capped():
    adjusted = holm_adjust([0.5, 0.001, 0.2, 0.04])
    # sorted: 0.001*4=0.004, 0.04*3=0.12, 0.2*2=0.4, 0.5*1=0.5
    assert adjusted == pytest.approx([0.5, 0.004, 0.4, 0.12])
    assert holm_adjust([0.9, 0.8]) == pytest.approx([1.0, 1.0])


def test_holm_single_and_empty():
    assert holm_adjust([0.02]) == pytest.approx([0.02])
    assert holm_adjust([]) == []


# --- paired CI ----------------------------------------------------------------------


def test_newcombe_matches_hand_computation():
    a, b, c, d = 30, 5, 12, 3
    n = a + b + c + d
    p1, p2 = (a + c) / n, (a + b) / n
    l1, u1 = wilson_interval(a + c, n)
    l2, u2 = wilson_interval(a + b, n)
    phi = (a * d - b * c) / math.sqrt((a + b) * (c + d) * (a + c) * (b + d))
    low = (p1 - p2) - math.sqrt((p1 - l1) ** 2 - 2 * phi * (p1 - l1) * (u2 - p2) + (u2 - p2) ** 2)
    high = (p1 - p2) + math.sqrt((u1 - p1) ** 2 - 2 * phi * (u1 - p1) * (p2 - l2) + (p2 - l2) ** 2)
    assert newcombe_paired_diff_ci(a, b, c, d) == pytest.approx((low, high))


def test_newcombe_no_discordant_pairs_contains_zero():
    low, high = newcombe_paired_diff_ci(40, 0, 0, 10)
    assert low <= 0 <= high


def test_newcombe_stays_in_range_and_brackets_estimate():
    low, high = newcombe_paired_diff_ci(0, 0, 20, 0)
    assert -1 <= low <= 1.0 <= high <= 1.0
    low, high = newcombe_paired_diff_ci(10, 2, 8, 5)
    assert low < 6 / 25 < high


def test_newcombe_empty_is_nan():
    assert all(math.isnan(x) for x in newcombe_paired_diff_ci(0, 0, 0, 0))


# --- pairing ------------------------------------------------------------------------


def test_run_kind_detection():
    assert run_kind(natural_run([True])) == "natural"
    assert run_kind(scenario_run({"hard16_vs_10": True})) == "scenario"


def test_natural_pairs_only_first_decision_of_each_hand():
    later = row(1, False, index=1)
    run = natural_run([True, False], extra_rows=[later])
    firsts = first_decisions(run)
    assert set(firsts) == {1, 2}
    assert firsts[1]["decision_index"] == 0


def test_scenario_pairs_on_scenario_id():
    base = scenario_run({"hard16_vs_10": True, "hard12_vs_2": False})
    conf = scenario_run({"hard12_vs_2": True, "hard16_vs_10": True}, config="prob")  # different order
    pairs = pair_runs(base, conf)
    assert [p.key for p in pairs.pairs] == ["hard12_vs_2", "hard16_vs_10"]
    assert pairs.pairs[0].baseline["correct"] is False and pairs.pairs[0].config["correct"] is True


def test_pairing_refuses_different_models():
    with pytest.raises(PairingError, match="model"):
        pair_runs(natural_run([True]), natural_run([True], model="qwen2.5:14b"))


def test_pairing_refuses_different_seeds():
    with pytest.raises(PairingError, match="seed"):
        pair_runs(natural_run([True]), natural_run([True], seed=7))


# Stack fields as an HCC run records them (top level, plus "where" per session).
STACK = {
    "model_digest": "845dbda0ea48",
    "prompt_version": "baseline-v3",
    "parser_version": "parser-v2",
    "ollama_version": "0.35.0",
    "ollama_options": {"temperature": 0, "seed": 42, "num_predict": 400},
    "gpus": ["Tesla P100-PCIE-16GB"],
}


def stacked_run(name="run", sessions=None, **overrides):
    run = natural_run([True], name=name)
    run.metadata.update(STACK)
    run.metadata.update(overrides)
    gpus = run.metadata.get("gpus")
    run.metadata["sessions"] = sessions if sessions is not None else [
        {"status": "completed", "hostname": f"{name}-node", "slurm_job_id": f"{name}-job", "gpus": gpus}]
    run.metadata["hostname"], run.metadata["slurm_job_id"] = f"{name}-node", f"{name}-job"
    return run


def test_pairing_accepts_same_stack_on_different_nodes_and_jobs():
    pairs = pair_runs(stacked_run("base"), stacked_run("conf"))
    assert len(pairs.pairs) == 1


def test_pairing_accepts_equal_ollama_options_in_another_key_order():
    options = {"num_predict": 400, "seed": 42, "temperature": 0}
    assert len(pair_runs(stacked_run("base"), stacked_run("conf", ollama_options=options)).pairs) == 1


@pytest.mark.parametrize("field, value, label", [
    ("model_digest", "deadbeef", "model digest"),
    ("prompt_version", "baseline-v2", "prompt version"),
    ("parser_version", "parser-v1", "parser version"),
    ("ollama_version", "0.36.0", "Ollama version"),
    ("ollama_options", {"temperature": 0, "seed": 7, "num_predict": 400}, "Ollama options"),
    ("gpus", ["Tesla V100-PCIE-32GB"], "GPUs"),
])
def test_pairing_refuses_a_different_stack_field(field, value, label):
    with pytest.raises(PairingError, match=label):
        pair_runs(stacked_run("base"), stacked_run("conf", **{field: value}))


def test_pairing_refuses_a_session_on_a_different_gpu():
    sessions = [{"status": "interrupted", "gpus": ["Tesla V100-PCIE-32GB"]},
                {"status": "completed", "gpus": ["Tesla P100-PCIE-16GB"]}]
    with pytest.raises(PairingError, match="GPUs"):
        pair_runs(stacked_run("base"), stacked_run("conf", sessions=sessions))


@pytest.mark.parametrize("field", list(STACK))
def test_pairing_skips_a_stack_field_missing_on_one_side(field):
    old = stacked_run("base")
    del old.metadata[field]
    if field == "gpus":
        old.metadata["sessions"] = [{"status": "completed"}]
    assert len(pair_runs(old, stacked_run("conf")).pairs) == 1
    assert len(pair_runs(stacked_run("conf"), old).pairs) == 1


def test_pairing_skips_gpus_recorded_as_none():
    mac = stacked_run("base", gpus=None)
    assert len(pair_runs(mac, stacked_run("conf")).pairs) == 1


def test_pairing_refuses_different_hand_counts():
    with pytest.raises(PairingError, match="hand"):
        pair_runs(natural_run([True, True]), natural_run([True, True, True]))


def test_pairing_refuses_natural_vs_scenario():
    with pytest.raises(PairingError, match="scenario"):
        pair_runs(natural_run([True]), scenario_run({"hard16_vs_10": True}))


def test_pairing_refuses_different_scenario_cells():
    with pytest.raises(PairingError, match="scenario"):
        pair_runs(scenario_run({"a": True, "b": True}), scenario_run({"a": True, "c": True}))


def test_pairing_refuses_different_cards_on_a_paired_hand():
    base = natural_run([True])
    conf = natural_run([True])
    conf.decisions[0]["player_cards"] = ["9", "7"]
    with pytest.raises(PairingError, match="cards"):
        pair_runs(base, conf)


def test_hands_missing_a_first_decision_on_one_side_are_dropped_and_counted():
    base = natural_run([True, True, None, True])
    conf = natural_run([True, None, None, False])
    pairs = pair_runs(base, conf)
    assert [p.key for p in pairs.pairs] == [1, 4]
    assert pairs.dropped == 1  # hand 2: config has no decision
    assert pairs.no_decision == 1  # hand 3: neither side decided (e.g. a blackjack)


# --- comparison ---------------------------------------------------------------------


def test_compare_counts_discordant_pairs_and_p_value():
    base_flags, conf_flags = flags(a=10, b=1, c=9, d=4)
    result = compare_to_baseline(natural_run(base_flags), natural_run(conf_flags, config="prob"))
    assert (result.n, result.a, result.b, result.c, result.d) == (24, 10, 1, 9, 4)
    assert result.baseline_accuracy.rate == pytest.approx(11 / 24)
    assert result.config_accuracy.rate == pytest.approx(19 / 24)
    assert result.difference == pytest.approx(8 / 24)
    assert result.p_value == pytest.approx(22 / 1024)
    assert result.ci_low < result.difference < result.ci_high
    assert result.config_name == "prob"
    assert result.kind == "natural"


def test_compare_reports_invalid_counts_and_ev_loss_change():
    base = natural_run([True, True, True])
    conf = natural_run([True, True, True], config="prob")
    conf.decisions[0].update(invalid=True, correct=False, action_taken="stand", parsed_action=None)
    conf.decisions[1].update(correct=False, action_taken="stand")
    result = compare_to_baseline(base, conf)
    assert result.baseline_invalid == 0 and result.config_invalid == 1
    assert result.baseline_ev_loss == pytest.approx(0)
    assert result.ev_loss_change > 0  # standing on 16 vs 10 costs EV
    assert result.ev_loss_change == pytest.approx(result.config_ev_loss - result.baseline_ev_loss)


def test_compare_uses_the_graded_final_correctness_for_self_eval():
    base = natural_run([False])
    conf = natural_run([True], config="self")
    conf.decisions[0]["self_eval"] = {"first_action": "stand", "first_valid": True, "first_correct": False,
                                      "second_action": "hit", "second_valid": True, "final_action": "hit",
                                      "flipped": True}
    result = compare_to_baseline(base, conf)
    assert (result.b, result.c) == (0, 1)


# --- later decisions, coverage, flips -----------------------------------------------


def test_later_decisions_are_the_non_first_decisions():
    run = natural_run([True, True], extra_rows=[row(1, False, index=1), row(2, True, index=1)])
    assert (later_decisions(run).k, later_decisions(run).n) == (1, 2)
    scen = scenario_run({"a": False, "b": False})
    assert (later_decisions(scen).k, later_decisions(scen).n) == (2, 2)


def test_accuracy_by_coverage_uses_the_injected_classifier():
    rows = [row(1, True, upcard="10"), row(2, False, upcard="10"), row(3, True, upcard="6"), row(4, True, upcard="6")]
    covered, uncovered = accuracy_by_coverage(rows, lambda r: r["dealer_upcard"] == "6")
    assert (covered.k, covered.n) == (2, 2)
    assert (uncovered.k, uncovered.n) == (1, 2)


def _self_eval_row(hand, first_correct, final_correct, flipped, second_valid=True):
    r = row(hand, final_correct)
    r["self_eval"] = {
        "first_action": "hit" if first_correct else "stand",
        "first_valid": True,
        "first_correct": first_correct,
        "second_action": r["action_taken"] if second_valid else None,
        "second_valid": second_valid,
        "final_action": r["action_taken"],
        "flipped": flipped,
    }
    return r


def test_flip_stats_counts_fixes_breaks_and_neutral_flips():
    rows = [
        _self_eval_row(1, first_correct=False, final_correct=True, flipped=True),  # fix
        _self_eval_row(2, first_correct=False, final_correct=True, flipped=True),  # fix
        _self_eval_row(3, first_correct=True, final_correct=False, flipped=True),  # break
        _self_eval_row(4, first_correct=False, final_correct=False, flipped=True),  # neutral (wrong -> wrong)
        _self_eval_row(5, first_correct=True, final_correct=True, flipped=False),  # kept
        _self_eval_row(6, first_correct=True, final_correct=True, flipped=False, second_valid=False),
        row(7, True),  # no self_eval: not counted
    ]
    stats = flip_stats(rows)
    assert stats.n == 6
    assert stats.flips == 4
    assert stats.fixes == 2
    assert stats.breaks == 1
    assert stats.neutral == 1
    assert stats.second_invalid == 1
    assert stats.first_accuracy.k == 3 and stats.final_accuracy.k == 4


def test_flip_stats_without_self_eval_rows_is_empty():
    assert flip_stats([row(1, True)]).n == 0
