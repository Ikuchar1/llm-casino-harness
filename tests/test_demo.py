"""Tests for the showcase demo: the export, engine parity (Python and demo/engine.js), and the server."""

import glob
import importlib.util
import json
import os
import random
import shutil
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from agent.ollama_client import ChatReply
from agent.scenarios import build_scenarios, forced_shoe
from blackjack.cards import make_shoe_for_hand
from blackjack.engine import play_hand

ROOT = Path(__file__).resolve().parent.parent
DEMO_DATA = ROOT / "demo" / "demo_data.json"
REPLAY_JS = ROOT / "tests" / "js" / "replay.js"


def load(name):
    spec = importlib.util.spec_from_file_location(f"{name}_script", ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


export = load("export_demo_data")
server_mod = load("demo_server")


# ---------- fake runs made by the real scenario runner ----------


class FakeClient:
    """Stands in for OllamaClient: always stands, and keeps standing when re-asked."""

    def __init__(self, model):
        self.model = model

    def chat(self, system, user):
        return ChatReply(content="I'll stand.\nACTION: stand", done_reason="stop", eval_count=5, latency_s=0.1)

    def chat_messages(self, messages):
        return ChatReply(content="Checked again.\nACTION: stand", done_reason="stop", eval_count=6, latency_s=0.2)


def make_run(tmp_path, monkeypatch, name, config, limit):
    runner = load("run_scenarios")
    monkeypatch.setattr(runner, "OllamaClient", FakeClient)
    monkeypatch.setattr(runner, "get_model_digest", lambda model: "sha256:fake")
    monkeypatch.setattr(runner, "get_ollama_version", lambda: "0.0-test")
    out = tmp_path / name
    monkeypatch.setattr(sys, "argv", ["run_scenarios.py", "--seed", "2026", "--out", str(out),
                                      "--limit", str(limit), "--config", config])
    assert runner.main() == 0
    return out


@pytest.fixture
def runs(tmp_path, monkeypatch):
    baseline = make_run(tmp_path, monkeypatch, "baseline", "baseline", 6)
    full = make_run(tmp_path, monkeypatch, "full", "prob_strat_self", 3)
    return baseline, full


def test_export_marks_unplayed_scenarios_pending(runs):
    baseline, full = runs
    data = export.build_demo_data(baseline, full)
    assert data["format"] == "demo-data-v1"
    assert data["counts"] == {"scenarios": 330, "ready": 3, "baseline_answered": 6, "full_answered": 3}
    scenarios = data["scenarios"]
    assert [s["ready"] for s in scenarios[:7]] == [True, True, True, False, False, False, False]
    assert scenarios[3]["seats"]["baseline"]["status"] == "answered"
    assert scenarios[3]["seats"]["full"] == {"status": "pending"}
    assert data["sources"]["baseline"]["status"] == "completed"
    assert data["sources"]["full"]["harness_config"] == "prob_strat_self"
    assert data["sources"]["full"]["self_eval_version"] == "self-eval-v2"
    assert data["sources"]["baseline"]["run_id"].startswith("scenarios_baseline_")


def test_export_writes_the_deal_basic_strategy_and_forced_shoe(runs):
    data = export.build_demo_data(*runs)
    for scenario, entry in zip(build_scenarios(), data["scenarios"]):
        shoe = forced_shoe(scenario, 2026, 6)
        assert export.decode_shoe(entry["shoe"]) == shoe
        assert entry["player"] == list(scenario.player_cards) and entry["upcard"] == scenario.dealer_upcard
        assert entry["hole"] == shoe[3]
        assert entry["basic"] in entry["legal"]
        assert ("split" in entry["legal"]) == (scenario.kind == "pair")
    hard16_10 = next(s for s in data["scenarios"] if s["id"] == "hard16_vs_10")
    assert (hard16_10["label"], hard16_10["basic"], hard16_10["total"]) == ("Hard 16", "hit", 16)
    assert next(s for s in data["scenarios"] if s["id"] == "pairA_vs_6")["label"] == "Pair of aces"


def test_export_keeps_answer_reasoning_odds_and_self_eval(runs):
    data = export.build_demo_data(*runs)
    first = data["scenarios"][0]  # hard 5 vs 2: standing is wrong
    base, full = first["seats"]["baseline"], first["seats"]["full"]
    assert (base["action"], base["correct"], base["invalid"]) == ("stand", False, False)
    assert "ACTION: stand" in base["reasoning"]
    assert "odds_text" not in base
    assert full["odds_text"].startswith("Odds (worked out from the cards left in the shoe):")
    assert set(full["odds"]) >= {"bust_if_hit", "dealer", "stand"}
    assert full["self_eval"]["first_action"] == "stand" and full["self_eval"]["second_action"] == "stand"
    assert full["reasoning"].startswith("Checked again.")
    assert full["result"]["player_hands"][0]["cards"] == first["player"]
    assert full["decisions"][0]["taken"] == "stand"


def test_export_survives_a_run_that_is_still_writing(runs, tmp_path):
    baseline, full = runs
    # A hand still being played: decision rows with no hands.jsonl row, then a half-written line.
    rows = (full / "decisions.jsonl").read_text().splitlines()
    orphan = json.loads(rows[0])
    orphan.update(hand_number=4, scenario_id="hard5_vs_5", decision_index=0)
    with (full / "decisions.jsonl").open("a") as handle:
        handle.write(json.dumps(orphan) + "\n" + '{"hand_number": 4, "scen')
    data = export.build_demo_data(baseline, full)
    assert data["counts"]["full_answered"] == 3
    assert data["scenarios"][3]["seats"]["full"] == {"status": "pending"}


def test_export_with_a_missing_run_folder_marks_everything_pending(runs, tmp_path):
    baseline, _ = runs
    data = export.build_demo_data(baseline, tmp_path / "not_started")
    assert data["counts"]["full_answered"] == 0 and data["counts"]["ready"] == 0
    assert data["sources"]["full"]["status"] == "missing"


def test_export_refuses_a_run_with_another_seed(runs):
    with pytest.raises(ValueError, match="run seed"):
        export.build_demo_data(*runs, seed=7)


def test_export_cli_writes_the_file(runs, tmp_path, capsys):
    out = tmp_path / "demo" / "demo_data.json"
    baseline, full = runs
    assert export.main(["--baseline", str(baseline), "--full", str(full), "--out", str(out)]) == 0
    assert json.loads(out.read_text())["counts"]["ready"] == 3
    assert "ready (both seats answered): 3/330" in capsys.readouterr().out


def test_parse_odds_reads_every_number():
    block = (
        "Odds (worked out from the cards left in the shoe):\n"
        "- If you hit once: 62.5% chance to bust.\n"
        "- Dealer final total (no blackjack): 17: 12.0%, 18: 13.4%, 19: 13.0%, 20: 30.5%, 21: 9.0%, bust: 22.1%.\n"
        "- If you stand now: win 22.1%, push 0.0%, lose 77.9%."
    )
    assert export.odds_block("Your hand: 16\n" + block + "\nPick one.") == block
    odds = export.parse_odds(block)
    assert odds["bust_if_hit"] == 62.5
    assert odds["dealer"][0] == ["17", 12.0] and odds["dealer"][-1] == ["bust", 22.1]
    assert odds["dealer_no_blackjack"] is True
    assert odds["stand"] == {"win": 22.1, "push": 0.0, "lose": 77.9}


# ---------- parity: replaying recorded moves on the forced shoe ----------


class Scripted:
    """Returns a fixed list of actions, one per decision (None = an invalid reply)."""

    def __init__(self, actions):
        self.actions = list(actions)
        self.requested = []

    def decide(self, state):
        action = self.actions[len(self.requested)]
        self.requested.append(action)
        return action


class RandomPolicy:
    """Picks a random legal action, and now and then an invalid reply."""

    def __init__(self, rng):
        self.rng = rng
        self.requested = []

    def decide(self, state):
        action = None if self.rng.random() < 0.08 else self.rng.choice(state.legal_actions)
        self.requested.append(action)
        return action


def record_summary(record):
    return {
        "player_hands": [
            {"cards": h.cards, "total": h.total, "doubled": h.doubled, "from_split": h.from_split,
             "payout": h.payout, "result": "win" if h.payout > 0 else "loss" if h.payout < 0 else "push"}
            for h in record.player_hands
        ],
        "dealer_cards": record.dealer_cards,
        "dealer_total": record.dealer_total,
        "payout": record.payout,
    }


def exported_plays():
    """(scenario, seat name, seat entry) for every answered seat in the committed demo data."""
    data = json.loads(DEMO_DATA.read_text())
    return [(s, seat, s["seats"][seat]) for s in data["scenarios"] for seat in ("baseline", "full")
            if s["seats"][seat]["status"] == "answered"]


def test_committed_demo_data_has_every_scenario():
    data = json.loads(DEMO_DATA.read_text())
    assert [s["id"] for s in data["scenarios"]] == [s.scenario_id for s in build_scenarios()]
    assert data["counts"]["baseline_answered"] == 330


def test_python_engine_replays_every_exported_hand():
    plays = exported_plays()
    assert len(plays) >= 330
    for scenario, seat, entry in plays:
        player = Scripted(d["action"] for d in entry["decisions"])
        record = play_hand(player, 2026, 1, shoe=export.decode_shoe(scenario["shoe"]))
        assert record_summary(record) == entry["result"], (seat, scenario["id"])
        assert [d.action_taken for d in record.decisions] == [d["taken"] for d in entry["decisions"]]


def find_node():
    found = shutil.which("node")
    if found:
        return found
    candidates = sorted(glob.glob(os.path.expanduser("~/.nvm/versions/node/*/bin/node")))
    return candidates[-1] if candidates else None


def run_js(cases, tmp_path):
    node = find_node()
    if node is None:
        pytest.skip("node is not installed")
    path = tmp_path / "cases.json"
    path.write_text(json.dumps(cases))
    out = subprocess.run([node, str(REPLAY_JS), str(path)], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def test_js_engine_replays_every_exported_hand(tmp_path):
    plays = exported_plays()
    cases = [{"shoe": s["shoe"], "actions": [d["action"] for d in e["decisions"]]} for s, _, e in plays]
    for (scenario, seat, entry), got in zip(plays, run_js(cases, tmp_path)):
        decisions = got.pop("decisions")
        got.pop("cards_drawn")
        assert got == entry["result"], (seat, scenario["id"])
        assert [d["taken"] for d in decisions] == [d["taken"] for d in entry["decisions"]]
        assert [d["legal"] for d in decisions] == [d["legal"] for d in entry["decisions"]]


def test_js_engine_matches_python_on_random_play(tmp_path):
    """Shared fixtures: the Python engine plays random moves, then the JS engine replays them."""
    rng = random.Random(20261122)
    scenarios = build_scenarios()
    cases, expected = [], []
    for n in range(600):
        if n % 3 == 0:  # natural shoes too, so blackjacks and the dealer peek are covered
            shoe = make_shoe_for_hand(2026, 10_000 + n, 6)
        else:
            shoe = forced_shoe(rng.choice(scenarios), 2026, 6)
        policy = RandomPolicy(rng)
        record = play_hand(policy, 2026, 1, shoe=list(shoe))
        cases.append({"shoe": shoe, "actions": policy.requested})
        expected.append((record_summary(record), [
            {"hand": d.state.hand_index, "cards": list(d.state.player_cards), "legal": list(d.state.legal_actions),
             "taken": d.action_taken, "valid": d.is_valid} for d in record.decisions
        ]))
    assert any(len(s["player_hands"]) == 2 for s, _ in expected)
    assert any(s["payout"] == 1.5 for s, _ in expected)
    for (summary, decisions), got in zip(expected, run_js(cases, tmp_path)):
        got.pop("cards_drawn")
        assert got.pop("decisions") == decisions
        assert got == summary


# ---------- the server ----------


@pytest.fixture
def board_data():
    deal = lambda id_, basic, b, f: {  # noqa: E731
        "id": id_, "legal": ["hit", "stand", "double"], "basic": basic,
        "seats": {"baseline": {"status": "answered", "correct": b},
                  "full": {"status": "answered", "correct": f} if f is not None else {"status": "pending"}},
    }
    return {"scenarios": [deal("a", "hit", True, True), deal("b", "stand", False, True), deal("c", "double", False, None)]}


def test_grade_submission_regrades_against_basic_strategy(board_data):
    row = server_mod.grade_submission(board_data, {"deals": [{"id": "a", "action": "stand"}, {"id": "b", "action": "stand"}]})
    assert row["deals"] == ["a", "b"] and row["actions"] == ["stand", "stand"] and row["correct"] == [False, True]
    assert set(row) == {"ts", "deals", "actions", "correct"}


@pytest.mark.parametrize("body", [
    {}, {"deals": []}, {"deals": [{"id": "zzz", "action": "hit"}]}, {"deals": [{"id": "a", "action": "split"}]},
    {"deals": [{"id": "a", "action": "hit"}, {"id": "a", "action": "hit"}]}, {"deals": ["a"]},
])
def test_grade_submission_rejects_bad_bodies(board_data, body):
    with pytest.raises(ValueError):
        server_mod.grade_submission(board_data, body)


def test_board_scores_agents_on_the_deals_visitors_played(board_data):
    results = [
        {"deals": ["a", "b", "c"], "correct": [True, False, True]},
        {"deals": ["b", "c"], "correct": [True, False]},
    ]
    board = server_mod.compute_board(board_data, results)
    assert board["visitors"] == 2 and board["deals_played"] == 5 and board["distinct_deals"] == 3
    assert board["visitor"] == {"correct": 3, "total": 5, "accuracy": 0.6}
    assert board["baseline"] == {"correct": 1, "total": 5, "accuracy": 0.2}
    # c is pending for the full harness, so only a, b, b count.
    assert board["full"] == {"correct": 3, "total": 3, "accuracy": 1.0}


def test_board_with_no_visitors_has_no_accuracy(board_data):
    board = server_mod.compute_board(board_data, [])
    assert board["visitors"] == 0 and board["visitor"]["accuracy"] is None and board["full"]["accuracy"] is None


def test_read_results_skips_a_half_written_line(tmp_path):
    path = tmp_path / "r.jsonl"
    path.write_text('{"deals": ["a"], "correct": [true]}\n{"deals": ["b"], "corr')
    assert server_mod.read_results(path) == [{"deals": ["a"], "correct": [True]}]


def start(data_path, results_path):
    server = server_mod.make_server("127.0.0.1", 0, data_path, results_path)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def stop(server):
    server.shutdown()
    server.server_close()


def http(url, body=None):
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=5) as reply:
            return reply.status, reply.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def test_server_stores_results_and_keeps_them_across_a_restart(board_data, tmp_path):
    data_path, results_path = tmp_path / "demo_data.json", tmp_path / "visitor_results.jsonl"
    data_path.write_text(json.dumps(board_data))
    server, base = start(data_path, results_path)
    try:
        status, body = http(base + "/api/results", {"deals": [{"id": "a", "action": "hit"}, {"id": "c", "action": "hit"}]})
        assert status == 200
        assert json.loads(body)["board"]["visitor"] == {"correct": 1, "total": 2, "accuracy": 0.5}
        assert http(base + "/api/results", {"deals": [{"id": "nope", "action": "hit"}]})[0] == 400
    finally:
        stop(server)

    stored = [json.loads(line) for line in results_path.read_text().splitlines()]
    assert len(stored) == 1 and stored[0]["deals"] == ["a", "c"] and stored[0]["correct"] == [True, False]

    server, base = start(data_path, results_path)
    try:
        status, body = http(base + "/api/board")
        board = json.loads(body)
        assert status == 200 and board["visitors"] == 1
        assert board["baseline"] == {"correct": 1, "total": 2, "accuracy": 0.5}
        assert board["full"] == {"correct": 1, "total": 1, "accuracy": 1.0}
    finally:
        stop(server)


def test_server_serves_the_page_but_not_the_results_file(board_data, tmp_path):
    data_path = tmp_path / "demo_data.json"
    data_path.write_text(json.dumps(board_data))
    server, base = start(data_path, tmp_path / "visitor_results.jsonl")
    try:
        status, body = http(base + "/")
        assert status == 200 and b"<title>" in body
        assert http(base + "/visitor_results.jsonl")[0] == 404
        assert http(base + "/api/nothing")[0] == 404
    finally:
        stop(server)
