"""End-to-end tests for scripts/run_poker.py with scripted players (no Ollama)."""

import importlib.util
import json
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "run_poker.py"


def load_script():
    spec = importlib.util.spec_from_file_location("run_poker_script", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CheckCallBot:
    def decide(self, state):
        return "check" if any(item.action == "check" for item in state.menu) else "call"


def run_cli(monkeypatch, *args):
    module = load_script()
    monkeypatch.setattr(module, "BOT_REGISTRY", {"scripted": CheckCallBot})
    monkeypatch.setattr(sys, "argv", ["run_poker.py", *args])
    return module.main()


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_a_scripted_player_plays_a_whole_match_without_ollama_and_prints_progress(tmp_path, monkeypatch, capsys):
    out = tmp_path / "run"

    code = run_cli(monkeypatch, "--player", "station", "--bot", "scripted", "--pairs", "2", "--seed", "5", "--out", str(out))

    assert code == 0
    metadata = json.loads((out / "metadata.json").read_text())
    assert (metadata["model"], metadata["player"], metadata["bot"], metadata["setup"]) == ("scripted-station", "station", "scripted", "plain")
    assert [row["hand_number"] for row in read_jsonl(out / "hands.jsonl")] == [0, 1, 2, 3]
    assert all(row["run_id"] == metadata["run_id"] for row in read_jsonl(out / "decisions.jsonl"))
    printed = capsys.readouterr().out
    assert "hand    3 (4/4)" in printed


def test_rerunning_the_cli_with_more_pairs_resumes_the_same_run(tmp_path, monkeypatch):
    out = tmp_path / "run"
    args = ("--player", "random", "--bot", "scripted", "--seed", "5", "--out", str(out))
    assert run_cli(monkeypatch, *args, "--pairs", "1") == 0
    first_id = json.loads((out / "metadata.json").read_text())["run_id"]

    assert run_cli(monkeypatch, *args, "--pairs", "2") == 0

    metadata = json.loads((out / "metadata.json").read_text())
    assert metadata["run_id"] == first_id and len(metadata["sessions"]) == 2
    assert [row["hand_number"] for row in read_jsonl(out / "hands.jsonl")] == [0, 1, 2, 3]


def test_a_resume_with_a_different_bot_exits_2(tmp_path, monkeypatch):
    out = tmp_path / "run"
    run_cli(monkeypatch, "--player", "station", "--bot", "scripted", "--pairs", "1", "--seed", "5", "--out", str(out))

    module = load_script()
    monkeypatch.setattr(module, "BOT_REGISTRY", {"scripted": CheckCallBot, "other": CheckCallBot})
    monkeypatch.setattr(sys, "argv", ["run_poker.py", "--player", "station", "--bot", "other", "--pairs", "1",
                                      "--seed", "5", "--out", str(out)])
    assert module.main() == 2


class FakeOllama:
    def __init__(self, model, **kwargs):
        self.model = model

    def chat(self, system, user):
        from agent.ollama_client import ChatReply

        return ChatReply(content="ACTION: check/call", done_reason="stop", eval_count=3, latency_s=0.1)


def test_the_llm_player_runs_through_the_ollama_client_and_records_the_model(tmp_path, monkeypatch):
    module = load_script()
    monkeypatch.setattr(module, "OllamaClient", FakeOllama)
    monkeypatch.setattr(module, "get_model_digest", lambda model: "sha256:abc")
    monkeypatch.setattr(module, "get_ollama_version", lambda: "0.9.0")
    monkeypatch.setattr(module, "BOT_REGISTRY", {"scripted": CheckCallBot})
    out = tmp_path / "run"
    monkeypatch.setattr(sys, "argv", ["run_poker.py", "--model", "fake:1b", "--bot", "scripted", "--pairs", "1",
                                      "--seed", "5", "--out", str(out)])

    assert module.main() == 0

    metadata = json.loads((out / "metadata.json").read_text())
    assert (metadata["model"], metadata["model_digest"], metadata["ollama_version"]) == ("fake:1b", "sha256:abc", "0.9.0")
    assert "system_prompt" in metadata
    model_rows = [row for row in read_jsonl(out / "decisions.jsonl") if row["player"] == "model"]
    assert model_rows and all(row["raw_response"] == "ACTION: check/call" for row in model_rows)


def test_the_memory_setup_is_refused_with_exit_2_before_anything_is_written(tmp_path, monkeypatch):
    module = load_script()
    monkeypatch.setattr(module, "OllamaClient", FakeOllama)
    out = tmp_path / "run"
    monkeypatch.setattr(sys, "argv", ["run_poker.py", "--setup", "memory", "--bot", "scripted", "--pairs", "1",
                                      "--seed", "5", "--out", str(out)])

    assert module.main() == 2
    assert not out.exists()


def test_an_uninstalled_model_exits_1(tmp_path, monkeypatch):
    module = load_script()
    monkeypatch.setattr(module, "OllamaClient", FakeOllama)
    monkeypatch.setattr(module, "get_model_digest", lambda model: None)
    monkeypatch.setattr(module, "get_ollama_version", lambda: "0.9.0")
    out = tmp_path / "run"
    monkeypatch.setattr(sys, "argv", ["run_poker.py", "--bot", "scripted", "--pairs", "1", "--seed", "5", "--out", str(out)])

    assert module.main() == 1
    assert not out.exists()


def run_llm_cli(monkeypatch, out, digest, version="0.9.0", hostname="mac"):
    module = load_script()
    monkeypatch.setattr(module, "OllamaClient", FakeOllama)
    monkeypatch.setattr(module, "get_model_digest", lambda model: digest)
    monkeypatch.setattr(module, "get_ollama_version", lambda: version)
    monkeypatch.setattr(module, "platform_info", lambda: {"hostname": hostname, "gpus": None})
    monkeypatch.setattr(module, "BOT_REGISTRY", {"scripted": CheckCallBot})
    monkeypatch.setattr(sys, "argv", ["run_poker.py", "--model", "fake:1b", "--bot", "scripted", "--pairs", "1",
                                      "--seed", "5", "--out", str(out)])
    return module.main()


def test_a_resume_after_the_model_digest_changed_exits_2_and_plays_nothing(tmp_path, monkeypatch, capsys):
    out = tmp_path / "run"
    assert run_llm_cli(monkeypatch, out, "sha256:old") == 0
    before = (out / "hands.jsonl").read_text()

    assert run_llm_cli(monkeypatch, out, "sha256:new") == 2

    assert "model_digest" in capsys.readouterr().err
    assert (out / "hands.jsonl").read_text() == before
    metadata = json.loads((out / "metadata.json").read_text())
    assert metadata["model_digest"] == "sha256:old" and len(metadata["sessions"]) == 1


def test_each_session_records_where_it_ran_and_a_resume_keeps_the_first_digest_and_ollama_version(tmp_path, monkeypatch):
    out = tmp_path / "run"
    assert run_llm_cli(monkeypatch, out, "sha256:abc", "0.9.0", "mac") == 0
    assert run_llm_cli(monkeypatch, out, "sha256:abc", "0.9.1", "hcc-node") == 0

    metadata = json.loads((out / "metadata.json").read_text())
    assert (metadata["model_digest"], metadata["ollama_version"]) == ("sha256:abc", "0.9.0")
    assert [session["hostname"] for session in metadata["sessions"]] == ["mac", "hcc-node"]
