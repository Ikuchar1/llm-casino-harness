"""Tests for per-decision / per-hand JSONL logging and resume (agent/run_log.py, agent/runner.py)."""

import dataclasses
import json

from agent.config import BASELINE, get_config
from agent.llm_player import LLMPlayer
from agent.ollama_client import ChatReply
from agent.prompt import ODDS_HEADER
import pytest

from agent.run_log import DECISION_FIELDS, HAND_FIELDS, RunInfo, RunWriter, check_resume_compatible
from agent.runner import run_hands

INFO = RunInfo(
    run_id="test_run",
    model="fake:1b",
    model_digest="sha256:abc",
    harness_config=BASELINE,
    run_seed=2026,
    ollama_seed=42,
    prompt_version="baseline-v2",
    parser_version="parser-v2",
)


class AlwaysReply:
    """Fake chat client that always gives the same reply."""

    model = "fake:1b"

    def __init__(self, reply: str):
        self.reply = reply
        self.calls = 0

    def chat(self, system, user):
        self.calls += 1
        return ChatReply(content=self.reply, done_reason="stop", eval_count=10, latency_s=0.25)


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def run(tmp_path, hands, reply="Thinking.\nACTION: stand"):
    writer = RunWriter(tmp_path)
    client = AlwaysReply(reply)
    run_hands(LLMPlayer(client, BASELINE), writer, INFO, hand_numbers=hands)
    return client


def test_runner_refuses_a_player_whose_config_differs_from_the_run_info(tmp_path):
    player = LLMPlayer(AlwaysReply("ACTION: stand"), get_config("prob"))
    with pytest.raises(ValueError, match="harness config"):
        run_hands(player, RunWriter(tmp_path), INFO, hand_numbers=[1])


def test_prob_run_logs_the_config_name_flags_and_odds_prompt(tmp_path):
    prob = get_config("prob")
    info = dataclasses.replace(INFO, harness_config=prob)
    run_hands(LLMPlayer(AlwaysReply("ACTION: stand"), prob), RunWriter(tmp_path), info, hand_numbers=range(1, 4))
    rows = read_jsonl(tmp_path / "decisions.jsonl")
    assert rows
    for row in rows:
        assert row["harness_config"] == "prob"
        assert row["harness_flags"]["probability_tool"] is True
        assert ODDS_HEADER in row["prompt"]["user"]
    assert {row["harness_config"] for row in read_jsonl(tmp_path / "hands.jsonl")} == {"prob"}


def test_every_decision_row_has_every_field(tmp_path):
    run(tmp_path, range(1, 11))
    rows = read_jsonl(tmp_path / "decisions.jsonl")
    assert rows, "expected at least one decision in 10 hands"
    for row in rows:
        assert set(DECISION_FIELDS) <= set(row), set(DECISION_FIELDS) - set(row)
    row = rows[0]
    assert row["run_id"] == "test_run"
    assert row["model"] == "fake:1b"
    assert row["model_digest"] == "sha256:abc"
    assert row["harness_config"] == "baseline"
    assert row["harness_flags"] == BASELINE.flags()
    assert row["prompt_version"] == "baseline-v2"
    assert row["parser_version"] == "parser-v2"
    assert row["prompt"]["user"].startswith("Your cards:")
    assert "ACTION:" in row["prompt"]["system"]
    assert row["raw_response"] == "Thinking.\nACTION: stand"
    assert row["parsed_action"] == "stand"
    assert row["action_taken"] == "stand"
    assert row["invalid"] is False
    assert row["correct"] == (row["optimal_action"] == "stand")
    assert row["chart_code"] in {"H", "S", "Dh", "Ds", "P"}


def test_every_hand_row_has_every_field_and_hand_numbers_start_at_one(tmp_path):
    run(tmp_path, range(1, 11))
    hands = read_jsonl(tmp_path / "hands.jsonl")
    assert [h["hand_number"] for h in hands] == list(range(1, 11))
    for hand in hands:
        assert set(HAND_FIELDS) <= set(hand), set(HAND_FIELDS) - set(hand)


def test_decision_rows_carry_the_hands_final_payout(tmp_path):
    run(tmp_path, range(1, 21))
    hands = {h["hand_number"]: h for h in read_jsonl(tmp_path / "hands.jsonl")}
    for row in read_jsonl(tmp_path / "decisions.jsonl"):
        assert row["hand_payout"] == hands[row["hand_number"]]["payout"]
        assert row["sub_hand_result"] in {"win", "loss", "push"}


def test_invalid_reply_is_logged_unambiguously(tmp_path):
    run(tmp_path, range(1, 11), reply="I'd stand.")
    rows = read_jsonl(tmp_path / "decisions.jsonl")
    assert rows
    for row in rows:
        assert row["invalid"] is True
        assert row["invalid_reason"] == "no_action"
        assert row["parsed_action"] is None
        assert row["action_taken"] == "stand"
        assert row["correct"] is False


def test_resume_skips_finished_hands_and_appends(tmp_path):
    run(tmp_path, range(1, 6))
    first_decisions = len(read_jsonl(tmp_path / "decisions.jsonl"))

    client = run(tmp_path, range(1, 11))  # same out dir, more hands

    hands = read_jsonl(tmp_path / "hands.jsonl")
    assert [h["hand_number"] for h in hands] == list(range(1, 11))
    rows = read_jsonl(tmp_path / "decisions.jsonl")
    assert len(rows) > first_decisions
    assert client.calls == len(rows) - first_decisions  # hands 1-5 were not replayed


def test_resume_drops_decisions_of_a_hand_that_never_finished_and_a_partial_line(tmp_path):
    run(tmp_path, range(1, 3))
    with open(tmp_path / "decisions.jsonl", "a") as f:
        f.write(json.dumps({"hand_number": 3, "orphan": True}) + "\n")
        f.write('{"hand_number": 4, "trunc')  # crash mid-write

    writer = RunWriter(tmp_path)
    assert writer.completed_hands() == {1, 2}
    rows = read_jsonl(tmp_path / "decisions.jsonl")
    assert all(r["hand_number"] in {1, 2} for r in rows)


# --- Resume compatibility ------------------------------------------------------------

EXPECTED = {
    "model": "qwen2.5:7b",
    "run_seed": 2026,
    "harness_config": "baseline",
    "prompt_version": "baseline-v2",
    "parser_version": "parser-v2",
}


def test_matching_metadata_can_resume():
    check_resume_compatible(dict(EXPECTED, started_at="x"), EXPECTED)


def test_different_prompt_version_cannot_resume():
    with pytest.raises(ValueError, match="prompt_version"):
        check_resume_compatible(dict(EXPECTED, prompt_version="baseline-v1"), EXPECTED)


def test_v1_run_without_prompt_version_cannot_resume():
    old = {k: v for k, v in EXPECTED.items() if k != "prompt_version"}
    with pytest.raises(ValueError, match="prompt_version=None"):
        check_resume_compatible(old, EXPECTED)


def test_different_seed_cannot_resume():
    with pytest.raises(ValueError, match="run_seed"):
        check_resume_compatible(dict(EXPECTED, run_seed=1), EXPECTED)


def test_different_parser_version_cannot_resume():
    with pytest.raises(ValueError, match="parser_version"):
        check_resume_compatible(dict(EXPECTED, parser_version="parser-v1"), EXPECTED)
