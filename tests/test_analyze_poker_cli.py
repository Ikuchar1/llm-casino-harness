"""End-to-end tests for scripts/analyze_poker.py on scripted-player runs (no Ollama)."""

import csv
import importlib.util
import json
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


def load_script(name):
    spec = importlib.util.spec_from_file_location(f"{name}_script", SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def play(monkeypatch, out, setup="plain", seed="2026", bot="maniac", pairs="6"):
    monkeypatch.setattr(sys, "argv", ["run_poker.py", "--player", "random", "--setup", setup, "--bot", bot,
                                      "--pairs", pairs, "--seed", seed, "--out", str(out)])
    assert load_script("run_poker").main() == 0
    return out


def test_analyzing_a_run_prints_its_table_and_writes_summary_json_and_csv(tmp_path, monkeypatch, capsys):
    run_dir = play(monkeypatch, tmp_path / "plain")
    capsys.readouterr()
    out = tmp_path / "results"

    code = load_script("analyze_poker").main([str(run_dir), "--out", str(out)])

    assert code == 0
    printed = capsys.readouterr().out
    for text in ("scripted-random", "plain", "maniac", "12 hands", "fold_to_bet_rate", "call_down_rate",
                 "bb/100", "VPIP", "PFR", "AF", "WTSD", "fallback"):
        assert text in printed, text
    summary = json.loads((out / "summary.json").read_text())
    (only,) = summary["runs"]
    assert (only["model"], only["setup"], only["bot"], only["hands"], only["pairs"]) == (
        "scripted-random", "plain", "maniac", 12, 6)
    assert set(only["habits"]) == {"fold_to_bet_rate", "call_down_rate"}
    assert only["trend"]["first_hands"] == 2 and only["trend"]["last_hands"] == 10
    assert only["bb_per_100"]["pairs"] == 6
    assert only["prompt_tokens_mean"] is None  # scripted players log no tokens
    assert only["seconds_per_decision"] is None  # nor call times
    assert "s/decision n/a" in printed
    rows = list(csv.DictReader((out / "summary.csv").open()))
    assert len(rows) == 1 and rows[0]["bot"] == "maniac"
    assert rows[0]["seconds_per_decision"] == ""


def test_the_fold_to_bet_rate_is_split_into_preflop_and_postflop_in_summary_json_and_csv(tmp_path, monkeypatch):
    run_dir = play(monkeypatch, tmp_path / "plain")
    out = tmp_path / "results"

    assert load_script("analyze_poker").main([str(run_dir), "--out", str(out)]) == 0

    (only,) = json.loads((out / "summary.json").read_text())["runs"]
    fold = only["habits"]["fold_to_bet_rate"]
    preflop, postflop = fold["fold_to_bet_preflop"], fold["fold_to_bet_postflop"]
    assert preflop["n"] > 0  # the maniac raises preflop every hand
    assert (preflop["k"] + postflop["k"], preflop["n"] + postflop["n"]) == (fold["k"], fold["n"])
    (row,) = list(csv.DictReader((out / "summary.csv").open()))
    assert (row["fold_to_bet_preflop_k"], row["fold_to_bet_preflop_n"]) == (str(preflop["k"]), str(preflop["n"]))
    assert (row["fold_to_bet_postflop_k"], row["fold_to_bet_postflop_n"]) == (str(postflop["k"]), str(postflop["n"]))
    assert "fold_to_bet_preflop_rate" in row and "fold_to_bet_postflop_rate" in row


def test_the_csv_carries_the_af_counts_so_an_infinite_af_and_an_undefined_af_differ(tmp_path, monkeypatch):
    run_dir = play(monkeypatch, tmp_path / "plain")
    out = tmp_path / "results"

    assert load_script("analyze_poker").main([str(run_dir), "--out", str(out)]) == 0

    (only,) = json.loads((out / "summary.json").read_text())["runs"]
    (row,) = list(csv.DictReader((out / "summary.csv").open()))
    assert row["af_bets_raises"] == str(only["profile"]["af_bets_raises"])
    assert row["af_calls"] == str(only["profile"]["af_calls"])


def test_compare_prints_the_paired_plain_vs_memory_comparison(tmp_path, monkeypatch, capsys):
    plain = play(monkeypatch, tmp_path / "plain")
    memory = play(monkeypatch, tmp_path / "memory", setup="memory")
    capsys.readouterr()
    out = tmp_path / "results"

    code = load_script("analyze_poker").main(["--compare", str(plain), str(memory), "--out", str(out)])

    assert code == 0
    printed = capsys.readouterr().out
    assert "memory - plain" in printed and "6 seed pairs" in printed and "bootstrap" in printed
    comparison = json.loads((out / "comparison.json").read_text())
    assert comparison["pairs"] == 6


def test_compare_refuses_runs_dealt_different_seeds(tmp_path, monkeypatch, capsys):
    plain = play(monkeypatch, tmp_path / "plain")
    other = play(monkeypatch, tmp_path / "other", setup="memory", seed="7")
    capsys.readouterr()

    code = load_script("analyze_poker").main(["--compare", str(plain), str(other), "--out", str(tmp_path / "r")])

    assert code == 2
    assert "seed list differs" in capsys.readouterr().err


def test_compare_refuses_a_run_whose_metadata_has_no_seed_list(tmp_path, monkeypatch, capsys):
    plain = play(monkeypatch, tmp_path / "plain")
    memory = play(monkeypatch, tmp_path / "memory", setup="memory")
    metadata = json.loads((memory / "metadata.json").read_text())
    del metadata["seeds"]
    (memory / "metadata.json").write_text(json.dumps(metadata))
    capsys.readouterr()

    code = load_script("analyze_poker").main(["--compare", str(plain), str(memory), "--out", str(tmp_path / "r")])

    assert code == 2
    assert "memory's metadata has no 'seeds'" in capsys.readouterr().err


class FlippingOllama:
    """First answers check/call; every re-check folds, so the re-check flips each decision."""

    def __init__(self, model, **kwargs):
        self.model = model

    def chat(self, system, user):
        from agent.ollama_client import ChatReply

        return ChatReply(content="ACTION: check/call", done_reason="stop", eval_count=3, latency_s=0.1)

    def chat_messages(self, messages):
        from agent.ollama_client import ChatReply

        return ChatReply(content="ACTION: fold", done_reason="stop", eval_count=3, latency_s=0.1)


def test_a_tools_run_reports_the_self_check_flip_rate_and_the_first_and_final_pass_fallback_rates(
        tmp_path, monkeypatch, capsys):
    run_poker = load_script("run_poker")
    monkeypatch.setattr(run_poker, "OllamaClient", FlippingOllama)
    monkeypatch.setattr(run_poker, "get_model_digest", lambda model: "sha256:abc")
    monkeypatch.setattr(run_poker, "get_ollama_version", lambda: "0.9.0")
    monkeypatch.setattr(sys, "argv", ["run_poker.py", "--model", "fake:1b", "--setup", "tools", "--bot", "maniac",
                                      "--pairs", "2", "--seed", "2026", "--out", str(tmp_path / "tools")])
    assert run_poker.main() == 0
    plain = play(monkeypatch, tmp_path / "plain")
    capsys.readouterr()

    assert load_script("analyze_poker").main([str(tmp_path / "tools"), str(plain), "--out", str(tmp_path / "results")]) == 0

    printed = capsys.readouterr().out
    assert "self-check flips" in printed
    tools, plain_summary = json.loads((tmp_path / "results" / "summary.json").read_text())["runs"]
    checked = tools["self_check"]
    assert checked["flips"]["k"] == checked["flips"]["n"] > 0  # fold differs from every check or call
    assert checked["first_pass_fallback"]["k"] == 0 and checked["final_fallback"]["k"] == 0
    assert plain_summary["self_check"] is None
    rows = list(csv.DictReader((tmp_path / "results" / "summary.csv").open()))
    assert rows[0]["self_check_flip_rate"] == "1.0" and rows[1]["self_check_flip_rate"] == ""
    assert rows[0]["first_pass_fallback_rate"] == "0.0"
