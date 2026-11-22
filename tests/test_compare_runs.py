"""Tests for scripts/compare_runs.py on tiny hand-made run directories."""

import importlib.util
import json
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "compare_runs.py"


def load_script():
    spec = importlib.util.spec_from_file_location("compare_runs_script", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


META = {
    "model": "qwen2.5:7b",
    "model_digest": "845dbda0ea48ed749caafd9e6037047aa19acfcfd82e704d7ca97d631a0b697e",
    "prompt_version": "baseline-v2",
    "parser_version": "parser-v2",
    "ollama_version": "0.35.0",
}


def dec(hand, idx, action, reply=None, cards=("10", "6"), upcard="10", correct=False):
    return {
        "hand_number": hand,
        "decision_index": idx,
        "player_cards": list(cards),
        "dealer_upcard": upcard,
        "action_taken": action,
        "raw_response": reply if reply is not None else f"Reasoning.\nACTION: {action}",
        "correct": correct,
    }


def write_run(path, decisions, payouts, metadata=META):
    path.mkdir(parents=True)
    (path / "metadata.json").write_text(json.dumps(metadata))
    (path / "decisions.jsonl").write_text("".join(json.dumps(d) + "\n" for d in decisions))
    hands = [{"hand_number": i + 1, "payout": p} for i, p in enumerate(payouts)]
    (path / "hands.jsonl").write_text("".join(json.dumps(h) + "\n" for h in hands))
    return path


BASE = [
    dec(1, 0, "hit"),
    dec(1, 1, "stand", cards=("10", "6", "2")),
    dec(2, 0, "stand", correct=True),
]


def compare(tmp_path, a_rows, b_rows, a_pay=(1, -1), b_pay=(1, -1), b_meta=META):
    mod = load_script()
    a = write_run(tmp_path / "a", a_rows, a_pay)
    b = write_run(tmp_path / "b", b_rows, b_pay, b_meta)
    return mod.compare(mod.load(a), mod.load(b))


def test_same_run_is_identical(tmp_path):
    result = compare(tmp_path, BASE, BASE)
    assert result.verdict() == "IDENTICAL"
    assert (result.n_a, result.n_b, result.aligned, result.same_action, result.same_reply) == (3, 3, 3, 3, 3)
    assert result.not_comparable == 0


def test_reply_wording_differs_but_actions_match(tmp_path):
    b = [dict(BASE[0], raw_response="Other words.\nACTION: hit"), BASE[1], BASE[2]]
    result = compare(tmp_path, BASE, b)
    assert result.verdict() == "SAME ACTIONS"
    assert result.same_action == 3 and result.same_reply == 2


def test_divergence_stops_comparison_within_that_hand(tmp_path):
    # Hand 1 diverges at decision 0, so decision 1 (different cards) is not comparable.
    b = [dec(1, 0, "stand"), dec(1, 1, "stand", cards=("10", "6", "9")), BASE[2]]
    result = compare(tmp_path, BASE, b)
    assert result.compared == 2
    assert result.same_action == 1
    assert result.not_comparable == 2  # hand 1 decision 1 in each run
    assert result.verdict() == "DIVERGES (1 of 2 compared actions differ)"
    [first] = result.divergences
    assert (first.hand, first.index, first.action_a, first.action_b) == (1, 0, "hit", "stand")


def test_extra_decision_in_one_run_is_unmatched_and_diverges(tmp_path):
    # B stood at decision 0 of hand 1 too, but A has one more decision: an unmatched row.
    result = compare(tmp_path, BASE, [BASE[0], BASE[2]])
    assert result.aligned == 2 and result.unmatched == 1
    assert result.verdict().startswith("DIVERGES")


def test_report_text_has_header_counts_divergence_and_summary(tmp_path):
    mod = load_script()
    b_meta = {**META, "ollama_version": "0.15.1", "platform": "Linux x86_64"}
    b_rows = [dec(1, 0, "double", correct=False), BASE[2]]
    a = write_run(tmp_path / "a", BASE, (1, -1))
    b = write_run(tmp_path / "b", b_rows, (-2, -1), b_meta)
    text = mod.report(mod.load(a), mod.load(b))
    assert "845dbda0ea48" in text
    assert "baseline-v2" in text and "parser-v2" in text
    assert "0.35.0" in text and "0.15.1" in text
    assert "Linux x86_64" in text and "not recorded" in text  # A has no platform info
    assert "hand 1 decision 0: 10,6 vs 10: hit vs double" in text
    assert "accuracy 33.3% (1/3), payout +0" in text  # run A
    assert "accuracy 50.0% (1/2), payout -3" in text  # run B
    assert text.strip().splitlines()[-1].startswith("Verdict: DIVERGES")


def test_main_exit_code(tmp_path, capsys):
    mod = load_script()
    a = write_run(tmp_path / "a", BASE, (1, -1))
    assert mod.main([str(a), str(a)]) == 0
    assert "Verdict: IDENTICAL" in capsys.readouterr().out
    b = write_run(tmp_path / "b", [dec(1, 0, "stand")], (1, -1))
    assert mod.main([str(a), str(b)]) == 1
