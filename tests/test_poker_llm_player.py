"""Tests for the poker LLM player (poker/llm_player.py) with a fake chat client. No network."""

from dataclasses import replace

from agent.ollama_client import ChatReply
from poker.engine import MenuItem, play_hand
from poker.llm_player import SETUPS, PokerLLMPlayer
from poker.memory import REWRITE_SYSTEM_PROMPT
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

    def chat_messages(self, messages):
        self.calls.append(messages)
        return ChatReply(content=self.replies.pop(0), done_reason="stop", eval_count=17, latency_s=0.25,
                         prompt_eval_count=300)


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


class CutOffClient(FakeChatClient):
    """Every reply hit the token limit."""

    def chat(self, system, user):
        reply = super().chat(system, user)
        return ChatReply(content=reply.content, done_reason="length", eval_count=400, latency_s=0.5)


def test_a_reply_cut_off_before_its_action_line_falls_back_and_is_marked_truncated():
    player = PokerLLMPlayer(CutOffClient(["My reasoning so far:\ncall"]))

    assert player.decide(flop_state()) is None
    detail, = player.take_hand_details()
    assert (detail.parsed_action, detail.parse_status, detail.done_reason) == (None, "truncated_no_action", "length")


def test_the_memory_setup_builds_and_its_rewrite_goes_to_the_same_client_with_the_rewrite_system_prompt():
    client = FakeChatClient(["folds a lot | key faced_bet.fold | for 9 | against 1"])
    player = PokerLLMPlayer(client, SETUPS["memory"])

    reply = player.rewrite_notes("Rewrite your notes ...")

    assert client.calls == [(REWRITE_SYSTEM_PROMPT, "Rewrite your notes ...")]
    assert (reply.content, reply.done_reason, reply.eval_count) == ("folds a lot | key faced_bet.fold | for 9 | against 1", "stop", 42)
    assert player.take_hand_details() == []  # a rewrite is not a decision


def test_with_the_probability_and_strategy_tools_the_prompt_carries_equity_pot_odds_and_the_chart_before_the_menu():
    from agent.config import HarnessConfig
    from poker.equity_info import equity_info
    from poker.preflop_chart import chart_lines

    client = FakeChatClient(["ACTION: call"])
    player = PokerLLMPlayer(client, HarnessConfig(name="prob_strat", probability_tool=True, strategy_info=True))
    state = preflop_state()

    player.decide(state)

    tools = equity_info(state).lines() + chart_lines(state)
    assert client.calls == [(build_system_prompt(), build_user_prompt(state, tools=tools))]
    assert "Preflop chart" in client.calls[0][1] and "Pot odds" in client.calls[0][1]
    detail, = player.take_hand_details()
    info = equity_info(state)
    assert detail.tools == {
        "equity": round(info.equity, 4), "pot_odds": round(info.pot_odds, 4), "equity_seed": info.seed,
        "equity_samples": info.samples, "hand_class": "QJs", "spot": "vs_raise", "chart_play": "call",
    }


def test_the_plain_and_memory_setups_log_no_tools_and_send_the_same_prompt_as_before():
    for name in ("plain", "memory"):
        client = FakeChatClient(["ACTION: call"])
        player = PokerLLMPlayer(client, SETUPS[name])
        player.decide(preflop_state())

        assert client.calls == [(build_system_prompt(), build_user_prompt(preflop_state()))]
        detail, = player.take_hand_details()
        assert (detail.tools, detail.self_check, detail.flags) == (None, None, None)


def preflop_state():
    """The big blind with QJs facing the button's open to 4."""
    from poker.engine import Action, DecisionState, MenuItem

    return DecisionState(
        seat="big_blind", hole_cards=("Qh", "Jh"), board=(), street="preflop", pot=6, stack=198,
        opponent_stack=196, to_call=2, is_button=False,
        history=(Action("preflop", "button", "raise_half_pot", 4),),
        menu=(MenuItem("fold"), MenuItem("call", 2), MenuItem("raise_half_pot", 10),
              MenuItem("raise_pot", 16), MenuItem("all_in", 198)),
    )


class OneActionPlayer:
    def __init__(self, action):
        self.action = action

    def decide(self, state):
        return self.action


def test_in_the_tools_setup_every_decision_is_re_checked_in_the_same_conversation_and_the_second_answer_is_played():
    from poker.self_check import recheck_prompt

    client = FakeChatClient(["Weak hand.\nACTION: fold", "On reflection the price is good.\nACTION: call"])
    player = PokerLLMPlayer(client, SETUPS["tools"])
    state = preflop_state()

    assert player.decide(state) == "call"

    (system, user), messages = client.calls
    assert messages == [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
        {"role": "assistant", "content": "Weak hand.\nACTION: fold"},
        {"role": "user", "content": recheck_prompt("fold")},
    ]
    detail, = player.take_hand_details()
    assert (detail.raw_response, detail.parsed_action, detail.parse_status) == ("Weak hand.\nACTION: fold", "call", "ok")
    assert detail.self_check == {
        "first_action": "fold", "first_parse_status": "ok", "recheck_prompt": recheck_prompt("fold"),
        "second_raw": "On reflection the price is good.\nACTION: call", "second_action": "call",
        "second_parse_status": "ok", "final_action": "call", "flipped": True,
        "done_reason": "stop", "eval_count": 17, "prompt_tokens": 300, "latency_s": 0.25,
    }


def test_an_unusable_re_check_keeps_the_first_answer_and_an_unusable_first_answer_gets_the_invalid_re_check():
    from poker.self_check import RECHECK_PROMPT_INVALID

    keeps = PokerLLMPlayer(FakeChatClient(["ACTION: call", "hmm"]), SETUPS["tools_memory"])
    assert keeps.decide(preflop_state()) == "call"
    detail, = keeps.take_hand_details()
    assert (detail.parsed_action, detail.self_check["second_action"], detail.self_check["flipped"]) == ("call", None, False)

    client = FakeChatClient(["no idea", "ACTION: raise_pot"])
    fixed = PokerLLMPlayer(client, SETUPS["tools"])
    assert fixed.decide(preflop_state()) == "raise_pot"
    assert client.calls[1][-1] == {"role": "user", "content": RECHECK_PROMPT_INVALID}
    detail, = fixed.take_hand_details()
    assert (detail.self_check["first_action"], detail.self_check["first_parse_status"]) == (None, "unparseable")


def test_the_harness_flags_are_logged_from_the_first_answer_but_never_shown_to_the_model():
    from poker.self_check import FREE_FOLD, recheck_prompt

    client = FakeChatClient(["ACTION: fold", "ACTION: fold"])
    player = PokerLLMPlayer(client, SETUPS["tools"])
    checkable = replace(flop_state(), to_call=0, menu=(MenuItem("fold"), MenuItem("check"), MenuItem("raise_pot", 18)))

    player.decide(checkable)

    detail, = player.take_hand_details()
    assert detail.flags == [FREE_FOLD]
    assert client.calls[1][-1]["content"] == recheck_prompt("fold")
    assert all(FREE_FOLD not in str(call) for call in client.calls)


def test_the_tools_setups_record_the_tool_versions_and_the_re_check_texts_in_the_run_metadata():
    from poker.equity_info import EQUITY_SAMPLES
    from poker.preflop_chart import PREFLOP_CHART_VERSION
    from poker.self_check import RECHECK_PROMPT_INVALID, SELF_CHECK_VERSION, recheck_prompt

    metadata = PokerLLMPlayer(FakeChatClient([]), SETUPS["tools"]).run_metadata()

    assert metadata["tools"] == {"equity_samples": EQUITY_SAMPLES, "preflop_chart_version": PREFLOP_CHART_VERSION,
                                 "self_check_version": SELF_CHECK_VERSION}
    assert metadata["recheck_prompts"] == {"valid": recheck_prompt("<first action>"), "invalid": RECHECK_PROMPT_INVALID}
    assert set(PokerLLMPlayer(FakeChatClient([]), SETUPS["memory"]).run_metadata()) == {
        "system_prompt", "prompt_version", "parser_version"}


def facing_a_shove(replies):
    """The model in the big blind facing the button's all-in (menu fold / call); returns its decision and detail."""
    player = PokerLLMPlayer(FakeChatClient(replies), SETUPS["tools"])
    record = play_hand(seed=1, players={"model": player, "bot": OneActionPlayer("all_in")}, button="bot")
    decision, = [d for d in record.decisions if d.player == "model"]
    detail, = player.take_hand_details()
    return decision, detail


def test_a_re_check_naming_a_raise_the_engine_applies_as_the_call_is_played_and_counts_as_a_flip():
    decision, detail = facing_a_shove(["ACTION: fold", "On reflection I shove.\nACTION: all_in"])

    assert [item.action for item in decision.state.menu] == ["fold", "call"]
    assert (decision.choice, decision.action, decision.fallback, decision.clamped) == ("all_in", "call", False, True)
    assert (detail.self_check["final_action"], detail.self_check["flipped"]) == ("all_in", True)
