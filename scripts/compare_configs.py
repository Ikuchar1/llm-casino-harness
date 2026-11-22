"""Compare harness configurations with the same model's baseline on paired first decisions.

Usage:
    python scripts/compare_configs.py --baseline runs/<base> [--baseline runs/<base2> ...] \\
        runs/<config1> [runs/<config2> ...] [--out results/<name>] [--covered]

Each config run is paired with the --baseline run of the same kind (natural or
scenario, detected from the logs) and the same model. Give one baseline per
(kind, model) you compare against. Natural runs pair on hand number (first
decision of each hand only), scenario runs on scenario_id; see analysis/paired.py.

Per comparison: paired n, both accuracies, the difference (config - baseline)
with a Newcombe hybrid-score 95% CI, discordant counts b/c, the exact McNemar
p-value and its Holm-adjusted value, the EV-loss change and invalid counts.

Holm correction is applied across all comparisons of one invocation, separately
for each family: natural comparisons form one family and scenario comparisons
another. They answer different questions (natural frequency-weighted accuracy vs
every chart cell once) and are never pooled, so each is its own set of tests.

Also printed, descriptive only: accuracy of later decisions (unpaired),
self-evaluation flip stats for runs whose rows carry `self_eval`, and with
--covered the covered/uncovered accuracy of first decisions.

--out writes comparison.json and comparison.md there.
"""

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any, Callable, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from analysis.loading import Run, load_run  # noqa: E402
from analysis.paired import (  # noqa: E402
    NATURAL,
    SCENARIO,
    Comparison,
    PairingError,
    accuracy_by_coverage,
    compare_to_baseline,
    config_name,
    first_decisions,
    flip_stats,
    holm_adjust,
    later_decisions,
    run_kind,
)
from analysis.stats import Proportion  # noqa: E402

FAMILIES = (NATURAL, SCENARIO)
CI_METHOD = "Newcombe hybrid score (1998, method 10)"

Classifier = Callable[[dict[str, Any]], bool]


def load_covered_classifier() -> Optional[Classifier]:
    """row -> covered? from agent/strategy_info.py, or None if that module isn't available.

    Uses strategy_info.cell_for_decision (row -> chart cell) and is_covered(cell).
    build_report takes any row -> bool classifier, so tests and other labellings
    can be injected instead.
    """
    try:
        from agent.strategy_info import cell_for_decision, is_covered
    except ImportError:
        return None
    return lambda row: bool(is_covered(cell_for_decision(row)))


# --- building the report ------------------------------------------------------------


def _unique_names(runs: list[Run]) -> dict[int, str]:
    """Display name per run: the metadata config name, or the folder name when names collide."""
    names = [config_name(run) for run in runs]
    return {id(run): (name if names.count(name) == 1 else run.name) for run, name in zip(runs, names)}


def _proportion(p: Proportion) -> dict[str, Any]:
    return {"k": p.k, "n": p.n, "rate": _nan_to_none(p.rate),
            "ci_low": _nan_to_none(p.low), "ci_high": _nan_to_none(p.high)}


def _nan_to_none(value: float) -> Optional[float]:
    return None if value is None or (isinstance(value, float) and math.isnan(value)) else value


def _comparison_dict(c: Comparison, name: str, baseline_dir: str) -> dict[str, Any]:
    return {
        "config": name,
        "baseline": c.baseline_name,
        "baseline_dir": baseline_dir,
        "model": c.model,
        "kind": c.kind,
        "n": c.n,
        "a": c.a, "b": c.b, "c": c.c, "d": c.d,
        "dropped": c.dropped,
        "no_decision": c.no_decision,
        "baseline_accuracy": _proportion(c.baseline_accuracy),
        "config_accuracy": _proportion(c.config_accuracy),
        "difference": _nan_to_none(c.difference),
        "difference_ci": [_nan_to_none(c.ci_low), _nan_to_none(c.ci_high)],
        "p_raw": c.p_value,
        "p_holm": c.p_holm,
        "baseline_invalid": c.baseline_invalid,
        "config_invalid": c.config_invalid,
        "baseline_ev_loss": _nan_to_none(c.baseline_ev_loss),
        "config_ev_loss": _nan_to_none(c.config_ev_loss),
        "ev_loss_change": _nan_to_none(c.ev_loss_change),
        "ev_loss_change_ci": [_nan_to_none(c.ev_loss_diff.low), _nan_to_none(c.ev_loss_diff.high)],
    }


def _pick_baseline(config: Run, baselines: list[Run]) -> Run:
    kind, model = run_kind(config), config.metadata.get("model")
    matches = [b for b in baselines if run_kind(b) == kind and b.metadata.get("model") == model]
    if not matches:
        raise PairingError(f"no {kind} baseline for model {model!r} (needed by {config.name}); pass one with --baseline")
    if len(matches) > 1:
        raise PairingError(f"several {kind} baselines for model {model!r}: {[b.name for b in matches]}")
    return matches[0]


def build_report(baseline_dirs: list[Path | str], config_dirs: list[Path | str],
                 classifier: Optional[Classifier] = None) -> dict[str, Any]:
    """Every number the tables show, as plain JSON-ready data."""
    baselines = [load_run(d) for d in baseline_dirs]
    configs = [load_run(d) for d in config_dirs]
    names = _unique_names(baselines + configs)

    families: dict[str, list[dict[str, Any]]] = {kind: [] for kind in FAMILIES}
    comparisons: dict[str, list[Comparison]] = {kind: [] for kind in FAMILIES}
    for config in configs:
        baseline = _pick_baseline(config, baselines)
        comparison = compare_to_baseline(baseline, config)
        comparison.baseline_name = names[id(baseline)]
        comparisons[comparison.kind].append(comparison)
        families[comparison.kind].append(_comparison_dict(comparison, names[id(config)], baseline.name))

    for kind in FAMILIES:  # Holm within each family
        for entry, adjusted in zip(families[kind], holm_adjust([c.p_value for c in comparisons[kind]])):
            entry["p_holm"] = adjusted

    seen, every_run = set(), []  # each run once in the descriptive tables, even if passed twice
    for path, run in zip(list(baseline_dirs) + list(config_dirs), baselines + configs):
        if Path(path).resolve() not in seen:
            seen.add(Path(path).resolve())
            every_run.append(run)
    later = [{"config": names[id(r)], "model": r.metadata.get("model"), "kind": run_kind(r),
              **_proportion(later_decisions(r))} for r in every_run]

    flips = {}
    for run in every_run:
        stats = flip_stats(list(first_decisions(run).values()))
        if stats.n:
            flips[names[id(run)]] = {
                "kind": run_kind(run), "n": stats.n, "flips": stats.flips, "fixes": stats.fixes,
                "breaks": stats.breaks, "neutral": stats.neutral, "second_invalid": stats.second_invalid,
                "first_accuracy": _proportion(stats.first_accuracy),
                "final_accuracy": _proportion(stats.final_accuracy),
            }

    coverage = None
    if classifier is not None:
        coverage = []
        for run in every_run:
            covered, uncovered = accuracy_by_coverage(list(first_decisions(run).values()), classifier)
            coverage.append({"config": names[id(run)], "model": run.metadata.get("model"), "kind": run_kind(run),
                             "covered": _proportion(covered), "uncovered": _proportion(uncovered)})

    return {
        "ci_method": CI_METHOD,
        "test": "exact McNemar (two-sided binomial on b + c)",
        "correction": "Holm-Bonferroni, separately per family (natural, scenario)",
        "families": families,
        "later_decisions": later,
        "flips": flips,
        "coverage": coverage,
    }


# --- markdown -----------------------------------------------------------------------


def _pct(value: Optional[float]) -> str:
    return "n/a" if value is None else f"{100 * value:.1f}%"


def _acc(p: dict[str, Any]) -> str:
    return f"{_pct(p['rate'])} ({p['k']}/{p['n']})"


def _signed(value: Optional[float], digits: int = 4) -> str:
    return "n/a" if value is None else f"{value:+.{digits}f}"


def _pp(value: Optional[float]) -> str:
    return "n/a" if value is None else f"{100 * value:+.1f}"


def _p(value: Optional[float]) -> str:
    return "n/a" if value is None else (f"{value:.2e}" if value < 1e-3 else f"{value:.4f}")


def render_markdown(report: dict[str, Any]) -> str:
    lines = ["# Config vs baseline (paired first decisions)", "",
             f"Test: {report['test']}. Difference CI: {report['ci_method']}, 95%. "
             f"Correction: {report['correction']}. b = baseline right & config wrong, "
             "c = baseline wrong & config right. EV loss is the mean per paired first decision.", ""]
    for kind in FAMILIES:
        entries = report["families"][kind]
        if not entries:
            continue
        lines += [f"## {kind.capitalize()} family", "",
                  "| config | model | n pairs | baseline acc | config acc | diff [95% CI] | b | c | p raw | p Holm "
                  "| EV loss change [95% CI] | invalid base/config | dropped |",
                  "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for e in entries:
            low, high = e["difference_ci"]
            ev_low, ev_high = e["ev_loss_change_ci"]
            diff = "n/a" if e["difference"] is None else (
                f"{_pp(e['difference'])} pp [{_pp(low)}, {_pp(high)}]")
            lines.append(
                f"| {e['config']} | {e['model']} | {e['n']} | {_acc(e['baseline_accuracy'])} | "
                f"{_acc(e['config_accuracy'])} | {diff} | {e['b']} | {e['c']} | {_p(e['p_raw'])} | "
                f"{_p(e['p_holm'])} | {_signed(e['ev_loss_change'])} [{_signed(ev_low)}, {_signed(ev_high)}] | "
                f"{e['baseline_invalid']}/{e['config_invalid']} | {e['dropped']} |")
        lines.append("")

    lines += ["## Later decisions (descriptive, not tested)", "",
              "| config | model | kind | accuracy |", "|---|---|---|---|"]
    lines += [f"| {e['config']} | {e['model']} | {e['kind']} | {_acc(e)} |" for e in report["later_decisions"]]
    lines.append("")

    if report["flips"]:
        lines += ["## Self-evaluation flips (first decisions)", "",
                  "| config | kind | n | first acc | final acc | flips | fixes | breaks | wrong->wrong | "
                  "second reply invalid |", "|---|---|---|---|---|---|---|---|---|---|"]
        for name, f in report["flips"].items():
            lines.append(f"| {name} | {f['kind']} | {f['n']} | {_acc(f['first_accuracy'])} | "
                         f"{_acc(f['final_accuracy'])} | {f['flips']} | {f['fixes']} | {f['breaks']} | "
                         f"{f['neutral']} | {f['second_invalid']} |")
        lines.append("")

    if report["coverage"] is not None:
        lines += ["## Covered vs uncovered cells (first decisions, descriptive)", "",
                  "| config | model | kind | covered acc | uncovered acc |", "|---|---|---|---|---|"]
        lines += [f"| {e['config']} | {e['model']} | {e['kind']} | {_acc(e['covered'])} | {_acc(e['uncovered'])} |"
                  for e in report["coverage"]]
        lines.append("")
    return "\n".join(lines)


# --- CLI ----------------------------------------------------------------------------


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--baseline", action="append", required=True, type=Path,
                        help="baseline run directory; repeat for other kinds or models")
    parser.add_argument("configs", nargs="+", type=Path, help="config run directories")
    parser.add_argument("--out", type=Path, help="write comparison.json and comparison.md here")
    parser.add_argument("--covered", action="store_true",
                        help="add covered/uncovered accuracy (needs agent/strategy_info.py)")
    args = parser.parse_args(argv)

    classifier = None
    if args.covered:
        classifier = load_covered_classifier()
        if classifier is None:
            print("--covered: agent/strategy_info.py (is_covered) not available yet; skipping the breakdown",
                  file=sys.stderr)

    try:
        report = build_report(args.baseline, args.configs, classifier)
    except PairingError as error:
        parser.error(str(error))

    markdown = render_markdown(report)
    print(markdown)
    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "comparison.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        (args.out / "comparison.md").write_text(markdown + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
