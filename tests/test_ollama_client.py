"""Tests for how the Ollama base URL is chosen (OLLAMA_HOST env var vs. the localhost default)."""

import pytest

from agent import ollama_client
from agent.ollama_client import OllamaClient, resolve_base_url


@pytest.mark.parametrize(
    "value, expected",
    [
        ("127.0.0.1:20123", "http://127.0.0.1:20123"),
        ("http://127.0.0.1:20123", "http://127.0.0.1:20123"),
        ("https://ollama.example.org", "https://ollama.example.org"),
        ("http://127.0.0.1:20123/", "http://127.0.0.1:20123"),
        ("0.0.0.0:20123", "http://0.0.0.0:20123"),
        ("127.0.0.1", "http://127.0.0.1:11434"),
        (":20123", "http://127.0.0.1:20123"),
        ("  127.0.0.1:20123  ", "http://127.0.0.1:20123"),
    ],
)
def test_ollama_host_is_normalized(monkeypatch, value, expected):
    monkeypatch.setenv("OLLAMA_HOST", value)
    assert resolve_base_url() == expected


@pytest.mark.parametrize("value", [None, "", "   "])
def test_unset_or_blank_ollama_host_falls_back_to_localhost(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("OLLAMA_HOST", raising=False)
    else:
        monkeypatch.setenv("OLLAMA_HOST", value)
    assert resolve_base_url() == "http://localhost:11434"


def test_client_uses_ollama_host_when_no_base_url_given(monkeypatch):
    monkeypatch.setenv("OLLAMA_HOST", "127.0.0.1:20123")
    assert OllamaClient(session=object()).base_url == "http://127.0.0.1:20123"


def test_explicit_base_url_beats_ollama_host(monkeypatch):
    monkeypatch.setenv("OLLAMA_HOST", "127.0.0.1:20123")
    client = OllamaClient(base_url="http://other:9999/", session=object())
    assert client.base_url == "http://other:9999"


class FakeResponse:
    def __init__(self, body):
        self.body = body

    def raise_for_status(self):
        pass

    def json(self):
        return self.body


def test_metadata_helpers_use_ollama_host(monkeypatch):
    monkeypatch.setenv("OLLAMA_HOST", "127.0.0.1:20123")
    urls = []

    def fake_get(url, timeout):
        urls.append(url)
        if url.endswith("/api/tags"):
            return FakeResponse({"models": [{"name": "m", "digest": "d"}]})
        return FakeResponse({"version": "9.9"})

    monkeypatch.setattr(ollama_client.requests, "get", fake_get)
    assert ollama_client.get_model_digest("m") == "d"
    assert ollama_client.get_ollama_version() == "9.9"
    assert urls == ["http://127.0.0.1:20123/api/tags", "http://127.0.0.1:20123/api/version"]
