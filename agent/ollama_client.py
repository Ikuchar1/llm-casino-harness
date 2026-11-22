"""A small client for a local Ollama server's /api/chat endpoint.

The server address comes from the OLLAMA_HOST environment variable when it is
set (the same variable `ollama serve` reads, e.g. a per-job port on HCC), and
is http://localhost:11434 otherwise.

Only HTTP and connection errors are retried (3 tries in total, with backoff).
If every try fails, OllamaUnavailableError is raised so the run stops: an
infrastructure failure must never be logged as the model's invalid action.
"""

import os
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional, Protocol

import requests

DEFAULT_BASE_URL = "http://localhost:11434"
DEFAULT_PORT = 11434
DEFAULT_MODEL = "qwen2.5:7b"
# Locked sampling settings: deterministic decoding, fixed seed, reply length cap.
DEFAULT_OPTIONS: dict[str, Any] = {"temperature": 0, "seed": 42, "num_predict": 400}
DEFAULT_KEEP_ALIVE = "30m"  # keep the model loaded between decisions
MAX_TRIES = 3
REQUEST_TIMEOUT_S = 300


def resolve_base_url() -> str:
    """The Ollama server URL: OLLAMA_HOST if set, else DEFAULT_BASE_URL.

    OLLAMA_HOST may omit the scheme ("127.0.0.1:20123"), the host (":20123")
    or the port ("127.0.0.1"); like Ollama, fill in http, 127.0.0.1 and 11434.
    """
    value = os.environ.get("OLLAMA_HOST", "").strip().rstrip("/")
    if not value:
        return DEFAULT_BASE_URL
    scheme, sep, rest = value.partition("://")
    if not sep:
        scheme, rest = "http", value
    host, colon, port = rest.rpartition(":")
    if not colon or "]" in port:  # no port given (or a bare IPv6 address)
        host, port = rest, str(DEFAULT_PORT) if scheme == "http" else ""
    host = host or "127.0.0.1"
    return f"{scheme}://{host}" + (f":{port}" if port else "")


class OllamaUnavailableError(RuntimeError):
    """Ollama could not be reached or kept returning HTTP errors."""


@dataclass
class ChatReply:
    """One model reply and the bookkeeping we log with it."""

    content: str
    done_reason: Optional[str]  # "stop" = finished normally, "length" = hit num_predict
    eval_count: Optional[int]  # tokens generated
    latency_s: float  # wall-clock time for the successful request


class ChatClient(Protocol):
    """Anything the LLM player can send a system + user message to."""

    model: str

    def chat(self, system: str, user: str) -> ChatReply: ...


class OllamaClient:
    """Sends chat requests to Ollama with the locked options."""

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        base_url: Optional[str] = None,  # None = resolve_base_url()
        options: Optional[dict[str, Any]] = None,
        keep_alive: str = DEFAULT_KEEP_ALIVE,
        session: Any = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.model = model
        self.base_url = (base_url if base_url is not None else resolve_base_url()).rstrip("/")
        self.options = dict(DEFAULT_OPTIONS if options is None else options)
        self.keep_alive = keep_alive
        # A requests.Session reuses the HTTP connection. Tests pass a fake one.
        self.session = session if session is not None else requests.Session()
        self.sleep = sleep

    def chat(self, system: str, user: str) -> ChatReply:
        """Send one system + user message pair and return the model's reply."""
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "stream": False,
            "options": self.options,
            "keep_alive": self.keep_alive,
        }
        start = time.perf_counter()
        body = self._post_with_retries("/api/chat", payload)
        latency = time.perf_counter() - start
        return ChatReply(
            content=body["message"]["content"],
            done_reason=body.get("done_reason"),
            eval_count=body.get("eval_count"),
            latency_s=latency,
        )

    def _post_with_retries(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        last_error: Optional[Exception] = None
        for attempt in range(1, MAX_TRIES + 1):
            try:
                response = self.session.post(self.base_url + path, json=payload, timeout=REQUEST_TIMEOUT_S)
                response.raise_for_status()
                return response.json()
            except requests.RequestException as error:  # connection errors, timeouts, HTTP errors
                last_error = error
                if attempt < MAX_TRIES:
                    self.sleep(2**attempt)  # 2 s, then 4 s
        raise OllamaUnavailableError(
            f"Ollama request to {self.base_url}{path} failed after {MAX_TRIES} tries: {last_error}"
        )


def get_model_digest(model: str, base_url: Optional[str] = None) -> Optional[str]:
    """The installed model's content digest from /api/tags (identifies the exact weights)."""
    base_url = base_url if base_url is not None else resolve_base_url()
    response = requests.get(base_url + "/api/tags", timeout=30)
    response.raise_for_status()
    for entry in response.json().get("models", []):
        if entry.get("name") == model or entry.get("model") == model:
            return entry.get("digest")
    return None


def get_ollama_version(base_url: Optional[str] = None) -> Optional[str]:
    """The Ollama server version from /api/version."""
    base_url = base_url if base_url is not None else resolve_base_url()
    response = requests.get(base_url + "/api/version", timeout=30)
    response.raise_for_status()
    return response.json().get("version")
