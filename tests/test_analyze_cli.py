"""End-to-end test of scripts/analyze.py on tiny hand-made runs (not the real runs)."""

import importlib.util
import json
from pathlib import Path

from test_analysis_metrics import METADATA, decision, hand, write_run

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "analyze.py"


def load_script():
    spec = importlib.util.spec_from_file_location("analyze_script", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_run(path, metadata=METADATA):
    rows = [
        decision(hand_number=1, total=12, upcard="4", taken="double", optimal="stand"),
        decision(hand_number=2, cards=("8", "8"), total=16, pair=True, taken="split", optimal="split"),
        decision(hand_number=3, cards=("A", "6"), total=17, soft=True, upcard="5", taken="double", optimal="double"),
        decision(hand_number=3, invalid=True, reason="no_marker", optimal="hit"),
    ]
    write_run(path, rows, [hand(1, -2), hand(2, 2), hand(3, 1.5), hand(4, 1.5, num_decisions=0)], metadata)


CHARTS = ["accuracy_by_hand_type.png", "confusion_matrix.png", "accuracy_heatmap.png", "action_frequency.png"]


def test_single_run_writes_results_and_four_charts(tmp_path):
    make_run(tmp_path / "run_a")
    out = tmp_path / "out"
    load_script().main([str(tmp_path / "run_a"), "--out", str(out)])
    for name in CHARTS + ["results.md"]:
        assert (out / name).exists(), name
    text = (out / "results.md").read_text()
    assert "50.0% (2/4" in text  # accuracy, invalid counted as incorrect
    assert "doubled hard 12 vs 4 (optimal: stand) ×1" in text
    assert "no_marker" in text
    assert "small sample" in text


def test_several_runs_also_write_a_comparison(tmp_path):
    make_run(tmp_path / "run_a")
    make_run(tmp_path / "run_b", {**METADATA, "run_id": "r2", "prompt_version": "baseline-v3"})
    out = tmp_path / "cmp"
    load_script().main([str(tmp_path / "run_a"), str(tmp_path / "run_b"), "--out", str(out)])
    assert (out / "run_a" / "results.md").exists()
    assert (out / "run_b" / "accuracy_heatmap.png").exists()
    assert (out / "comparison_accuracy.png").exists()
    table = (out / "comparison.md").read_text()
    assert "baseline-v3" in table and "`r2`" in table
    assert len((out / "comparison.csv").read_text().strip().splitlines()) == 3  # header + 2 runs


def test_results_and_comparison_include_ev_loss(tmp_path):
    make_run(tmp_path / "run_a")
    make_run(tmp_path / "run_b", {**METADATA, "run_id": "r2"})
    out = tmp_path / "cmp"
    load_script().main([str(tmp_path / "run_a"), str(tmp_path / "run_b"), "--out", str(out)])
    text = (out / "run_a" / "results.md").read_text()
    assert "## EV loss" in text
    assert "Costliest mistakes" in text
    assert "| 1 | doubled hard 12 vs 4 (optimal: stand) | 1 |" in text
    assert (out / "run_a" / "ev_loss_heatmap.png").exists()
    header = (out / "comparison.csv").read_text().splitlines()[0]
    for column in ["ev_loss_total", "ev_loss_per_decision", "ev_loss_per_hand", "ev_loss_per_mistake"]:
        assert column in header
    assert "EV loss/decision" in (out / "comparison.md").read_text()
