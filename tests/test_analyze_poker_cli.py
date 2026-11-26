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
    rows = list(csv.DictReader((out / "summary.csv").open()))
    assert len(rows) == 1 and rows[0]["bot"] == "maniac"


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
