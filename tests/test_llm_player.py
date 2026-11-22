"""Tests for the Ollama client (with a fake HTTP session) and the LLM player
(with a fake chat client, played end to end through play_hand). No network."""

import pytest
import requests

from agent.config import BASELINE, HarnessConfig, get_config
from agent.llm_player import LLMPlayer, component_versions
from agent.ollama_client import ChatReply, OllamaClient, OllamaUnavailableError
from agent.prompt import ODDS_HEADER, SELF_EVAL_VERSION, build_system_prompt, build_user_prompt
from agent.strategy_info import STRATEGY_INFO_VERSION, principles_block
from blackjack.engine import DecisionState, play_hand
from blackjack.rules import DEFAULT_RULES


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


@pytest.mark.parametrize("name", ["baseline", "prob", "prob_strat", "prob_strat_self", "strat", "self"])
def test_every_blackjack_config_is_built(name):
    LLMPlayer(FakeChatClient([]), get_config(name))


@pytest.mark.parametrize("name", ["baseline", "prob", "self"])
def test_configs_without_strategy_info_keep_the_exact_baseline_system_prompt(name):
    assert LLMPlayer(FakeChatClient([]), get_config(name)).system_prompt == build_system_prompt(DEFAULT_RULES)


@pytest.mark.parametrize("name", ["strat", "prob_strat", "prob_strat_self"])
def test_strategy_info_appends_the_principles_after_one_blank_line(name):
    player = LLMPlayer(FakeChatClient([]), get_config(name))
    assert player.system_prompt == build_system_prompt(DEFAULT_RULES) + "\n\n" + principles_block()


def test_strat_config_sends_the_principles_in_the_system_message():
    client = FakeChatClient(["ACTION: stand"])
    play_hand(LLMPlayer(client, get_config("strat")), 1, 1, shoe=stacked(("10", "6"), ("6", "7")))
    system, user = client.calls[0]
    assert system.endswith(principles_block())
    assert ODDS_HEADER not in user


@pytest.mark.parametrize("name,expected", [
    ("baseline", {}),
    ("prob", {}),
    ("strat", {"strategy_info_version": STRATEGY_INFO_VERSION}),
    ("self", {"self_eval_version": SELF_EVAL_VERSION}),
    ("prob_strat_self", {"strategy_info_version": STRATEGY_INFO_VERSION, "self_eval_version": SELF_EVAL_VERSION}),
])
def test_run_metadata_records_component_versions_only_when_on(name, expected):
    metadata = LLMPlayer(FakeChatClient([]), get_config(name)).run_metadata()
    assert {k: v for k, v in metadata.items() if k.endswith("_version")} == expected
    assert metadata["system_prompt"] == LLMPlayer(FakeChatClient([]), get_config(name)).system_prompt


@pytest.mark.parametrize("name", ["baseline", "prob", "strat", "self", "prob_strat_self"])
def test_component_versions_match_run_metadata_with_none_for_components_off(name):
    # The run scripts' resume check uses these; None matches a key absent from metadata.
    metadata = LLMPlayer(FakeChatClient([]), get_config(name)).run_metadata()
    versions = component_versions(get_config(name))
    assert set(versions) == {"strategy_info_version", "self_eval_version"}
    assert all(metadata.get(key) == value for key, value in versions.items())


def test_prob_config_sends_the_odds_block_and_logs_it():
    client = FakeChatClient(["ACTION: stand"])
    player = LLMPlayer(client, get_config("prob"))
    play_hand(player, 1, 1, shoe=stacked(("10", "6"), ("6", "7")))

    sent_user = client.calls[0][1]
    assert sent_user == build_user_prompt(player_state(("10", "6"), "6"), get_config("prob"))
    assert ODDS_HEADER in sent_user
    assert player.take_hand_details()[0].user_prompt == sent_user


def test_baseline_config_sends_no_odds_block():
    client = FakeChatClient(["ACTION: stand"])
    play_hand(LLMPlayer(client, BASELINE), 1, 1, shoe=stacked(("10", "6"), ("6", "7")))
    assert ODDS_HEADER not in client.calls[0][1]


def player_state(cards, upcard):
    return DecisionState(player_cards=cards, total=16, is_soft=False, is_pair=False, dealer_upcard=upcard,
                         legal_actions=("hit", "stand", "double"), hand_index=0, num_cards=2, from_split=False)


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


def test_chat_messages_sends_the_whole_conversation_with_the_same_locked_options():
    session = FakeSession([FakeResponse(200, OK_BODY), FakeResponse(200, OK_BODY)])
    client = make_client(session)
    messages = [
        {"role": "system", "content": "SYS"},
        {"role": "user", "content": "USER"},
        {"role": "assistant", "content": "ACTION: stand"},
        {"role": "user", "content": "RECHECK"},
    ]
    reply = client.chat_messages(messages)
    client.chat("SYS", "USER")

    multi, single = session.posts[0]["json"], session.posts[1]["json"]
    assert multi["messages"] == messages
    assert {k: v for k, v in multi.items() if k != "messages"} == {k: v for k, v in single.items() if k != "messages"}
    assert multi["options"] == {"temperature": 0, "seed": 42, "num_predict": 400}
    assert reply.content == "ACTION: hit"
    assert reply.eval_count == 7


def test_chat_messages_retries_like_chat():
    session = FakeSession([requests.ConnectionError("down"), FakeResponse(200, OK_BODY)])
    assert make_client(session).chat_messages([{"role": "user", "content": "U"}]).content == "ACTION: hit"
    assert len(session.posts) == 2


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
