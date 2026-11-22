"""Analyze one or more run directories into results.md, charts and a comparison table.

Usage:
    .venv/bin/python scripts/analyze.py runs/<dir> [runs/<dir2> ...] [--out results/<name>]

One run:      writes results.md + 5 charts to --out (default results/<run dir name>/).
Several runs: writes each run's full report to <out>/<run dir name>/, plus
              comparison.md, comparison.csv and comparison_accuracy.png in <out>
              (default results/comparison_<dir1>__<dir2>.../).
"""

import argparse
import sys
from pathlib import Path

# Let `python scripts/analyze.py` import the analysis package from the repo root.
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from analysis.charts import comparison_accuracy_chart, write_run_charts  # noqa: E402
from analysis.loading import load_run  # noqa: E402
from analysis.metrics import RunSummary, summarize_run  # noqa: E402
from analysis.report import write_comparison, write_results  # noqa: E402


def analyze_one(run_dir: Path, out_dir: Path) -> RunSummary:
    """Full report for one run: charts first, then results.md listing them."""
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = summarize_run(load_run(run_dir))
    charts = write_run_charts(summary, out_dir)
    write_results(summary, out_dir, charts)
    print(f"{run_dir.name}: {summary.accuracy.k}/{summary.accuracy.n} correct "
          f"({summary.accuracy.rate:.1%}), {summary.invalid.k} invalid, "
          f"EV loss {summary.ev_loss.mean_per_decision:.4f}/decision -> {out_dir}")
    return summary


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("runs", nargs="+", type=Path, help="run directories (each with decisions.jsonl, hands.jsonl, metadata.json)")
    parser.add_argument("--out", type=Path, help="output directory")
    args = parser.parse_args(argv)

    run_dirs = [Path(r) for r in args.runs]
    names = [r.name for r in run_dirs]
    if len(set(names)) != len(names):
        parser.error("run directories must have different names (they become output subfolders)")

    if len(run_dirs) == 1:
        analyze_one(run_dirs[0], args.out or REPO_ROOT / "results" / names[0])
        return

    out = args.out or REPO_ROOT / "results" / ("comparison_" + "__".join(names))
    summaries = [analyze_one(run_dir, out / run_dir.name) for run_dir in run_dirs]
    write_comparison(summaries, out)
    comparison_accuracy_chart(summaries, out / "comparison_accuracy.png")
    print(f"comparison -> {out}")


if __name__ == "__main__":
    main()
