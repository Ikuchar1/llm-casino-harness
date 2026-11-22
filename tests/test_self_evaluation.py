"""Tests for self-evaluation (agent/llm_player.py + agent/run_log.py), with a fake chat client.

The hand used most: player 10, 7 against a dealer 6. Hard 17 vs 6 is a stand in basic
strategy, so stand is correct and hit or double is wrong.
"""

import pytest

from agent.config import BASELINE, get_config
from agent.llm_player import LLMPlayer
from agent.ollama_client import ChatReply
from agent.prompt import RECHECK_PROMPT, RECHECK_PROMPT_INVALID, recheck_prompt
from agent.run_log import SELF_EVAL_FIELDS, RunInfo, decision_rows
from analysis.paired import flip_stats
from blackjack.engine import play_hand

SELF = get_config("self")


def stacked(player_cards, dealer_cards, draws=()):
    p1, p2 = player_cards
    d_up, d_hole = dealer_cards
    return [p1, d_up, p2, d_hole, *draws] + ["2"] * 20


HARD_17_VS_6 = stacked(("10", "7"), ("6", "10"))


class FakeConversationClient:
    """Canned replies in order. Records single-turn calls and multi-turn conversations."""

    model = "fake:1b"

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []  # (system, user)
        self.conversations = []  # message lists

    def _reply(self, latency):
        return ChatReply(content=self.replies.pop(0), done_reason="stop", eval_count=11, latency_s=latency)

    def chat(self, system, user):
        self.calls.append((system, user))
        return self._reply(0.5)

    def chat_messages(self, messages):
        self.conversations.append([dict(m) for m in messages])
        return self._reply(0.75)


def info_for(config):
    return RunInfo(run_id="t", model="fake:1b", model_digest="sha256:x", harness_config=config, run_seed=1,
                   ollama_seed=42, prompt_version="baseline-v3", parser_version="parser-v2")


def play(replies, shoe=HARD_17_VS_6, config=SELF):
    client = FakeConversationClient(replies)
    player = LLMPlayer(client, config)
    record = play_hand(player, 1, 1, shoe=shoe)
    rows = decision_rows(record, player.take_hand_details(), info_for(config))
    return client, record, rows


# --- the re-check prompt -------------------------------------------------------------


def test_recheck_prompt_names_the_first_action_and_asks_for_the_action_line():
    assert recheck_prompt("hit") == (
        "You chose hit. Before you commit, re-check that choice against the rules and your cards. "
        "Then reply with your final answer as a final line of exactly the form "
        "`ACTION: <one of the legal actions>`."
    )
    assert recheck_prompt("hit") == RECHECK_PROMPT.format(first_action="hit")


def test_recheck_prompt_after_an_invalid_first_reply():
    assert recheck_prompt(None) == RECHECK_PROMPT_INVALID == (
        "Your reply did not contain a valid action. Re-check the rules and your cards, then reply with "
        "your final answer as a final line of exactly the form `ACTION: <one of the legal actions>`."
    )


@pytest.mark.parametrize("word", ["basic strategy", "wrong", "mistake", "odds", "probability", "should"])
def test_recheck_prompt_is_content_free(word):
    for text in (recheck_prompt("hit"), recheck_prompt(None)):
        assert word not in text.lower()


# --- the conversation ------------------------------------------------------------------


def test_second_call_continues_the_same_conversation():
    client, _, rows = play(["Reasoning.\nACTION: hit", "Rechecked.\nACTION: stand"])
    system, user = client.calls[0]
    assert client.conversations == [[
        {"role": "system", "content": system},
        {"role": "user", "content": user},
        {"role": "assistant", "content": "Reasoning.\nACTION: hit"},
        {"role": "user", "content": recheck_prompt("hit")},
    ]]
    assert rows[0]["prompt"] == {"system": system, "user": user}


def test_non_self_configs_make_one_call_and_have_no_self_eval_key():
    client, _, rows = play(["ACTION: stand"], config=BASELINE)
    assert len(client.calls) == 1 and client.conversations == []
    assert "self_eval" not in rows[0]


def test_every_self_eval_row_has_exactly_the_documented_keys():
    _, _, rows = play(["ACTION: hit", "ACTION: stand"])
    assert set(rows[0]["self_eval"]) == set(SELF_EVAL_FIELDS)
    for key in ("first_action", "first_valid", "first_correct", "second_action", "second_valid",
                "final_action", "flipped", "first_raw", "second_raw", "recheck_prompt",
                "done_reason", "eval_count", "latency_s"):
        assert key in SELF_EVAL_FIELDS


# --- outcomes ------------------------------------------------------------------------


def test_fix_wrong_first_answer_corrected_and_the_final_answer_is_graded():
    _, record, rows = play(["ACTION: hit", "On reflection.\nACTION: stand"])
    row = rows[0]
    assert record.decisions[0].action_taken == "stand"
    assert (row["parsed_action"], row["action_taken"], row["correct"], row["invalid"]) == ("stand", "stand", True, False)
    assert row["invalid_reason"] is None
    assert row["raw_response"] == "ACTION: hit"  # the first reply; the second is in self_eval
    se = row["self_eval"]
    assert se == {
        "first_action": "hit", "first_valid": True, "first_correct": False, "first_invalid_reason": None,
        "second_action": "stand", "second_valid": True, "second_invalid_reason": None,
        "final_action": "stand", "flipped": True,
        "first_raw": "ACTION: hit", "second_raw": "On reflection.\nACTION: stand",
        "recheck_prompt": recheck_prompt("hit"),
        "done_reason": "stop", "eval_count": 11, "latency_s": 0.75,
    }
    stats = flip_stats(rows)
    assert (stats.flips, stats.fixes, stats.breaks, stats.neutral) == (1, 1, 0, 0)


def test_break_right_first_answer_changed_to_a_wrong_one():
    # Hit draws a 2 (19); the second decision stands both times.
    _, record, rows = play(["ACTION: stand", "ACTION: hit", "ACTION: stand", "ACTION: stand"])
    assert [d.action_taken for d in record.decisions] == ["hit", "stand"]
    first = rows[0]
    assert (first["action_taken"], first["correct"]) == ("hit", False)
    assert (first["self_eval"]["first_correct"], first["self_eval"]["flipped"]) == (True, True)
    assert rows[1]["self_eval"]["flipped"] is False
    stats = flip_stats(rows)
    assert (stats.n, stats.flips, stats.fixes, stats.breaks, stats.neutral) == (2, 1, 0, 1, 0)


def test_neutral_flip_wrong_to_a_different_wrong():
    _, _, rows = play(["ACTION: hit", "ACTION: double"])
    row = rows[0]
    assert (row["action_taken"], row["correct"], row["self_eval"]["flipped"]) == ("double", False, True)
    stats = flip_stats(rows)
    assert (stats.flips, stats.fixes, stats.breaks, stats.neutral) == (1, 0, 0, 1)


def test_same_answer_twice_is_not_a_flip():
    _, _, rows = play(["ACTION: stand", "Still stand.\nACTION: stand"])
    assert rows[0]["self_eval"]["flipped"] is False
    assert rows[0]["correct"] is True


def test_invalid_second_reply_keeps_the_first_answer_and_is_not_invalid():
    _, record, rows = play(["ACTION: stand", "Let me think about it more."])
    row = rows[0]
    assert record.decisions[0].is_valid
    assert (row["parsed_action"], row["action_taken"], row["correct"], row["invalid"]) == ("stand", "stand", True, False)
    se = row["self_eval"]
    assert (se["second_action"], se["second_valid"], se["second_invalid_reason"]) == (None, False, "no_action")
    assert (se["final_action"], se["flipped"]) == ("stand", False)
    assert flip_stats(rows).second_invalid == 1


def test_invalid_first_reply_gets_the_invalid_recheck_and_a_valid_second_counts():
    client, _, rows = play(["I would stand.", "ACTION: stand"])
    assert client.conversations[0][-1] == {"role": "user", "content": RECHECK_PROMPT_INVALID}
    row = rows[0]
    assert (row["parsed_action"], row["correct"], row["invalid"], row["invalid_reason"]) == ("stand", True, False, None)
    se = row["self_eval"]
    assert (se["first_action"], se["first_valid"], se["first_correct"], se["first_invalid_reason"]) == (
        None, False, False, "no_action")
    assert (se["final_action"], se["flipped"]) == ("stand", True)
    assert flip_stats(rows).fixes == 1


def test_both_replies_invalid_is_an_invalid_decision():
    _, record, rows = play(["Hmm.", "Hmm again."])
    assert record.decisions[0].is_valid is False
    assert record.decisions[0].action_taken == "stand"  # the engine's fallback
    row = rows[0]
    assert (row["parsed_action"], row["invalid"], row["correct"], row["invalid_reason"]) == (None, True, False, "no_action")
    se = row["self_eval"]
    assert (se["first_valid"], se["second_valid"], se["final_action"], se["flipped"]) == (False, False, None, False)


def test_illegal_first_action_is_invalid_and_uses_the_invalid_recheck():
    # After a hit the hand has 3 cards, so double is illegal at the second decision.
    replies = ["ACTION: hit", "ACTION: hit", "ACTION: double", "ACTION: stand"]
    client, _, rows = play(replies, shoe=stacked(("5", "4"), ("10", "7"), ["2"]))
    assert client.conversations[1][-1]["content"] == RECHECK_PROMPT_INVALID
    se = rows[1]["self_eval"]
    assert (se["first_action"], se["first_invalid_reason"], se["final_action"]) == (None, "illegal", "stand")
    assert rows[1]["invalid"] is False


def test_prob_strat_self_sends_odds_and_principles_and_re_checks():
    client, _, rows = play(["ACTION: stand", "ACTION: stand"], config=get_config("prob_strat_self"))
    system, user = client.calls[0]
    assert "Strategy principles" in system and "Odds (" in user
    assert rows[0]["self_eval"]["second_action"] == "stand"
