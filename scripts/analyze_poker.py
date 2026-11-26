"""Analyze poker match run directories: habit metrics, trend, bb/100, profile, fallbacks.

Usage (from the repo root):
    .venv/bin/python scripts/analyze_poker.py runs/<match> [runs/<match2> ...] [--out results/poker]
    .venv/bin/python scripts/analyze_poker.py --compare runs/<plain> runs/<memory> [--out results/poker]
    options: --first-hands 100 --last-hands 500 (the trend windows; both shrink for a short match)

Prints a compact table per run and writes summary.json and summary.csv to --out
(default results/poker/). --compare A B also prints the paired comparison B - A on the
same seed pairs and writes comparison.json; it exits 2 if the runs were dealt
different seed lists or played different bots. Metric definitions: analysis/poker_metrics.py.
"""

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any, Optional

# Let `python scripts/analyze_poker.py` import the project packages from the repo root.
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from analysis import poker_metrics as pm  # noqa: E402
from analysis.loading import load_run  # noqa: E402
from analysis.paired import PairingError  # noqa: E402

DEFAULT_OUT = REPO_ROOT / "results" / "poker"


def _pct(value: Optional[float]) -> str:
    return "n/a" if value is None else f"{value:.1%}"


def _rate(rate: dict[str, Any]) -> str:
    return f"{_pct(rate['rate'])} [{_pct(rate['low'])}, {_pct(rate['high'])}] ({rate['k']}/{rate['n']})"


def _diff(diff: dict[str, Any]) -> str:
    if diff["difference"] is None:
        return "n/a"
    return f"{diff['difference']:+.1%} [{diff['low']:+.1%}, {diff['high']:+.1%}]"


def _num(value: Optional[float], spec: str = ".1f") -> str:
    return "n/a" if value is None else format(value, spec)


def print_run(summary: dict[str, Any]) -> None:
    trend = summary["trend"]
    bb = summary["bb_per_100"]
    profile = summary["profile"]
    print(f"{summary['run']}: {summary['model']} ({summary['setup']}) vs {summary['bot']}, "
          f"{summary['hands']} hands, {summary['pairs']} pairs")
    print(f"  {'habit':<18} {'target':<6} {'rate [95% CI] (k/n)':<34} "
          f"trend last {trend['last_hands']} - first {trend['first_hands']} hands")
    for name, habit in summary["habits"].items():
        print(f"  {name:<18} {habit['target'] or '-':<6} {_rate(habit):<34} {_diff(trend['habits'][name])}")
    print(f"  bb/100 {_num(bb['mean'])} [{_num(bb['low'])}, {_num(bb['high'])}] over {bb['pairs']} seed pairs"
          + (f" ({bb['incomplete_pairs']} incomplete)" if bb["incomplete_pairs"] else ""))
    print(f"  VPIP {_pct(profile['vpip']['rate'])}  PFR {_pct(profile['pfr']['rate'])}  "
          f"AF {_num(profile['af'], '.2f')} ({profile['af_bets_raises']}/{profile['af_calls']})  WTSD {_pct(profile['wtsd']['rate'])}")
    statuses = ", ".join(f"{status} {count}" for status, count in summary["parse_status"].items()) or "none"
    print(f"  fallback {_rate(summary['fallback'])}; parse status: {statuses}; "
          f"prompt tokens/decision {_num(summary['prompt_tokens_mean'], '.0f')}")


def print_comparison(summary: dict[str, Any], a: dict[str, Any], b: dict[str, Any]) -> None:
    diff = summary["bb_per_100_difference"]
    print(f"{b['setup']} - {a['setup']} ({summary['b']} - {summary['a']}), vs {a['bot']}, "
          f"{summary['pairs']} seed pairs" + (f" ({summary['unmatched_pairs']} unmatched)" if summary["unmatched_pairs"] else ""))
    print(f"  bb/100 difference {_num(diff['mean'])} [{_num(diff['low'])}, {_num(diff['high'])}] (mean ± 1.96 SE); "
          f"paired bootstrap [{_num(summary['bootstrap_low'])}, {_num(summary['bootstrap_high'])}], "
          f"p = {_num(summary['bootstrap_p'], '.3f')}")
    for name, habit in summary["habits"].items():
        print(f"  {name:<18} {_pct(habit['before']['rate'])} -> {_pct(habit['after']['rate'])}  {_diff(habit)}")


def csv_row(summary: dict[str, Any]) -> dict[str, Any]:
    """One flat row per run for summary.csv."""
    row = {key: summary[key] for key in ("run", "run_id", "model", "setup", "bot", "hands", "pairs")}
    for name, habit in summary["habits"].items():
        row.update({f"{name}_{key}": habit[key] for key in ("rate", "low", "high", "n")})
        trend = summary["trend"]["habits"][name]
        row.update({f"{name}_trend_{key}": trend[key] for key in ("difference", "low", "high")})
    bb = summary["bb_per_100"]
    row.update({"bb_per_100": bb["mean"], "bb_per_100_low": bb["low"], "bb_per_100_high": bb["high"]})
    profile = summary["profile"]
    row.update({"vpip": profile["vpip"]["rate"], "pfr": profile["pfr"]["rate"], "af": profile["af"],
                "wtsd": profile["wtsd"]["rate"], "fallback_rate": summary["fallback"]["rate"],
                "prompt_tokens_mean": summary["prompt_tokens_mean"]})
    return row


def write_csv(summaries: list[dict[str, Any]], path: Path) -> None:
    rows = [csv_row(summary) for summary in summaries]
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("runs", nargs="*", type=Path, help="poker run directories")
    parser.add_argument("--compare", nargs=2, type=Path, metavar=("A", "B"),
                        help="paired comparison B - A (e.g. plain then memory) on the same seeds")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="output directory (default results/poker)")
    parser.add_argument("--first-hands", type=int, default=pm.FIRST_HANDS, help="early trend window, in hands")
    parser.add_argument("--last-hands", type=int, default=pm.LAST_HANDS, help="late trend window, in hands")
    args = parser.parse_args(argv)

    run_dirs = list(dict.fromkeys([*args.runs, *(args.compare or [])]))
    if not run_dirs:
        parser.error("give at least one run directory, or --compare A B")
    runs = {run_dir: load_run(run_dir) for run_dir in run_dirs}
    summaries = {run_dir: pm.summarize_run(run, args.first_hands, args.last_hands) for run_dir, run in runs.items()}

    comparison = None
    if args.compare:
        a, b = args.compare
        try:
            comparison = pm.summarize_comparison(pm.compare_runs(runs[a], runs[b]))
        except PairingError as error:
            print(f"error: {error}", file=sys.stderr)
            return 2

    for summary in summaries.values():
        print_run(summary)
        print()
    if comparison is not None:
        print_comparison(comparison, summaries[args.compare[0]], summaries[args.compare[1]])

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "summary.json").write_text(json.dumps({"runs": list(summaries.values())}, indent=2) + "\n")
    write_csv(list(summaries.values()), args.out / "summary.csv")
    if comparison is not None:
        (args.out / "comparison.json").write_text(json.dumps(comparison, indent=2) + "\n")
    print(f"-> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
