"""Tests for the poker match runner (poker/runner.py), with scripted players only."""

import importlib.metadata
import json

import pytest

from agent.config import HarnessConfig
from agent.ollama_client import ChatReply
from poker.llm_player import PLAIN, PokerLLMPlayer
from poker.parser import PARSER_VERSION
from poker.prompt import PROMPT_VERSION
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
