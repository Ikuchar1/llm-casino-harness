"""Tests for the poker LLM player (poker/llm_player.py) with a fake chat client. No network."""

import pytest

from agent.ollama_client import ChatReply
from poker.engine import play_hand
from poker.llm_player import SETUPS, PokerLLMPlayer
from poker.prompt import build_system_prompt, build_user_prompt
from tests.test_poker_prompt import flop_state


class FakeChatClient:
    """Returns canned replies in order and remembers every prompt it was sent."""

    model = "fake:1b"

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def chat(self, system, user):
        self.calls.append((system, user))
        return ChatReply(content=self.replies.pop(0), done_reason="stop", eval_count=42, latency_s=0.5)


def test_the_player_sends_the_decision_prompt_and_returns_the_parsed_action():
    client = FakeChatClient(["Good draw, I raise.\nACTION: raise_pot"])
    player = PokerLLMPlayer(client)

    assert player.decide(flop_state()) == "raise_pot"
    assert client.calls == [(build_system_prompt(), build_user_prompt(flop_state()))]


def test_each_decision_keeps_its_prompt_reply_parse_result_and_latency():
    player = PokerLLMPlayer(FakeChatClient(["ACTION: check/call", "no idea"]))
    player.decide(flop_state())
    player.decide(flop_state())

    first, second = player.take_hand_details()
    assert (first.user_prompt, first.raw_response, first.parsed_action) == (build_user_prompt(flop_state()), "ACTION: check/call", "call")
    assert (first.parse_status, first.parse_method, first.mapping) == ("mapped", "action_line", "check/call -> call")
    assert (first.done_reason, first.eval_count, first.latency_s) == ("stop", 42, 0.5)
    assert (second.parsed_action, second.parse_status) == (None, "unparseable")
    assert player.take_hand_details() == []


def test_an_off_menu_answer_is_passed_on_so_the_engine_falls_back_and_the_detail_says_off_menu():
    # Facing the opening bet preflop, check is not on the menu; the engine folds for the player.
    player = PokerLLMPlayer(FakeChatClient(["ACTION: check"]))
    record = play_hand(seed=1, players={"model": player, "bot": OneActionPlayer("call")}, button="model")

    decision, = [d for d in record.decisions if d.player == "model"]
    detail, = player.take_hand_details()
    assert (decision.choice, decision.action, decision.fallback) == ("check", "fold", True)
    assert (detail.parsed_action, detail.parse_status, detail.named_action) == (None, "off_menu", "check")


def test_the_memory_setup_is_not_built_yet():
    with pytest.raises(NotImplementedError, match="memory"):
        PokerLLMPlayer(FakeChatClient([]), SETUPS["memory"])


class OneActionPlayer:
    def __init__(self, action):
        self.action = action

    def decide(self, state):
        return self.action
