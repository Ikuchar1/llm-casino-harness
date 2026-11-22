"""Tests for scripts/compare_configs.py on small synthetic run folders."""

import importlib.util
import json
from pathlib import Path

import pytest

from test_paired import _self_eval_row, flags, natural_run, row, scenario_run

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "compare_configs.py"


def load_script():
    spec = importlib.util.spec_from_file_location("compare_configs_script", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_run(path: Path, run) -> Path:
    path.mkdir(parents=True)
    (path / "metadata.json").write_text(json.dumps(run.metadata))
    (path / "decisions.jsonl").write_text("".join(json.dumps(r) + "\n" for r in run.decisions))
    (path / "hands.jsonl").write_text("".join(json.dumps(h) + "\n" for h in run.hands))
    return path


@pytest.fixture
def runs(tmp_path):
    base_flags, prob_flags = flags(a=10, b=1, c=9, d=4)  # p = 22/1024
    strat_flags = [True] * 11 + [False] * 9 + [True] * 4  # vs base: b=0, c=4
    base = write_run(tmp_path / "base_nat", natural_run(base_flags))
    prob = write_run(tmp_path / "prob_nat", natural_run(prob_flags, config="prob"))
    strat = write_run(tmp_path / "strat_nat", natural_run(strat_flags, config="strat"))
    base_s = write_run(tmp_path / "base_scen", scenario_run({"a": True, "b": False, "c": False}))
    self_rows = scenario_run({"a": True, "b": True, "c": False}, config="self")
    self_rows.decisions[0]["self_eval"] = _self_eval_row(1, True, True, False)["self_eval"]
    self_rows.decisions[2]["self_eval"] = _self_eval_row(2, False, True, True)["self_eval"]
    self_rows.decisions[4]["self_eval"] = _self_eval_row(3, True, False, True, second_valid=False)["self_eval"]
    self_s = write_run(tmp_path / "self_scen", self_rows)
    return {"base": base, "prob": prob, "strat": strat, "base_s": base_s, "self_s": self_s, "tmp": tmp_path}


def test_cli_prints_markdown_and_writes_json(runs, capsys):
    script = load_script()
    out = runs["tmp"] / "out"
    code = script.main(["--baseline", str(runs["base"]), str(runs["prob"]), str(runs["strat"]), "--out", str(out)])
    assert code == 0
    printed = capsys.readouterr().out
    assert "| prob |" in printed and "| strat |" in printed
    assert "Newcombe" in printed and "Holm" in printed

    data = json.loads((out / "comparison.json").read_text())
    assert (out / "comparison.md").read_text().strip() == printed.strip()
    natural = data["families"]["natural"]
    prob = next(c for c in natural if c["config"] == "prob")
    strat = next(c for c in natural if c["config"] == "strat")
    assert (prob["b"], prob["c"], prob["n"]) == (1, 9, 24)
    assert prob["p_raw"] == pytest.approx(22 / 1024)
    # strat vs base: base right on hands 1-11, strat right on 1-11 and 21-24 -> b=0, c=4, p=2/16
    assert (strat["b"], strat["c"]) == (0, 4)
    assert strat["p_raw"] == pytest.approx(2 / 16)
    # Holm over 2: smaller p doubled, larger max(itself, that)
    assert prob["p_holm"] == pytest.approx(2 * 22 / 1024)
    assert strat["p_holm"] == pytest.approx(max(2 / 16, 2 * 22 / 1024))
    assert data["families"]["scenario"] == []


def test_families_are_corrected_separately(runs):
    script = load_script()
    report = script.build_report([runs["base"], runs["base_s"]], [runs["prob"], runs["self_s"]])
    natural, scenario = report["families"]["natural"], report["families"]["scenario"]
    assert len(natural) == 1 and len(scenario) == 1
    # one comparison per family -> Holm leaves each p unchanged
    assert natural[0]["p_holm"] == pytest.approx(natural[0]["p_raw"])
    assert scenario[0]["p_holm"] == pytest.approx(scenario[0]["p_raw"])


def test_scenario_self_eval_flips_and_later_decisions(runs):
    script = load_script()
    report = script.build_report([runs["base_s"]], [runs["self_s"]])
    flips = report["flips"]["self"]
    assert (flips["n"], flips["flips"], flips["fixes"], flips["breaks"], flips["second_invalid"]) == (3, 2, 1, 1, 1)
    later = {entry["config"]: entry for entry in report["later_decisions"]}
    assert later["self"]["n"] == 3 and later["baseline"]["n"] == 3


def test_covered_breakdown_with_injected_classifier(runs):
    script = load_script()
    report = script.build_report([runs["base"]], [runs["prob"]], classifier=lambda r: r["hand_number"] <= 11)
    cov = {entry["config"]: entry for entry in report["coverage"]}
    assert cov["baseline"]["covered"]["n"] == 11 and cov["baseline"]["covered"]["k"] == 11
    assert cov["prob"]["uncovered"]["k"] == 9


def test_no_matching_baseline_is_an_error(runs, capsys):
    script = load_script()
    with pytest.raises(SystemExit):
        script.main(["--baseline", str(runs["base"]), str(runs["self_s"])])
    assert "baseline" in capsys.readouterr().err


def test_pairing_mismatch_is_reported_clearly(runs, capsys):
    script = load_script()
    other = write_run(runs["tmp"] / "seed7", natural_run(flags(10, 1, 9, 4)[1], seed=7, config="prob7"))
    with pytest.raises(SystemExit):
        script.main(["--baseline", str(runs["base"]), str(other)])
    assert "seed" in capsys.readouterr().err


def test_config_name_falls_back_to_folder(runs):
    script = load_script()
    run = natural_run(flags(10, 1, 9, 4)[1], config=None)
    folder = write_run(runs["tmp"] / "my_config_run", run)
    report = script.build_report([runs["base"]], [folder])
    assert report["families"]["natural"][0]["config"] == "my_config_run"


def test_dropped_pairs_are_reported(runs):
    script = load_script()
    run = natural_run(flags(10, 1, 9, 4)[1], config="prob")
    run.decisions = [r for r in run.decisions if r["hand_number"] != 3]
    folder = write_run(runs["tmp"] / "prob_missing", run)
    report = script.build_report([runs["base"]], [folder])
    entry = report["families"]["natural"][0]
    assert entry["dropped"] == 1 and entry["n"] == 23


def test_run_passed_as_baseline_and_config_is_listed_once(runs):
    script = load_script()
    report = script.build_report([runs["base"]], [runs["base"]])
    assert len(report["later_decisions"]) == 1
    assert report["families"]["natural"][0]["b"] == 0


def test_covered_hook_uses_strategy_info_when_present(runs):
    script = load_script()
    classifier = script.load_covered_classifier()
    if classifier is None:
        pytest.skip("agent/strategy_info.py not available")
    eights = row(1, True, cards=("8", "8"), upcard="10")
    eights.update(is_pair=True, total=16)
    assert classifier(eights) is True  # "always split aces and eights"


def test_cli_covered_flag_adds_the_breakdown(runs, capsys):
    script = load_script()
    script.main(["--baseline", str(runs["base"]), str(runs["prob"]), "--covered"])
    out = capsys.readouterr()
    assert "Covered vs uncovered" in out.out or "not available" in out.err
