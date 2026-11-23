"""Tests for the final ablation report (analysis/ablation_report.py, analysis/ablation_charts.py,
scripts/ablation_report.py) on small synthetic run folders."""

import importlib.util
import json
import re
from pathlib import Path

import pytest

from analysis.ablation_report import (
    BOTH_RIGHT,
    BROKE,
    CONFIG_ORDER,
    FIXED,
    NATURAL,
    SCENARIO,
    build_report,
    discover_run_dirs,
    expected_folder,
    latex_coverage_table,
    latex_escape,
    latex_flips_table,
    latex_main_table,
    latex_num,
    markdown_main_table,
    model_label,
    parse_folder_name,
)
from analysis.paired import compare_to_baseline, holm_adjust
from test_paired import flags, natural_run, scenario_run

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "ablation_report.py"
SMALL = "qwen2.5:7b"
BIG = "qwen2.5:14b"


def load_script():
    spec = importlib.util.spec_from_file_location("ablation_report_script", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_run(path: Path, run) -> Path:
    path.mkdir(parents=True)
    (path / "metadata.json").write_text(json.dumps(run.metadata))
    (path / "decisions.jsonl").write_text("".join(json.dumps(r) + "\n" for r in run.decisions))
    (path / "hands.jsonl").write_text("".join(json.dumps(h) + "\n" for h in run.hands))
    return path


def with_self_eval(run, flipped_to_right=1):
    """Mark the first decisions as self-evaluated; the first `flipped_to_right` correct ones were fixes."""
    fixed = 0
    for r in run.decisions:
        if r["decision_index"] != 0:
            continue
        fix = r["correct"] and fixed < flipped_to_right
        fixed += fix
        r["self_eval"] = {"first_action": "stand" if fix else r["action_taken"], "first_valid": True,
                          "first_correct": False if fix else r["correct"], "second_action": r["action_taken"],
                          "second_valid": True, "final_action": r["action_taken"], "flipped": bool(fix)}
    return run


SCEN_BASE = {f"s{i}": i % 2 == 0 for i in range(12)}            # 6 right
SCEN_STRAT = {f"s{i}": i % 2 == 0 or i < 7 for i in range(12)}  # fixes s1 s3 s5 -> 9 right


@pytest.fixture
def runs_dir(tmp_path):
    """7b: baseline, prob, strat, self (natural + scenario). 14b: baseline natural only. Plus noise folders."""
    root = tmp_path / "runs"
    base_flags, prob_flags = flags(a=10, b=1, c=9, d=4)
    strat_flags = [True] * 11 + [False] * 9 + [True] * 4
    for config, nat, scn in (("baseline", base_flags, SCEN_BASE), ("prob", prob_flags, SCEN_BASE),
                             ("strat", strat_flags, SCEN_STRAT), ("self", base_flags, SCEN_BASE)):
        nat_run = natural_run(nat, config=config, model=SMALL)
        scn_run = scenario_run(scn, config=config, model=SMALL)
        if config == "self":
            with_self_eval(nat_run)
            with_self_eval(scn_run)
        write_run(root / expected_folder(NATURAL, config, SMALL), nat_run)
        write_run(root / expected_folder(SCENARIO, config, SMALL), scn_run)
    write_run(root / expected_folder(NATURAL, "baseline", BIG), natural_run(base_flags, model=BIG))
    write_run(root / "hcc_cfgsmoke_prob_seed2026", natural_run(base_flags, config="prob"))  # config smoke: ignored
    write_run(root / "hcc_baseline_v2_seed2026", natural_run(base_flags))                  # other label: ignored
    (root / "hcc_baseline_v3_prob_seed2026_empty").mkdir()                                # no metadata: ignored
    return root


# --- naming and discovery -----------------------------------------------------------


@pytest.mark.parametrize("kind", [NATURAL, SCENARIO])
@pytest.mark.parametrize("config", CONFIG_ORDER)
@pytest.mark.parametrize("model", [SMALL, BIG])
def test_expected_folder_round_trips_through_the_parser(kind, config, model):
    name = expected_folder(kind, config, model)
    assert parse_folder_name(name) == {"kind": kind, "config": config, "model": model}


def test_folder_names_match_the_hcc_layout():
    assert expected_folder(NATURAL, "baseline", SMALL) == "hcc_baseline_v3_seed2026"
    assert expected_folder(SCENARIO, "prob_strat_self", BIG) == "hcc_scenarios_v3_prob_strat_self_seed2026_qwen2.5-14b"
    assert parse_folder_name("hcc_scenarios_v3_prob_strat_seed2026")["config"] == "prob_strat"
    assert parse_folder_name("hcc_cfgsmoke_prob_seed2026") is None
    assert parse_folder_name("hcc_baseline_v2_seed2026") is None
    assert parse_folder_name("hcc_baseline_v2_seed2026", label="v2")["model"] == SMALL
    assert model_label(BIG) == "Qwen2.5-14B"


def test_discovery_finds_only_this_labels_full_runs(runs_dir):
    names = [p.name for p in discover_run_dirs(runs_dir)]
    assert len(names) == 9
    assert all(name.startswith(("hcc_baseline_v3", "hcc_scenarios_v3")) for name in names)
    assert discover_run_dirs(runs_dir / "nope") == []


def test_metadata_wins_over_the_folder_name(tmp_path):
    path = write_run(tmp_path / expected_folder(NATURAL, "prob", SMALL), natural_run([True], config="strat"))
    report = build_report([path], expected_models=[])
    assert report["runs"][0]["config"] == "strat"
    assert any("folder name says config 'prob'" in note for note in report["notes"])


def test_unknown_configs_and_unreadable_folders_are_noted_not_fatal(tmp_path):
    odd = write_run(tmp_path / "odd", natural_run([True], config="mystery"))
    report = build_report([odd, tmp_path / "does_not_exist"], expected_models=[])
    assert report["runs"] == []
    assert any("unknown harness config 'mystery'" in note for note in report["notes"])
    assert any("could not be loaded" in note for note in report["notes"])


# --- numbers ------------------------------------------------------------------------


def test_numbers_match_paired_py_with_holm_per_family(runs_dir):
    report = build_report(discover_run_dirs(runs_dir))
    load = lambda config, kind, model=SMALL: _load(runs_dir / expected_folder(kind, config, model))  # noqa: E731
    for kind in (NATURAL, SCENARIO):
        expected = {c: compare_to_baseline(load("baseline", kind), load(c, kind)) for c in ("prob", "strat", "self")}
        adjusted = dict(zip(expected, holm_adjust([e.p_value for e in expected.values()])))
        for config, want in expected.items():
            got = report["results"][SMALL][config][kind]["comparison"]
            assert (got["a"], got["b"], got["c"], got["d"]) == (want.a, want.b, want.c, want.d)
            assert got["p_raw"] == pytest.approx(want.p_value)
            assert got["p_holm"] == pytest.approx(adjusted[config])
            assert got["difference"] == pytest.approx(want.difference)
            assert got["difference_ci"] == pytest.approx([want.ci_low, want.ci_high])
        assert report["method"]["family_sizes"][kind] == 3
    nat = report["results"][SMALL]["prob"][NATURAL]
    assert (nat["comparison"]["b"], nat["comparison"]["c"]) == (1, 9)
    assert nat["accuracy"]["k"] == 19 and nat["accuracy"]["n"] == 24


def _load(path):
    from analysis.loading import load_run
    return load_run(path)


def test_missing_runs_are_listed_with_their_expected_folders(runs_dir):
    report = build_report(discover_run_dirs(runs_dir))
    assert report["models"] == [SMALL, BIG]
    missing = {(m["model"], m["config"], m["kind"]) for m in report["missing"]}
    assert (SMALL, "prob_strat", NATURAL) in missing
    assert (BIG, "baseline", NATURAL) not in missing
    assert (BIG, "baseline", SCENARIO) in missing
    assert len(missing) == 4 + 11  # 7b lacks prob_strat and prob_strat_self; 14b has only one run
    entry = next(m for m in report["missing"] if m["model"] == BIG and m["config"] == "strat" and m["kind"] == SCENARIO)
    assert entry["expected_folder"] == "hcc_scenarios_v3_strat_seed2026_qwen2.5-14b"
    assert report["results"][BIG]["prob"][NATURAL] is None


def test_best_config_and_heatmap_categories(runs_dir):
    report = build_report(discover_run_dirs(runs_dir))
    assert report["best_config"][SMALL]["config"] == "strat"
    grid = report["heatmaps"][SMALL]
    assert grid["counts"] == {FIXED: 3, BROKE: 0, BOTH_RIGHT: 6, "both_wrong": 3}
    assert {cell["category"] for cell in grid["cells"]} <= {FIXED, BROKE, BOTH_RIGHT, "both_wrong"}
    assert BIG not in report["heatmaps"]


def test_self_eval_flips_are_counted(runs_dir):
    report = build_report(discover_run_dirs(runs_dir))
    flips = report["results"][SMALL]["self"][NATURAL]["flips"]
    assert (flips["fixes"], flips["breaks"]) == (1, 0)
    assert report["results"][SMALL]["prob"][NATURAL]["flips"] is None


# --- tables -------------------------------------------------------------------------


def test_latex_escape_and_numbers():
    assert latex_escape("a_b & 50% #1 {x} ~ ^ \\") == (
        "a\\_b \\& 50\\% \\#1 \\{x\\} \\textasciitilde{} \\textasciicircum{} \\textbackslash{}")
    assert latex_num("-5.6 [-9.0, -1.2]") == "$-$5.6 [$-$9.0, $-$1.2]"
    assert latex_num("<0.001") == "$<$0.001"


def test_latex_main_table_structure(runs_dir):
    report = build_report(discover_run_dirs(runs_dir))
    tex = latex_main_table(report, SMALL)
    for piece in ("\\begin{table*}", "\\toprule", "\\midrule", "\\bottomrule", "\\cmidrule(lr){2-5}",
                  "\\label{tab:ablation-qwen2-5-7b}", "\\textit{missing}", "Qwen2.5-7B"):
        assert piece in tex
    assert tex.count("\\begin{tabular}") == tex.count("\\end{tabular}") == 1
    prob = report["results"][SMALL]["prob"][NATURAL]["comparison"]
    assert prob["p_raw"] < 0.05 < prob["p_holm"]  # b=1, c=9 does not survive Holm over 3 tests
    assert "\\textbf{" not in tex
    prob["p_holm"] = 0.01
    assert "\\textbf{" in latex_main_table(report, SMALL)
    body = tex.split("\\midrule", 1)[1].split("\\bottomrule")[0]
    assert "_" not in body.replace("\\_", "")  # nothing unescaped in the cells
    assert not re.search(r"(?<![$\w.-])-\d", body)  # minus signs typeset as $-$
    assert "$-$" in body  # prob natural has a negative EV-loss change or CI bound
    md = markdown_main_table(report, SMALL)
    assert md.count("\n") >= len(CONFIG_ORDER) + 1 and "| Prob |" in md


def test_coverage_and_flips_tables_render(runs_dir):
    report = build_report(discover_run_dirs(runs_dir), classifier=lambda row: row["hand_number"] % 2 == 0)
    cov = latex_coverage_table(report)
    assert "\\label{tab:ablation-coverage}" in cov and "\\bottomrule" in cov
    assert report["results"][SMALL]["baseline"][NATURAL]["coverage"]["covered"]["n"] == 12
    flips = latex_flips_table(report)
    assert "\\label{tab:ablation-flips}" in flips and "Self" in flips


# --- charts and CLI -----------------------------------------------------------------


def test_charts_are_written_as_png_and_pdf(runs_dir, tmp_path):
    from analysis.ablation_charts import write_charts
    report = build_report(discover_run_dirs(runs_dir), classifier=lambda row: row["hand_number"] % 2 == 0)
    charts = write_charts(report, tmp_path / "out")
    files = [f for paths in charts.values() for f in paths]
    names = {Path(f).name for f in files}
    for stem in ("accuracy_by_config", "coverage_by_config", "self_eval_flips", "scenario_heatmap_qwen2.5-7b"):
        assert {f"{stem}.png", f"{stem}.pdf"} <= names
    for f in files:
        data = (tmp_path / "out" / f).read_bytes()
        assert data[:4] in (b"\x89PNG", b"%PDF") and len(data) > 1000


def test_cli_end_to_end_with_missing_runs(runs_dir, tmp_path, capsys):
    out = tmp_path / "results"
    code = load_script().main(["--runs-dir", str(runs_dir), "--out", str(out)])
    assert code == 0
    for rel in ("summary.md", "report.json", "tables/ablation_qwen2.5-7b.tex", "tables/ablation_qwen2.5-14b.md",
                "tables/coverage.tex", "tables/self_eval_flips.md", "charts/accuracy_by_config.pdf"):
        assert (out / rel).exists(), rel
    data = json.loads((out / "report.json").read_text())
    assert data["charts"] and len(data["missing"]) == 15
    summary = (out / "summary.md").read_text()
    assert "hcc_scenarios_v3_strat_seed2026_qwen2.5-14b" in summary
    assert "missing: qwen2.5:14b" in capsys.readouterr().out


def test_cli_explicit_dirs_and_no_runs(runs_dir, tmp_path):
    script = load_script()
    out = tmp_path / "explicit"
    dirs = [str(runs_dir / expected_folder(k, c, SMALL)) for c in ("baseline", "prob") for k in (NATURAL, SCENARIO)]
    assert script.main(dirs + ["--models", "--no-charts", "--out", str(out)]) == 0
    data = json.loads((out / "report.json").read_text())
    assert data["models"] == [SMALL] and data["charts"] == {}
    assert script.main(["--runs-dir", str(tmp_path / "empty"), "--out", str(tmp_path / "x")]) == 1
