"""Tests for the Ollama client (with a fake HTTP session) and the LLM player
(with a fake chat client, played end to end through play_hand). No network."""

import pytest
import requests

from agent.config import BASELINE, HarnessConfig
from agent.llm_player import LLMPlayer
from agent.ollama_client import ChatReply, OllamaClient, OllamaUnavailableError
from blackjack.engine import play_hand


def stacked(player_cards, dealer_cards, draws=()):
    """A shoe dealing these player cards, dealer cards, then draws (same order as test_engine)."""
    p1, p2 = player_cards
    d_up, d_hole = dealer_cards
    return [p1, d_up, p2, d_hole, *draws] + ["2"] * 20


class FakeChatClient:
    """Returns canned replies in order and remembers every prompt it was sent."""

    model = "fake:1b"

    def __init__(self, replies: list[str], done_reason: str = "stop"):
        self.replies = list(replies)
        self.done_reason = done_reason
        self.calls: list[tuple[str, str]] = []

    def chat(self, system: str, user: str) -> ChatReply:
        self.calls.append((system, user))
        return ChatReply(content=self.replies.pop(0), done_reason=self.done_reason, eval_count=42, latency_s=0.5)


# --- LLM player ----------------------------------------------------------------------


def test_enabling_any_component_is_not_implemented_yet():
    with pytest.raises(NotImplementedError):
        LLMPlayer(FakeChatClient([]), HarnessConfig("x", memory=True))


def test_valid_reply_is_played():
    # Player 10,6 vs dealer 10 (hole 7). Model hits, draws a 3 -> 19, then stands.
    client = FakeChatClient(["Hmm.\n\nACTION: hit", "ACTION: stand"])
    player = LLMPlayer(client, BASELINE)
    record = play_hand(player, 1, 1, shoe=stacked(("10", "6"), ("10", "7"), ["3"]))

    assert [d.action_taken for d in record.decisions] == ["hit", "stand"]
    assert all(d.is_valid for d in record.decisions)
    details = player.take_hand_details()
    assert [d.parsed_action for d in details] == ["hit", "stand"]
    assert details[0].raw_response == "Hmm.\n\nACTION: hit"
    assert "Your cards: 10, 6" in details[0].user_prompt
    assert "Your cards: 10, 6, 3" in details[1].user_prompt
    assert details[0].system_prompt == client.calls[0][0]
    assert record.payout == 1  # 19 beats 17


def test_invalid_reply_hands_the_engine_none_so_it_stands_and_logs_invalid():
    client = FakeChatClient(["I would stand probably."])
    player = LLMPlayer(client, BASELINE)
    record = play_hand(player, 1, 1, shoe=stacked(("10", "6"), ("10", "7")))

    decision = record.decisions[0]
    assert decision.action_requested is None
    assert decision.action_taken == "stand"
    assert decision.is_valid is False
    detail = player.take_hand_details()[0]
    assert detail.parsed_action is None
    assert detail.invalid_reason == "no_action"


def test_illegal_reply_is_invalid():
    # After a hit the hand has 3 cards, so double is illegal.
    client = FakeChatClient(["ACTION: hit", "ACTION: double"])
    player = LLMPlayer(client, BASELINE)
    record = play_hand(player, 1, 1, shoe=stacked(("5", "4"), ("10", "7"), ["2"]))
    assert record.decisions[1].is_valid is False
    assert player.take_hand_details()[1].invalid_reason == "illegal"


def test_take_hand_details_clears_the_buffer():
    player = LLMPlayer(FakeChatClient(["ACTION: stand"]), BASELINE)
    play_hand(player, 1, 1, shoe=stacked(("10", "6"), ("10", "7")))
    assert len(player.take_hand_details()) == 1
    assert player.take_hand_details() == []


# --- Ollama client -------------------------------------------------------------------


class FakeResponse:
    def __init__(self, status: int, body: dict):
        self.status_code = status
        self.body = body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        return self.body


class FakeSession:
    """Plays back a list of outcomes: an exception to raise, or a FakeResponse."""

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.posts: list[dict] = []

    def post(self, url, json, timeout):
        self.posts.append({"url": url, "json": json})
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


OK_BODY = {"message": {"role": "assistant", "content": "ACTION: hit"}, "done_reason": "stop", "eval_count": 7}


def make_client(session) -> OllamaClient:
    return OllamaClient(model="qwen2.5:7b", session=session, sleep=lambda seconds: None)


def test_client_sends_the_locked_request():
    session = FakeSession([FakeResponse(200, OK_BODY)])
    reply = make_client(session).chat("SYS", "USER")

    sent = session.posts[0]
    assert sent["url"] == "http://localhost:11434/api/chat"
    assert sent["json"] == {
        "model": "qwen2.5:7b",
        "messages": [{"role": "system", "content": "SYS"}, {"role": "user", "content": "USER"}],
        "stream": False,
        "options": {"temperature": 0, "seed": 42, "num_predict": 400},
        "keep_alive": "30m",
    }
    assert reply.content == "ACTION: hit"
    assert reply.done_reason == "stop"
    assert reply.eval_count == 7
    assert reply.latency_s >= 0


def test_client_retries_connection_and_http_errors_then_succeeds():
    session = FakeSession([requests.ConnectionError("down"), FakeResponse(500, {}), FakeResponse(200, OK_BODY)])
    assert make_client(session).chat("S", "U").content == "ACTION: hit"
    assert len(session.posts) == 3


def test_client_gives_up_after_three_tries_with_a_clear_error():
    session = FakeSession([requests.ConnectionError("down")] * 3)
    with pytest.raises(OllamaUnavailableError, match="3 tries"):
        make_client(session).chat("S", "U")


def test_infrastructure_failure_stops_the_hand_instead_of_logging_invalid():
    class BrokenClient:
        model = "x"

        def chat(self, system, user):
            raise OllamaUnavailableError("down")

    player = LLMPlayer(BrokenClient(), BASELINE)
    with pytest.raises(OllamaUnavailableError):
        play_hand(player, 1, 1, shoe=stacked(("10", "6"), ("10", "7")))
    assert player.take_hand_details() == []
