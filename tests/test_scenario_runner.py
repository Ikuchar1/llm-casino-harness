"""End-to-end tests for playing the scenario set with a fake LLM client (agent/scenario_runner.py)."""

import json

from agent.config import BASELINE
from agent.llm_player import LLMPlayer
from agent.ollama_client import ChatReply
from agent.run_log import DECISION_FIELDS, HAND_FIELDS, RunInfo, RunWriter
from agent.scenario_runner import run_scenarios
from agent.scenarios import build_scenarios, scenario_shoe_seed

INFO = RunInfo(
    run_id="test_scenarios",
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


def run(tmp_path, scenarios, reply="Thinking.\nACTION: hit"):
    client = AlwaysReply(reply)
    run_scenarios(LLMPlayer(client, BASELINE), RunWriter(tmp_path), INFO, scenarios)
    return client


def test_scenario_runner_refuses_a_player_whose_config_differs_from_the_run_info(tmp_path):
    import pytest

    from agent.config import get_config

    player = LLMPlayer(AlwaysReply("ACTION: stand"), get_config("prob"))
    with pytest.raises(ValueError, match="harness config"):
        run_scenarios(player, RunWriter(tmp_path), INFO, build_scenarios()[:1])


def test_rows_have_baseline_fields_plus_scenario_fields(tmp_path):
    scenarios = build_scenarios()[:12]
    run(tmp_path, scenarios)
    rows = read_jsonl(tmp_path / "decisions.jsonl")
    hands = read_jsonl(tmp_path / "hands.jsonl")
    assert rows
    for row in rows:
        assert set(DECISION_FIELDS) <= set(row)
        assert row["run_type"] == "scenario"
    for hand in hands:
        assert set(HAND_FIELDS) <= set(hand)
        assert hand["run_type"] == "scenario"
    assert [h["hand_number"] for h in hands] == list(range(1, 13))
    assert [h["scenario_id"] for h in hands] == [s.scenario_id for s in scenarios]
    assert hands[0]["shoe_seed"] == scenario_shoe_seed(2026, scenarios[0].scenario_id)


def test_only_the_first_decision_of_each_hand_is_the_scenario_cell(tmp_path):
    scenarios = build_scenarios()[:30]
    run(tmp_path, scenarios)  # always hitting gives many multi-decision hands
    rows = read_jsonl(tmp_path / "decisions.jsonl")
    by_number = {i: s for i, s in enumerate(scenarios, start=1)}

    cells = [row for row in rows if row["is_scenario_cell"]]
    assert len(cells) == len(scenarios)  # exactly one graded cell per scenario
    assert any(not row["is_scenario_cell"] for row in rows)  # later decisions exist and are flagged
    for row in rows:
        scenario = by_number[row["hand_number"]]
        assert row["scenario_id"] == scenario.scenario_id
        assert row["is_scenario_cell"] == (row["decision_index"] == 0)
        if row["is_scenario_cell"]:
            assert tuple(row["player_cards"]) == scenario.player_cards
            assert row["dealer_upcard"] == scenario.dealer_upcard


def test_pair_scenario_cell_is_graded_on_the_pair_row(tmp_path):
    pair8_vs_A = next(s for s in build_scenarios() if s.scenario_id == "pair8_vs_A")
    run(tmp_path, [pair8_vs_A], reply="ACTION: split")
    first = read_jsonl(tmp_path / "decisions.jsonl")[0]
    assert first["is_pair"] is True
    assert first["chart_code"] == "P"
    assert first["correct"] is True


def test_resume_skips_finished_scenarios_and_appends(tmp_path):
    scenarios = build_scenarios()
    run(tmp_path, scenarios[:5])
    first_decisions = len(read_jsonl(tmp_path / "decisions.jsonl"))

    client = run(tmp_path, scenarios[:10])  # same dir, bigger limit

    hands = read_jsonl(tmp_path / "hands.jsonl")
    assert [h["hand_number"] for h in hands] == list(range(1, 11))
    rows = read_jsonl(tmp_path / "decisions.jsonl")
    assert client.calls == len(rows) - first_decisions  # scenarios 1-5 were not replayed


def test_resume_replays_an_interrupted_scenario(tmp_path):
    scenarios = build_scenarios()[:3]
    run(tmp_path, scenarios)
    decisions_path = tmp_path / "decisions.jsonl"
    hands_path = tmp_path / "hands.jsonl"
    full_rows = read_jsonl(decisions_path)

    # Pretend the run crashed while writing scenario 3: its hand row never landed.
    hand_lines = hands_path.read_text().splitlines()
    hands_path.write_text("\n".join(hand_lines[:2]) + "\n")

    run(tmp_path, scenarios)
    assert [h["hand_number"] for h in read_jsonl(hands_path)] == [1, 2, 3]
    rows = read_jsonl(decisions_path)
    assert len(rows) == len(full_rows)  # no duplicated decisions for scenario 3
    assert [r["scenario_id"] for r in rows] == [r["scenario_id"] for r in full_rows]


def test_progress_callback_counts_scenarios(tmp_path):
    seen = []
    client = AlwaysReply("ACTION: stand")
    run_scenarios(LLMPlayer(client, BASELINE), RunWriter(tmp_path), INFO, build_scenarios()[:4], on_hand=seen.append)
    assert [p.hand_number for p in seen] == [1, 2, 3, 4]
    assert seen[-1].hands_done == 4 and seen[-1].hands_total == 4
    assert seen[-1].decisions == 4  # standing ends every hand after one decision
