"""Tests for scripts/run_scenarios.py, with Ollama replaced by fakes (no real model calls)."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from agent.ollama_client import ChatReply

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "run_scenarios.py"


def load_script():
    spec = importlib.util.spec_from_file_location("run_scenarios_script", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeClient:
    """Stands in for OllamaClient: always stands."""

    def __init__(self, model):
        self.model = model

    def chat(self, system, user):
        return ChatReply(content="Standing.\nACTION: stand", done_reason="stop", eval_count=5, latency_s=0.1)


def fake_ollama(module, monkeypatch, digest="sha256:fake"):
    monkeypatch.setattr(module, "OllamaClient", FakeClient)
    monkeypatch.setattr(module, "get_model_digest", lambda model: digest)
    monkeypatch.setattr(module, "get_ollama_version", lambda: "0.0-test")


def run_main(module, monkeypatch, *args):
    monkeypatch.setattr(sys, "argv", ["run_scenarios.py", *args])
    return module.main()


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def test_limit_run_writes_rows_metadata_and_baseline_style_progress(tmp_path, monkeypatch, capsys):
    module = load_script()
    fake_ollama(module, monkeypatch)
    out = tmp_path / "run"

    assert run_main(module, monkeypatch, "--seed", "2026", "--out", str(out), "--limit", "3") == 0

    metadata = json.loads((out / "metadata.json").read_text())
    assert metadata["run_type"] == "scenario"
    assert metadata["scenario_count"] == 330
    assert metadata["n_hands"] == 3
    assert metadata["scenario_set_version"] == "scenarios-v1"
    assert "10,2" in metadata["composition_rule"]
    assert metadata["harness_config"] == "baseline"
    assert metadata["sessions"][-1]["status"] == "completed"

    rows = read_jsonl(out / "decisions.jsonl")
    assert [r["scenario_id"] for r in rows] == ["hard5_vs_2", "hard5_vs_3", "hard5_vs_4"]
    assert all(r["is_scenario_cell"] and r["run_type"] == "scenario" for r in rows)

    printed = capsys.readouterr().out
    assert "hand    1 (1/3) | decisions 1 (total 1) | accuracy" in printed
    assert "s/decision | ETA" in printed


def test_resume_with_a_bigger_limit_appends(tmp_path, monkeypatch):
    module = load_script()
    fake_ollama(module, monkeypatch)
    out = tmp_path / "run"
    run_main(module, monkeypatch, "--seed", "2026", "--out", str(out), "--limit", "2")
    run_main(module, monkeypatch, "--seed", "2026", "--out", str(out), "--limit", "5")

    hands = read_jsonl(out / "hands.jsonl")
    assert [h["hand_number"] for h in hands] == [1, 2, 3, 4, 5]
    metadata = json.loads((out / "metadata.json").read_text())
    assert len(metadata["sessions"]) == 2


def test_resume_refuses_a_different_seed(tmp_path, monkeypatch):
    module = load_script()
    fake_ollama(module, monkeypatch)
    out = tmp_path / "run"
    run_main(module, monkeypatch, "--seed", "2026", "--out", str(out), "--limit", "1")
    with pytest.raises(SystemExit, match="run_seed"):
        run_main(module, monkeypatch, "--seed", "7", "--out", str(out), "--limit", "1")


def test_resume_refuses_a_baseline_run_directory(tmp_path, monkeypatch):
    module = load_script()
    fake_ollama(module, monkeypatch)
    out = tmp_path / "run"
    out.mkdir()
    baseline_metadata = {
        "model": "qwen2.5:7b", "run_seed": 2026, "harness_config": "baseline",
        "prompt_version": module.PROMPT_VERSION, "parser_version": module.PARSER_VERSION,
    }
    (out / "metadata.json").write_text(json.dumps(baseline_metadata))
    with pytest.raises(SystemExit, match="run_type"):
        run_main(module, monkeypatch, "--seed", "2026", "--out", str(out), "--limit", "1")


def test_metadata_records_the_ollama_host_url(tmp_path, monkeypatch):
    module = load_script()
    fake_ollama(module, monkeypatch)
    monkeypatch.setenv("OLLAMA_HOST", "127.0.0.1:20123")
    out = tmp_path / "run"

    assert run_main(module, monkeypatch, "--seed", "2026", "--out", str(out), "--limit", "1") == 0

    assert json.loads((out / "metadata.json").read_text())["ollama_url"] == "http://127.0.0.1:20123"
