"""Tests for the poker match runner (poker/runner.py), with scripted players only."""

import importlib.metadata
import json

import pytest

from agent.config import HarnessConfig
from agent.ollama_client import ChatReply
from poker.llm_player import MEMORY, PLAIN, PokerLLMPlayer
from poker.memory import MEMORY_VERSION, REWRITE_SYSTEM_PROMPT, memory_settings
from poker.parser import PARSER_VERSION
from poker.prompt import PROMPT_VERSION, notes_block
from poker.runner import BOT, MODEL, MatchSpec, deal_schedule, match_seeds, resolve_bot, run_match


def test_the_seed_list_depends_only_on_the_base_seed_and_grows_by_appending():
    assert match_seeds(2026, 5) == match_seeds(2026, 5)
    assert match_seeds(2026, 8)[:5] == match_seeds(2026, 5)
    assert match_seeds(2027, 5) != match_seeds(2026, 5)
    assert len(set(match_seeds(2026, 50))) == 50


def test_each_seed_is_dealt_twice_in_a_row_with_the_model_on_the_button_first():
    schedule = deal_schedule([11, 22])

    assert [(deal.hand_number, deal.seed, deal.button) for deal in schedule] == [
        (0, 11, MODEL), (1, 11, BOT), (2, 22, MODEL), (3, 22, BOT),
    ]


class CheckCallPlayer:
    """Checks when it can, else calls."""

    def decide(self, state):
        return "check" if any(item.action == "check" for item in state.menu) else "call"


def test_a_bot_is_made_fresh_by_name_from_the_registry_given():
    registry = {"scripted": CheckCallPlayer}

    bot = resolve_bot("scripted", registry)
    assert isinstance(bot, CheckCallPlayer) and bot is not resolve_bot("scripted", registry)


def test_without_a_registry_the_leak_bots_module_is_used():
    from poker.bots import BOTS

    name = next(iter(BOTS))
    assert isinstance(resolve_bot(name), BOTS[name])


def test_an_unknown_bot_name_is_refused_with_the_known_names():
    with pytest.raises(ValueError, match="unknown bot 'nobody'.*scripted"):
        resolve_bot("nobody", {"scripted": CheckCallPlayer})


def spec(**changes):
    values = {"model": "fake:1b", "setup": PLAIN, "bot": "scripted", "base_seed": 7, "n_pairs": 2}
    return MatchSpec(**{**values, **changes})


def run(out, player=None, **changes):
    return run_match(out, spec(**changes), player or CheckCallPlayer(), bots={"scripted": CheckCallPlayer})


def test_a_match_writes_metadata_with_the_run_identity(tmp_path):
    run(tmp_path / "run")

    metadata = json.loads((tmp_path / "run" / "metadata.json").read_text())
    assert metadata["run_id"].startswith("poker_plain_fake-1b_vs_scripted_seed7_")
    assert (metadata["model"], metadata["setup"], metadata["bot"]) == ("fake:1b", "plain", "scripted")
    assert metadata["setup_flags"] == PLAIN.flags()
    assert (metadata["base_seed"], metadata["n_pairs"], metadata["seeds"]) == (7, 2, match_seeds(7, 2))
    assert metadata["pokerkit_version"] == importlib.metadata.version("pokerkit")
    assert metadata["git_commit"] is None or len(metadata["git_commit"]) >= 40
    assert (metadata["prompt_version"], metadata["parser_version"]) == (PROMPT_VERSION, PARSER_VERSION)
    assert metadata["sessions"][-1]["status"] == "completed"


class AlwaysClient:
    """A fake chat client that always gives the same reply."""

    model = "fake:1b"

    def __init__(self, reply):
        self.reply = reply

    def chat(self, system, user):
        return ChatReply(content=self.reply, done_reason="stop", eval_count=7, latency_s=0.25, prompt_eval_count=640)


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_every_row_carries_the_run_identity_and_model_decisions_carry_the_llm_detail(tmp_path):
    run(tmp_path / "run", PokerLLMPlayer(AlwaysClient("Keep it cheap.\nACTION: check/call")))

    out = tmp_path / "run"
    run_id = json.loads((out / "metadata.json").read_text())["run_id"]
    hands, decisions = read_jsonl(out / "hands.jsonl"), read_jsonl(out / "decisions.jsonl")
    identity = {"run_id": run_id, "model": "fake:1b", "setup": "plain", "bot": "scripted"}
    assert [row["hand_number"] for row in hands] == [0, 1, 2, 3]
    assert all({key: row[key] for key in identity} == identity for row in hands + decisions)
    assert list(decisions[0])[:4] == list(identity)

    model_rows = [row for row in decisions if row["player"] == MODEL]
    bot_rows = [row for row in decisions if row["player"] == BOT]
    assert model_rows and bot_rows
    first = model_rows[0]
    assert first["raw_response"] == "Keep it cheap.\nACTION: check/call"
    assert (first["parse_status"], first["parse_method"], first["mapping"]) == ("mapped", "action_line", "check/call -> " + first["action"])
    assert first["prompt"].startswith("You are on the button") and first["latency_s"] == 0.25
    assert (first["prompt_tokens"], first["eval_count"]) == (640, 7)
    assert all(row["parse_status"] is None and row["raw_response"] is None for row in bot_rows)
    assert all(set(row) == set(first) for row in decisions)


class CrashesInTheBigBlind(CheckCallPlayer):
    """Like Ollama going down at the model's first big-blind decision: hand 1, the second deal of pair 0."""

    def decide(self, state):
        if not state.is_button:
            raise RuntimeError("Ollama is down")
        return super().decide(state)


def without_run_id(rows):
    return [{key: value for key, value in row.items() if key != "run_id"} for row in rows]


def test_a_match_interrupted_halfway_through_a_pair_resumes_by_replaying_only_the_missing_deal(tmp_path):
    out = tmp_path / "run"
    with pytest.raises(RuntimeError):
        run(out, CrashesInTheBigBlind())
    assert [row["hand_number"] for row in read_jsonl(out / "hands.jsonl")] == [0]
    assert json.loads((out / "metadata.json").read_text())["sessions"][-1]["status"] == "error"

    played = []
    run_match(out, spec(), CheckCallPlayer(), bots={"scripted": CheckCallPlayer}, on_hand=lambda p: played.append(p.hand_number))

    assert played == [1, 2, 3]
    run(tmp_path / "clean")
    for name in ("hands.jsonl", "decisions.jsonl"):
        assert without_run_id(read_jsonl(out / name)) == without_run_id(read_jsonl(tmp_path / "clean" / name))
    metadata = json.loads((out / "metadata.json").read_text())
    assert {row["run_id"] for row in read_jsonl(out / "decisions.jsonl")} == {metadata["run_id"]}
    assert [session["status"] for session in metadata["sessions"]] == ["error", "completed"]
    second = read_jsonl(out / "hands.jsonl")[1]
    assert (second["seed"], second["button"]) == (match_seeds(7, 2)[0], BOT)


@pytest.mark.parametrize("change", [{"model": "other:7b"}, {"bot": "other"}, {"base_seed": 8}, {"setup": HarnessConfig("tools")}])
def test_resuming_with_a_different_model_bot_seed_or_setup_is_refused_before_anything_is_played(tmp_path, change):
    out = tmp_path / "run"
    run(out, n_pairs=1)
    before = (out / "hands.jsonl").read_text()

    with pytest.raises(ValueError, match="cannot resume"):
        run_match(out, spec(n_pairs=2, **change), CheckCallPlayer(), bots={"scripted": CheckCallPlayer, "other": CheckCallPlayer})
    assert (out / "hands.jsonl").read_text() == before
    assert len(json.loads((out / "metadata.json").read_text())["sessions"]) == 1


def test_resuming_a_run_started_under_the_poker_v2_prompt_is_refused_because_of_the_prompt_version(tmp_path):
    out = tmp_path / "run"
    run(out, n_pairs=1)
    metadata = json.loads((out / "metadata.json").read_text())
    (out / "metadata.json").write_text(json.dumps({**metadata, "prompt_version": "poker-v2"}))
    before = (out / "hands.jsonl").read_text()

    with pytest.raises(ValueError, match="cannot resume.*prompt_version='poker-v2', not 'poker-v4'"):
        run(out, n_pairs=2)
    assert (out / "hands.jsonl").read_text() == before
    assert len(json.loads((out / "metadata.json").read_text())["sessions"]) == 1


def test_resuming_a_run_started_under_the_v2_parser_is_refused_because_bare_raises_now_parse(tmp_path):
    out = tmp_path / "run"
    run(out, n_pairs=1)
    metadata = json.loads((out / "metadata.json").read_text())
    (out / "metadata.json").write_text(json.dumps({**metadata, "parser_version": "poker-parser-v2"}))

    with pytest.raises(ValueError, match="cannot resume.*parser_version='poker-parser-v2', not 'poker-parser-v3'"):
        run(out, n_pairs=2)


def ollama_facts(digest, version="0.9.0"):
    return {"model_digest": digest, "ollama_version": version}


def test_resuming_after_the_model_digest_changed_is_refused_before_anything_is_played(tmp_path):
    out = tmp_path / "run"
    run_match(out, spec(n_pairs=1), CheckCallPlayer(), bots={"scripted": CheckCallPlayer},
              extra_metadata=ollama_facts("sha256:old"))
    before = (out / "hands.jsonl").read_text()

    with pytest.raises(ValueError, match="cannot resume.*model_digest"):
        run_match(out, spec(n_pairs=2), CheckCallPlayer(), bots={"scripted": CheckCallPlayer},
                  extra_metadata=ollama_facts("sha256:new"))
    assert (out / "hands.jsonl").read_text() == before
    assert len(json.loads((out / "metadata.json").read_text())["sessions"]) == 1


def test_a_resume_keeps_the_original_model_digest_and_ollama_version_and_records_each_sessions_platform(tmp_path):
    out = tmp_path / "run"
    run_match(out, spec(n_pairs=1), CheckCallPlayer(), bots={"scripted": CheckCallPlayer},
              extra_metadata=ollama_facts("sha256:same", "0.9.0"), session_metadata={"hostname": "mac"})
    run_match(out, spec(n_pairs=2), CheckCallPlayer(), bots={"scripted": CheckCallPlayer},
              extra_metadata=ollama_facts("sha256:same", "0.9.1"), session_metadata={"hostname": "hcc-node"})

    metadata = json.loads((out / "metadata.json").read_text())
    assert (metadata["model_digest"], metadata["ollama_version"]) == ("sha256:same", "0.9.0")
    assert [session["hostname"] for session in metadata["sessions"]] == ["mac", "hcc-node"]
    assert all(session["status"] == "completed" for session in metadata["sessions"])


def test_each_session_records_the_git_commit_it_ran_on_and_the_top_level_commit_is_kept(tmp_path):
    out = tmp_path / "run"
    run(out, n_pairs=1)
    run(out, n_pairs=2)

    metadata = json.loads((out / "metadata.json").read_text())
    assert len(metadata["sessions"]) == 2
    assert all("git_commit" in session for session in metadata["sessions"])
    assert metadata["sessions"][-1]["git_commit"] == metadata["git_commit"]


# ---------- The memory setup ----------

NOTES_REPLY = "checks whenever it can | key checked_to.check | for 1 | against 0"


class NotesClient:
    """Check/call for every decision, the same notes for every rewrite; optionally fails once on a given call."""

    model = "fake:1b"

    def __init__(self, fail_on=None):
        self.fail_on = fail_on  # (system, user) -> True to raise, like Ollama going down
        self.rewrites = 0
        self.failed = False

    def chat(self, system, user):
        if self.fail_on and not self.failed and self.fail_on(self, system, user):
            self.failed = True
            raise RuntimeError("Ollama is down")
        if system == REWRITE_SYSTEM_PROMPT:
            self.rewrites += 1
            return ChatReply(content=NOTES_REPLY, done_reason="stop", eval_count=20, latency_s=0.5, prompt_eval_count=900)
        return ChatReply(content="ACTION: check/call", done_reason="stop", eval_count=7, latency_s=0.25, prompt_eval_count=640)


def memory_run(out, client=None, n_pairs=6):
    player = PokerLLMPlayer(client or NotesClient(), MEMORY)
    return run_match(out, spec(setup=MEMORY, n_pairs=n_pairs), player, bots={"scripted": CheckCallPlayer})


def test_a_plain_run_writes_no_memory_log_and_its_rows_have_no_notes_version(tmp_path):
    run(tmp_path / "run", PokerLLMPlayer(AlwaysClient("ACTION: check/call")))

    assert not (tmp_path / "run" / "memory.jsonl").exists()
    assert all(row["notes_version"] is None for row in read_jsonl(tmp_path / "run" / "decisions.jsonl"))
    assert json.loads((tmp_path / "run" / "metadata.json").read_text())["memory"] is None


def test_a_memory_run_logs_each_rewrite_after_the_hand_it_followed_with_its_call_details(tmp_path):
    memory_run(tmp_path / "run")

    out = tmp_path / "run"
    run_id = json.loads((out / "metadata.json").read_text())["run_id"]
    events = read_jsonl(out / "memory.jsonl")
    assert [(e["notes_version"], e["hand_number"], e["hands_seen"]) for e in events] == [(0, 5, 6), (1, 9, 10)]
    first = events[0]
    assert {key: first[key] for key in ("run_id", "model", "setup", "bot")} == {
        "run_id": run_id, "model": "fake:1b", "setup": "memory", "bot": "scripted"}
    assert first["rewrite_prompt"].startswith("You are playing heads-up") and "hand 5:" in first["rewrite_prompt"]
    assert first["raw_response"] == NOTES_REPLY and first["verified_notes"][0]["text"] == "checks whenever it can"
    assert (first["latency_s"], first["eval_count"], first["prompt_tokens"], first["done_reason"]) == (0.5, 20, 900, "stop")
    assert first["notes_block"].startswith('- "checks whenever it can" — evidence:')


def test_decision_prompts_differ_from_the_plain_runs_only_by_the_notes_block_in_effect_and_log_its_version(tmp_path):
    run_match(tmp_path / "plain", spec(n_pairs=6), PokerLLMPlayer(NotesClient()), bots={"scripted": CheckCallPlayer})
    memory_run(tmp_path / "memory")

    events = read_jsonl(tmp_path / "memory" / "memory.jsonl")
    plain = [row for row in read_jsonl(tmp_path / "plain" / "decisions.jsonl") if row["player"] == MODEL]
    memory = [row for row in read_jsonl(tmp_path / "memory" / "decisions.jsonl") if row["player"] == MODEL]
    assert len(plain) == len(memory)
    versions = {row["hand_number"]: row["notes_version"] for row in memory}
    assert versions == {hand: None if hand <= 5 else 0 if hand <= 9 else 1 for hand in range(12)}
    for before, after in zip(plain, memory):
        if after["notes_version"] is None:
            assert after["prompt"] == before["prompt"]
        else:
            block = notes_block(events[after["notes_version"]]["notes_block"])
            assert after["prompt"] == before["prompt"].replace("Legal actions:", block + "Legal actions:")
    bot_rows = [row for row in read_jsonl(tmp_path / "memory" / "decisions.jsonl") if row["player"] == BOT]
    assert all(row["notes_version"] is None for row in bot_rows)


def test_a_memory_run_records_the_memory_settings_in_its_metadata(tmp_path):
    memory_run(tmp_path / "run")

    metadata = json.loads((tmp_path / "run" / "metadata.json").read_text())
    assert metadata["setup"] == "memory" and metadata["setup_flags"]["memory"] is True
    assert metadata["memory"] == memory_settings()
    assert metadata["memory"]["rewrite_every"] == 5 and metadata["memory"]["rewrite_system_prompt"] == REWRITE_SYSTEM_PROMPT


def test_resuming_a_memory_run_started_under_another_memory_version_is_refused_before_anything_is_played(tmp_path):
    out = tmp_path / "run"
    memory_run(out, n_pairs=3)
    metadata = json.loads((out / "metadata.json").read_text())
    metadata["memory"]["memory_version"] = "memory-v1"
    (out / "metadata.json").write_text(json.dumps(metadata))
    before = [(out / name).read_text() for name in ("hands.jsonl", "decisions.jsonl", "memory.jsonl")]

    with pytest.raises(ValueError, match=f"cannot resume.*memory_version='memory-v1', not '{MEMORY_VERSION}'"):
        memory_run(out, n_pairs=6)
    assert [(out / name).read_text() for name in ("hands.jsonl", "decisions.jsonl", "memory.jsonl")] == before
    assert len(json.loads((out / "metadata.json").read_text())["sessions"]) == 1


def in_the_big_blind_after_the_first_rewrite(client, system, user):
    """Hand 7: the second deal of pair 3, so its first deal (hand 6) is still pending in memory."""
    return client.rewrites == 1 and user.startswith("You are in the big blind")


def during_the_first_rewrite(client, system, user):
    """After hand 5 was written, before its rewrite was logged."""
    return system == REWRITE_SYSTEM_PROMPT


@pytest.mark.parametrize("fail_on", [in_the_big_blind_after_the_first_rewrite, during_the_first_rewrite])
def test_an_interrupted_memory_run_resumes_to_the_same_hands_rewrites_and_notes_versions_as_an_uninterrupted_one(tmp_path, fail_on):
    out = tmp_path / "run"
    with pytest.raises(RuntimeError):
        memory_run(out, NotesClient(fail_on))

    resumed = NotesClient()
    memory_run(out, resumed)
    memory_run(tmp_path / "clean")

    for name in ("hands.jsonl", "decisions.jsonl", "memory.jsonl"):
        assert without_run_id(read_jsonl(out / name)) == without_run_id(read_jsonl(tmp_path / "clean" / name))
    assert resumed.rewrites == (1 if fail_on is in_the_big_blind_after_the_first_rewrite else 2)
    assert [s["status"] for s in json.loads((out / "metadata.json").read_text())["sessions"]] == ["error", "completed"]


def test_resuming_a_memory_run_whose_memory_log_lost_a_rewrite_before_later_hands_is_refused(tmp_path):
    out = tmp_path / "run"
    memory_run(out, n_pairs=5)
    (out / "memory.jsonl").write_text("")

    with pytest.raises(ValueError, match="cannot resume.*no logged rewrite after hand 5"):
        memory_run(out, n_pairs=6)


class ToolsClient(AlwaysClient):
    """Check/call first, and the same on every re-check."""

    def __init__(self):
        super().__init__("ACTION: check/call")
        self.rechecks = 0

    def chat_messages(self, messages):
        self.rechecks += 1
        return ChatReply(content="Still fine.\nACTION: check/call", done_reason="stop", eval_count=9, latency_s=0.125,
                         prompt_eval_count=700)


def tools_run(out, n_pairs=2):
    from poker.llm_player import TOOLS

    return run_match(out, spec(setup=TOOLS, n_pairs=n_pairs), PokerLLMPlayer(ToolsClient(), TOOLS),
                     bots={"scripted": CheckCallPlayer})


def test_a_tools_run_logs_the_tools_the_re_check_and_the_flags_on_model_rows_and_its_tool_versions(tmp_path):
    from poker.llm_player import TOOLS, tools_settings

    tools_run(tmp_path / "run")

    decisions = read_jsonl(tmp_path / "run" / "decisions.jsonl")
    model_rows = [row for row in decisions if row["player"] == MODEL]
    first = model_rows[0]
    assert first["prompt"].count("Equity (worked out by the harness") == 1 and "Preflop chart" in first["prompt"]
    assert set(first["tools"]) == {"equity", "pot_odds", "equity_seed", "equity_samples", "hand_class", "spot", "chart_play"}
    assert first["self_check"]["second_raw"] == "Still fine.\nACTION: check/call" and first["self_check"]["flipped"] is False
    assert first["flags"] == []
    assert all(row["tools"] is None and row["self_check"] is None and row["flags"] is None
               for row in decisions if row["player"] == BOT)
    metadata = json.loads((tmp_path / "run" / "metadata.json").read_text())
    assert metadata["tools"] == tools_settings(TOOLS) and metadata["setup"] == "tools"


def test_a_plain_run_has_no_tools_in_its_metadata_or_rows(tmp_path):
    run(tmp_path / "run", PokerLLMPlayer(AlwaysClient("ACTION: check/call")))

    assert json.loads((tmp_path / "run" / "metadata.json").read_text())["tools"] is None
    rows = read_jsonl(tmp_path / "run" / "decisions.jsonl")
    assert all(row["tools"] is None and row["self_check"] is None and row["flags"] is None for row in rows)


def test_resuming_a_tools_run_started_under_another_chart_version_is_refused_before_anything_is_played(tmp_path):
    out = tmp_path / "run"
    tools_run(out, n_pairs=1)
    metadata = json.loads((out / "metadata.json").read_text())
    metadata["tools"]["preflop_chart_version"] = "preflop-chart-v0"
    (out / "metadata.json").write_text(json.dumps(metadata))
    before = (out / "decisions.jsonl").read_text()

    with pytest.raises(ValueError, match="cannot resume.*preflop-chart-v0"):
        tools_run(out, n_pairs=2)
    assert (out / "decisions.jsonl").read_text() == before


def test_resuming_a_tools_run_started_under_another_equity_version_is_refused_before_anything_is_played(tmp_path):
    from poker.equity_info import EQUITY_VERSION

    out = tmp_path / "run"
    tools_run(out, n_pairs=1)
    metadata = json.loads((out / "metadata.json").read_text())
    assert metadata["tools"]["equity_version"] == EQUITY_VERSION
    metadata["tools"]["equity_version"] = "equity-v0"
    (out / "metadata.json").write_text(json.dumps(metadata))
    before = (out / "decisions.jsonl").read_text()

    with pytest.raises(ValueError, match="cannot resume.*equity-v0"):
        tools_run(out, n_pairs=2)
    assert (out / "decisions.jsonl").read_text() == before
