"""Tests for scripts/run_baseline.py, with Ollama replaced by fakes (no real model calls)."""

import importlib.util
import json
import sys
from pathlib import Path

from agent.ollama_client import ChatReply

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
