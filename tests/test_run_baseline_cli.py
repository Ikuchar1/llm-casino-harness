"""Tests for scripts/run_baseline.py, with Ollama replaced by fakes (no real model calls)."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from agent.config import get_config
from agent.ollama_client import ChatReply
from agent.prompt import ODDS_HEADER

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "run_baseline.py"


def load_script():
    spec = importlib.util.spec_from_file_location("run_baseline_script", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeClient:
    """Stands in for OllamaClient: always stands."""

    def __init__(self, model):
        self.model = model

    def chat(self, system, user):
        return ChatReply(content="Standing.\nACTION: stand", done_reason="stop", eval_count=5, latency_s=0.1)


def test_metadata_records_the_ollama_host_url(tmp_path, monkeypatch):
    module = load_script()
    monkeypatch.setattr(module, "OllamaClient", FakeClient)
    monkeypatch.setattr(module, "get_model_digest", lambda model: "sha256:fake")
    monkeypatch.setattr(module, "get_ollama_version", lambda: "0.0-test")
    monkeypatch.setenv("OLLAMA_HOST", "127.0.0.1:20123")
    monkeypatch.setattr(sys, "argv", ["run_baseline.py", "--hands", "2", "--seed", "2026", "--out", str(tmp_path / "run")])

    assert module.main() == 0

    metadata = json.loads((tmp_path / "run" / "metadata.json").read_text())
    assert metadata["ollama_url"] == "http://127.0.0.1:20123"
    assert metadata["n_hands"] == 2


def test_metadata_records_the_platform(tmp_path, monkeypatch):
    module = load_script()
    monkeypatch.setattr(module, "OllamaClient", FakeClient)
    monkeypatch.setattr(module, "get_model_digest", lambda model: "sha256:fake")
    monkeypatch.setattr(module, "get_ollama_version", lambda: "0.0-test")
    fake = {"hostname": "c1234", "platform": "Linux-x86_64", "gpus": ["NVIDIA L40S"], "slurm_job_id": "42"}
    monkeypatch.setattr(module, "platform_info", lambda: fake)
    monkeypatch.setattr(sys, "argv", ["run_baseline.py", "--hands", "1", "--seed", "2026", "--out", str(tmp_path / "run")])

    assert module.main() == 0

    metadata = json.loads((tmp_path / "run" / "metadata.json").read_text())
    assert {k: metadata[k] for k in fake} == fake


# --- --config ------------------------------------------------------------------------


def run_with(module, monkeypatch, tmp_path, *extra):
    monkeypatch.setattr(module, "OllamaClient", FakeClient)
    monkeypatch.setattr(module, "get_model_digest", lambda model: "sha256:fake")
    monkeypatch.setattr(module, "get_ollama_version", lambda: "0.0-test")
    out = tmp_path / "run"
    monkeypatch.setattr(sys, "argv", ["run_baseline.py", "--hands", "2", "--seed", "2026", "--out", str(out), *extra])
    return module.main(), out


def test_default_config_is_baseline(tmp_path, monkeypatch):
    module = load_script()
    code, out = run_with(module, monkeypatch, tmp_path)
    assert code == 0
    metadata = json.loads((out / "metadata.json").read_text())
    assert metadata["harness_config"] == "baseline"
    assert metadata["harness_flags"] == get_config("baseline").flags()
    assert metadata["run_id"].startswith("baseline_")


def test_prob_config_is_recorded_and_puts_odds_in_the_prompt(tmp_path, monkeypatch):
    module = load_script()
    code, out = run_with(module, monkeypatch, tmp_path, "--config", "prob")
    assert code == 0
    metadata = json.loads((out / "metadata.json").read_text())
    assert metadata["harness_config"] == "prob"
    assert metadata["harness_flags"] == get_config("prob").flags()
    assert metadata["run_id"].startswith("prob_")
    rows = [json.loads(line) for line in (out / "decisions.jsonl").read_text().splitlines()]
    assert rows and all(r["harness_config"] == "prob" and ODDS_HEADER in r["prompt"]["user"] for r in rows)


def test_resume_refuses_a_different_config(tmp_path, monkeypatch):
    module = load_script()
    run_with(module, monkeypatch, tmp_path)
    with pytest.raises(SystemExit, match="harness_config"):
        run_with(module, monkeypatch, tmp_path, "--config", "prob")


@pytest.mark.parametrize("name", ["strat", "self", "prob_strat", "prob_strat_self"])
def test_unbuilt_config_fails_before_writing_anything(tmp_path, monkeypatch, capsys, name):
    module = load_script()
    code, out = run_with(module, monkeypatch, tmp_path, "--config", name)
    assert code == 2
    assert "not built yet" in capsys.readouterr().err
    assert not out.exists()


def test_unknown_config_is_rejected(tmp_path, monkeypatch):
    module = load_script()
    with pytest.raises(SystemExit):
        run_with(module, monkeypatch, tmp_path, "--config", "memory")
