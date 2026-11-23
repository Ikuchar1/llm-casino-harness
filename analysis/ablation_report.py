"""Final blackjack ablation results: every config vs the same model's baseline, for every model.

Inputs are run folders (see docs/ablation-plan.md). Each one is identified as
(model, harness config, kind), where kind is "natural" or "scenario". Identity comes
from the run's metadata (`model`, `harness_config`, run type in the logs); the HCC
folder name (hcc/full_run.sbatch) is only a fallback for runs that predate a field:

    runs/hcc_{baseline|scenarios}_<label>[_<config>]_seed2026[_<model>]

`hcc_baseline_*` is the natural 1000-hand run (named after the script, not the
config), `_<config>` is left out for the baseline config, and `_<model>` is left out
for qwen2.5:7b (":" written as "-").

All statistics come from analysis/paired.py:
- accuracy per run is over first decisions (natural: decision_index 0 of each hand;
  scenario: the graded cell), the same decisions the paired test uses;
- difference vs baseline: Newcombe paired 95% CI; exact McNemar p-value;
- Holm correction within the natural family and within the scenario family, each
  family pooling every config of every model (as scripts/compare_configs.py does);
- EV-loss change per paired first decision; covered/uncovered accuracy (strategy
  information classifier); self-evaluation flips.

build_report returns plain JSON-ready data; the Markdown and LaTeX renderers and
analysis/ablation_charts.py only format it.
"""

import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from analysis.loading import Run, load_run
from analysis.metrics import accuracy, chosen_action, graded_rows, heatmap_row_label, heatmap_row_labels, upcard_label
from analysis.paired import (
    NATURAL,
    SCENARIO,
    PairingError,
    accuracy_by_coverage,
    compare_to_baseline,
    first_decisions,
    flip_stats,
    holm_adjust,
    later_decisions,
    pair_runs,
    run_kind,
)
from analysis.stats import Proportion

CONFIG_ORDER = ["baseline", "prob", "prob_strat", "prob_strat_self", "strat", "self"]
CONFIG_LABELS = {
    "baseline": "Baseline",
    "prob": "Prob",
    "prob_strat": "Prob + Strat",
    "prob_strat_self": "Prob + Strat + Self",
    "strat": "Strat",
    "self": "Self",
}
SELF_CONFIGS = [c for c in CONFIG_ORDER if c.endswith("self")]
KINDS = (NATURAL, SCENARIO)
KIND_LABELS = {NATURAL: "Natural run", SCENARIO: "Scenario set"}
FOLDER_PREFIX = {NATURAL: "hcc_baseline", SCENARIO: "hcc_scenarios"}
DEFAULT_MODEL = "qwen2.5:7b"  # the model whose HCC folders carry no _<model> suffix
DEFAULT_LABEL = "v3"
DEFAULT_SEED = 2026
EXPECTED_MODELS = ["qwen2.5:7b", "qwen2.5:14b"]

# Heatmap categories: baseline vs config on the same scenario cell.
FIXED, BROKE, BOTH_RIGHT, BOTH_WRONG = "fixed", "broke", "both_right", "both_wrong"

Classifier = Callable[[dict[str, Any]], bool]


# --- naming and identity ------------------------------------------------------------


def model_slug(model: str) -> str:
    """Folder suffix for a model tag: "qwen2.5:14b" -> "qwen2.5-14b"."""
    return model.replace(":", "-")


def model_label(model: str) -> str:
    """Display name: "qwen2.5:14b" -> "Qwen2.5-14B"."""
    name, _, size = model.partition(":")
    name = name[:1].upper() + name[1:]
    return f"{name}-{size.upper()}" if size else name


def model_size(model: str) -> float:
    """Parameter count parsed from the tag (for ordering 7b before 14b); inf if unknown."""
    match = re.search(r":(\d+(?:\.\d+)?)b\b", model.lower())
    return float(match.group(1)) if match else math.inf


def config_label(config: str) -> str:
    return CONFIG_LABELS.get(config, config)


def expected_folder(kind: str, config: str, model: str, label: str = DEFAULT_LABEL, seed: int = DEFAULT_SEED) -> str:
    """The folder hcc/full_run.sbatch writes for this run."""
    config_tag = "" if config == "baseline" else f"_{config}"
    model_tag = "" if model == DEFAULT_MODEL else f"_{model_slug(model)}"
    return f"{FOLDER_PREFIX[kind]}_{label}{config_tag}_seed{seed}{model_tag}"


def parse_folder_name(name: str, label: str = DEFAULT_LABEL, seed: int = DEFAULT_SEED) -> Optional[dict[str, str]]:
    """{"kind", "config", "model"} from an HCC full-run folder name, or None if it isn't one."""
    configs = "|".join(sorted((re.escape(c) for c in CONFIG_ORDER if c != "baseline"), key=len, reverse=True))
    pattern = (rf"^hcc_(baseline|scenarios)_{re.escape(label)}(?:_({configs}))?"
               rf"_seed{seed}(?:_(.+))?$")
    match = re.match(pattern, name)
    if not match:
        return None
    prefix, config, slug = match.groups()
    model = DEFAULT_MODEL
    if slug:
        head, dash, size = slug.rpartition("-")
        model = f"{head}:{size}" if dash else slug
    return {"kind": NATURAL if prefix == "baseline" else SCENARIO, "config": config or "baseline", "model": model}


def discover_run_dirs(runs_dir: Path, label: str = DEFAULT_LABEL, seed: int = DEFAULT_SEED) -> list[Path]:
    """Every HCC full-run folder for this label under runs_dir (sorted)."""
    if not runs_dir.is_dir():
        return []
    return sorted(p for p in runs_dir.iterdir()
                  if p.is_dir() and (p / "metadata.json").exists() and parse_folder_name(p.name, label, seed))


@dataclass
class RunEntry:
    path: Path
    run: Run
    kind: str
    config: str
    model: str


def identify(run: Run, path: Path, label: str = DEFAULT_LABEL, seed: int = DEFAULT_SEED) -> tuple[Optional[RunEntry], list[str]]:
    """(entry, notes). Metadata wins over the folder name; None if the config or model is unknown."""
    notes = []
    parsed = parse_folder_name(path.name, label, seed) or {}
    kind = run_kind(run)
    meta_config = run.metadata.get("harness_config")
    if isinstance(meta_config, dict):
        meta_config = meta_config.get("name")
    config = meta_config or parsed.get("config")
    model = run.metadata.get("model") or parsed.get("model")
    for field, value in (("config", config), ("model", model), ("kind", kind)):
        if parsed and value and parsed.get(field) and parsed[field] != value:
            notes.append(f"{path.name}: folder name says {field} {parsed[field]!r} but the run logged {value!r}; "
                         "using the logged value")
    if config not in CONFIG_ORDER:
        notes.append(f"{path}: unknown harness config {config!r}; skipped")
        return None, notes
    if not model:
        notes.append(f"{path}: no model in metadata or folder name; skipped")
        return None, notes
    return RunEntry(path, run, kind, config, model), notes


def collect_runs(paths: Iterable[Path], label: str = DEFAULT_LABEL,
                 seed: int = DEFAULT_SEED) -> tuple[dict[tuple[str, str, str], RunEntry], list[str]]:
    """{(model, config, kind): entry} and notes. A later path for the same key replaces an earlier one."""
    entries: dict[tuple[str, str, str], RunEntry] = {}
    notes: list[str] = []
    for path in paths:
        path = Path(path)
        try:
            run = load_run(path)
        except (OSError, ValueError) as error:
            notes.append(f"{path}: could not be loaded ({error}); skipped")
            continue
        entry, found = identify(run, path, label, seed)
        notes += found
        if entry is None:
            continue
        key = (entry.model, entry.config, entry.kind)
        if key in entries:
            notes.append(f"{entry.model} {entry.config} {entry.kind}: {path} replaces {entries[key].path}")
        entries[key] = entry
    return entries, notes


# --- numbers --------------------------------------------------------------------------


def _clean(value: Any) -> Any:
    return None if isinstance(value, float) and math.isnan(value) else value


def proportion_dict(p: Proportion) -> dict[str, Any]:
    return {"k": p.k, "n": p.n, "rate": _clean(p.rate), "ci_low": _clean(p.low), "ci_high": _clean(p.high)}


def _run_numbers(entry: RunEntry, classifier: Optional[Classifier]) -> dict[str, Any]:
    firsts = list(first_decisions(entry.run).values())
    numbers: dict[str, Any] = {
        "run_dir": str(entry.path),
        "run_name": entry.path.name,
        "accuracy": proportion_dict(accuracy(firsts)),
        "all_decisions_accuracy": proportion_dict(accuracy(graded_rows(entry.run))),
        "later_decisions_accuracy": proportion_dict(later_decisions(entry.run)),
        "invalid": sum(1 for row in firsts if row["invalid"]),
        "comparison": None,
        "coverage": None,
        "flips": None,
    }
    if classifier is not None:
        covered, uncovered = accuracy_by_coverage(firsts, classifier)
        numbers["coverage"] = {"covered": proportion_dict(covered), "uncovered": proportion_dict(uncovered)}
    stats = flip_stats(firsts)
    if stats.n:
        numbers["flips"] = {
            "n": stats.n, "flips": stats.flips, "fixes": stats.fixes, "breaks": stats.breaks,
            "neutral": stats.neutral, "second_invalid": stats.second_invalid,
            "first_accuracy": proportion_dict(stats.first_accuracy),
            "final_accuracy": proportion_dict(stats.final_accuracy),
        }
    return numbers


def _comparison_dict(c) -> dict[str, Any]:
    return {
        "n": c.n, "a": c.a, "b": c.b, "c": c.c, "d": c.d,
        "dropped": c.dropped, "no_decision": c.no_decision,
        "baseline_accuracy": proportion_dict(c.baseline_accuracy),
        "config_accuracy": proportion_dict(c.config_accuracy),
        "difference": _clean(c.difference),
        "difference_ci": [_clean(c.ci_low), _clean(c.ci_high)],
        "p_raw": c.p_value,
        "p_holm": None,
        "baseline_invalid": c.baseline_invalid,
        "config_invalid": c.config_invalid,
        "baseline_ev_loss": _clean(c.baseline_ev_loss),
        "config_ev_loss": _clean(c.config_ev_loss),
        "ev_loss_change": _clean(c.ev_loss_change),
        "ev_loss_change_ci": [_clean(c.ev_loss_diff.low), _clean(c.ev_loss_diff.high)],
    }


def scenario_cell_grid(baseline: Run, config: Run) -> dict[str, Any]:
    """Each paired scenario cell's category (fixed / broke / both right / both wrong) and actions."""
    paired = pair_runs(baseline, config)
    cells, counts = [], {FIXED: 0, BROKE: 0, BOTH_RIGHT: 0, BOTH_WRONG: 0}
    for pair in paired.pairs:
        base_ok, conf_ok = bool(pair.baseline["correct"]), bool(pair.config["correct"])
        category = (BOTH_RIGHT if base_ok and conf_ok else BROKE if base_ok
                    else FIXED if conf_ok else BOTH_WRONG)
        counts[category] += 1
        cells.append({
            "row": heatmap_row_label(pair.baseline),
            "upcard": upcard_label(pair.baseline["dealer_upcard"]),
            "category": category,
            "baseline_action": chosen_action(pair.baseline),
            "config_action": chosen_action(pair.config),
            "optimal_action": pair.baseline["optimal_action"],
        })
    present = {cell["row"] for cell in cells}
    rows = [label for label in heatmap_row_labels([p.baseline for p in paired.pairs]) if label in present]
    return {"rows": rows, "cells": cells, "counts": counts}


def build_report(paths: Iterable[Path], label: str = DEFAULT_LABEL, seed: int = DEFAULT_SEED,
                 classifier: Optional[Classifier] = None,
                 expected_models: Optional[list[str]] = None) -> dict[str, Any]:
    """Every number the tables and charts show, as JSON-ready data."""
    entries, notes = collect_runs(paths, label, seed)
    models = sorted({model for model, _, _ in entries} | set(expected_models or []),
                    key=lambda m: (model_size(m), m))

    missing = []
    for model in models:
        for config in CONFIG_ORDER:
            for kind in KINDS:
                if (model, config, kind) not in entries:
                    missing.append({"model": model, "config": config, "kind": kind,
                                    "expected_folder": expected_folder(kind, config, model, label, seed)})

    results: dict[str, dict[str, dict[str, Any]]] = {}
    family: dict[str, list[dict[str, Any]]] = {kind: [] for kind in KINDS}
    for model in models:
        results[model] = {}
        for config in CONFIG_ORDER:
            results[model][config] = {}
            for kind in KINDS:
                entry = entries.get((model, config, kind))
                if entry is None:
                    results[model][config][kind] = None
                    continue
                numbers = _run_numbers(entry, classifier)
                baseline = entries.get((model, "baseline", kind))
                if config != "baseline" and baseline is not None:
                    try:
                        numbers["comparison"] = _comparison_dict(compare_to_baseline(baseline.run, entry.run))
                        family[kind].append(numbers["comparison"])
                    except PairingError as error:
                        notes.append(f"{model} {config} {kind}: not compared with baseline ({error})")
                elif config != "baseline":
                    notes.append(f"{model} {config} {kind}: no baseline run to compare with")
                results[model][config][kind] = numbers

    for kind in KINDS:  # Holm within each family
        for comparison, adjusted in zip(family[kind], holm_adjust([c["p_raw"] for c in family[kind]])):
            comparison["p_holm"] = adjusted

    best, heatmaps = {}, {}
    for model in models:
        candidates = [(config, results[model][config][SCENARIO]) for config in CONFIG_ORDER[1:]
                      if results[model][config][SCENARIO] and results[model][config][SCENARIO]["comparison"]]
        if not candidates:
            continue
        config, numbers = max(candidates, key=lambda item: (item[1]["accuracy"]["rate"] or 0,
                                                            -CONFIG_ORDER.index(item[0])))
        best[model] = {"config": config, "scenario_accuracy": numbers["accuracy"]}
        heatmaps[model] = {"config": config, **scenario_cell_grid(entries[(model, "baseline", SCENARIO)].run,
                                                                  entries[(model, config, SCENARIO)].run)}

    return {
        "label": label,
        "seed": seed,
        "method": {
            "accuracy": "first decisions: decision_index 0 of each natural hand; the graded cell of each scenario",
            "accuracy_ci": "Wilson score 95%",
            "difference_ci": "Newcombe hybrid score for paired proportions (1998, method 10), 95%",
            "test": "exact McNemar (two-sided binomial on the discordant pairs)",
            "correction": "Holm-Bonferroni within each family (natural, scenario), across all models and configs",
            "family_sizes": {kind: len(family[kind]) for kind in KINDS},
            "ev_loss": "mean EV loss per paired first decision, config minus baseline (units per 1-unit bet); "
                       "normal-approximation 95% CI on the per-pair differences",
            "coverage": None if classifier is None else "agent/strategy_info.py is_covered(cell_for_decision(row))",
        },
        "models": models,
        "configs": CONFIG_ORDER,
        "runs": [{"model": e.model, "config": e.config, "kind": e.kind, "path": str(e.path)}
                 for e in sorted(entries.values(), key=lambda e: (model_size(e.model), e.model,
                                                                  CONFIG_ORDER.index(e.config), e.kind))],
        "missing": missing,
        "notes": notes,
        "results": results,
        "best_config": best,
        "heatmaps": heatmaps,
    }


def default_classifier() -> Optional[Classifier]:
    """Covered-cell classifier from agent/strategy_info.py (None if it can't be imported)."""
    try:
        from agent.strategy_info import is_decision_covered
    except ImportError:
        return None
    return is_decision_covered


# --- text formatting ------------------------------------------------------------------


def fmt_pct(value: Optional[float]) -> str:
    return "n/a" if value is None else f"{100 * value:.1f}"


def fmt_pp(value: Optional[float]) -> str:
    return "n/a" if value is None else f"{100 * value:+.1f}"


def fmt_p(value: Optional[float]) -> str:
    if value is None:
        return "n/a"
    return "<0.001" if value < 0.001 else f"{value:.3f}"


def fmt_units(value: Optional[float]) -> str:
    return "n/a" if value is None else f"{value:+.3f}"


def fmt_acc_ci(p: dict[str, Any]) -> str:
    if not p or p["rate"] is None:
        return "n/a"
    return f"{fmt_pct(p['rate'])} [{fmt_pct(p['ci_low'])}, {fmt_pct(p['ci_high'])}]"


def fmt_diff_ci(c: dict[str, Any]) -> str:
    low, high = c["difference_ci"]
    return f"{fmt_pp(c['difference'])} [{fmt_pp(low)}, {fmt_pp(high)}]"


_LATEX_SPECIAL = {
    "\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#", "_": r"\_",
    "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}",
}


def latex_escape(text: str) -> str:
    """Escape LaTeX's special characters in plain text."""
    return "".join(_LATEX_SPECIAL.get(ch, ch) for ch in str(text))


def latex_num(text: str) -> str:
    """A formatted number for a LaTeX cell: real minus signs, escaped < and %."""
    text = latex_escape(text)
    text = re.sub(r"(?<![\w.])-(?=\d)", "$-$", text)
    return text.replace("<", "$<$")


def _significant(c: Optional[dict[str, Any]]) -> bool:
    return bool(c and c["p_holm"] is not None and c["p_holm"] < 0.05)


def _scenario_n(report: dict[str, Any], model: str) -> Optional[int]:
    ns = [r[SCENARIO]["accuracy"]["n"] for r in report["results"][model].values() if r.get(SCENARIO)]
    return max(ns) if ns else None


def _hands_n(report: dict[str, Any], model: str) -> Optional[int]:
    ns = [r[NATURAL]["accuracy"]["n"] for r in report["results"][model].values() if r.get(NATURAL)]
    return max(ns) if ns else None


def main_table_rows(report: dict[str, Any], model: str) -> list[dict[str, str]]:
    """One row per config with every formatted main-table cell (plain text; "---" = not applicable)."""
    rows = []
    for config in CONFIG_ORDER:
        result = report["results"][model][config]
        row = {"config": config_label(config), "missing": [], "significant": {}}
        for kind in KINDS:
            numbers = result.get(kind)
            prefix = "nat" if kind == NATURAL else "scn"
            if numbers is None:
                row["missing"].append(kind)
                for key in ("acc", "diff", "p", "ev"):
                    row[f"{prefix}_{key}"] = "missing"
                row[f"{prefix}_invalid"] = "--"
                continue
            row[f"{prefix}_acc"] = fmt_acc_ci(numbers["accuracy"])
            row[f"{prefix}_invalid"] = str(numbers["invalid"])
            c = numbers["comparison"]
            row["significant"][kind] = _significant(c)
            if c is None:
                for key in ("diff", "p", "ev"):
                    row[f"{prefix}_{key}"] = "---"
            else:
                row[f"{prefix}_diff"] = fmt_diff_ci(c)
                row[f"{prefix}_p"] = fmt_p(c["p_holm"])
                row[f"{prefix}_ev"] = fmt_units(c["ev_loss_change"])
        rows.append(row)
    return rows


# --- Markdown -------------------------------------------------------------------------


def markdown_main_table(report: dict[str, Any], model: str) -> str:
    lines = [
        "| Config | Natural acc % [95% CI] | Δ pp [95% CI] | p Holm | ΔEV loss | "
        "Scenario acc % [95% CI] | Δ pp [95% CI] | p Holm | ΔEV loss | Invalid (nat / scn) |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for row in main_table_rows(report, model):
        bold = lambda text, kind: f"**{text}**" if row["significant"].get(kind) else text  # noqa: E731
        lines.append(
            f"| {row['config']} | {row['nat_acc']} | {row['nat_diff']} | {bold(row['nat_p'], NATURAL)} | "
            f"{row['nat_ev']} | {row['scn_acc']} | {row['scn_diff']} | {bold(row['scn_p'], SCENARIO)} | "
            f"{row['scn_ev']} | {row['nat_invalid']} / {row['scn_invalid']} |")
    return "\n".join(lines)


def _coverage_cells(numbers: Optional[dict[str, Any]]) -> tuple[str, str]:
    if not numbers or not numbers.get("coverage"):
        return "n/a", "n/a"
    cov = numbers["coverage"]
    text = lambda p: f"{fmt_acc_ci(p)} (n={p['n']})" if p["n"] else "n/a (n=0)"  # noqa: E731
    return text(cov["covered"]), text(cov["uncovered"])


def markdown_coverage_table(report: dict[str, Any]) -> str:
    lines = ["| Model | Config | Natural covered | Natural uncovered | Scenario covered | Scenario uncovered |",
             "|---|---|---|---|---|---|"]
    for model in report["models"]:
        for config in CONFIG_ORDER:
            result = report["results"][model][config]
            nat = _coverage_cells(result.get(NATURAL))
            scn = _coverage_cells(result.get(SCENARIO))
            lines.append(f"| {model_label(model)} | {config_label(config)} | {nat[0]} | {nat[1]} | {scn[0]} | {scn[1]} |")
    return "\n".join(lines)


def flip_rows(report: dict[str, Any]) -> list[tuple[str, str, dict[str, Optional[dict[str, Any]]]]]:
    """(model, config, {kind: flips or None}) for every self-evaluation config with any run."""
    rows = []
    for model in report["models"]:
        for config in SELF_CONFIGS:
            result = report["results"][model][config]
            flips = {kind: (result.get(kind) or {}).get("flips") for kind in KINDS}
            if any(flips.values()):
                rows.append((model, config, flips))
    return rows


def markdown_flips_table(report: dict[str, Any]) -> str:
    lines = ["| Model | Config | Kind | n | First acc % | Final acc % | Flips | Fixes | Breaks | "
             "Wrong→wrong | Second reply invalid |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for model, config, flips in flip_rows(report):
        for kind in KINDS:
            f = flips[kind]
            if f is None:
                continue
            lines.append(f"| {model_label(model)} | {config_label(config)} | {KIND_LABELS[kind]} | {f['n']} | "
                         f"{fmt_pct(f['first_accuracy']['rate'])} | {fmt_pct(f['final_accuracy']['rate'])} | "
                         f"{f['flips']} | {f['fixes']} | {f['breaks']} | {f['neutral']} | {f['second_invalid']} |")
    return "\n".join(lines)


# --- LaTeX ----------------------------------------------------------------------------

LATEX_HEADER = ("% Generated by scripts/ablation_report.py; regenerate instead of editing.\n"
                "% Needs \\usepackage{booktabs} in the preamble.\n")


def _latex_label(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def latex_main_table(report: dict[str, Any], model: str) -> str:
    holm = report["method"]["family_sizes"]
    n_hands, n_cells = _hands_n(report, model), _scenario_n(report, model)
    nat_head = "Natural run" + (f" ({n_hands:,} first decisions)" if n_hands else "")
    scn_head = "Scenario set" + (f" ({n_cells} cells)" if n_cells else "")
    caption = (
        f"Harness ablation for {latex_escape(model_label(model))}. Accuracy (\\%) is over first decisions with "
        "Wilson 95\\% CIs. $\\Delta$ is the paired difference from the same model's baseline in percentage "
        "points (Newcombe 95\\% CI). $p_{\\mathrm{Holm}}$ is the exact McNemar p-value, Holm-adjusted within the "
        f"natural ({holm[NATURAL]} tests) and scenario ({holm[SCENARIO]} tests) families; bold: "
        "$p_{\\mathrm{Holm}} < 0.05$. $\\Delta$EV is the change in mean EV loss per decision (units per "
        "1-unit bet; negative is better). Invalid: invalid first decisions, natural / scenario."
    )

    def cell(row, key, kind=None):
        text = row[key]
        if text == "missing":
            return "\\textit{missing}"
        if text == "---":
            return "---"
        out = latex_num(text)
        return f"\\textbf{{{out}}}" if kind and row["significant"].get(kind) else out

    body = []
    for row in main_table_rows(report, model):
        body.append(
            f"    {latex_escape(row['config'])} & {cell(row, 'nat_acc')} & {cell(row, 'nat_diff')} & "
            f"{cell(row, 'nat_p', NATURAL)} & {cell(row, 'nat_ev')} & {cell(row, 'scn_acc')} & "
            f"{cell(row, 'scn_diff')} & {cell(row, 'scn_p', SCENARIO)} & {cell(row, 'scn_ev')} & "
            f"{row['nat_invalid']} / {row['scn_invalid']} \\\\")
        if row["config"] == CONFIG_LABELS["baseline"]:
            body.append("    \\addlinespace")
    return LATEX_HEADER + "\n".join([
        "\\begin{table*}[t]",
        "  \\centering",
        "  \\small",
        "  \\setlength{\\tabcolsep}{4pt}",
        f"  \\caption{{{caption}}}",
        f"  \\label{{tab:ablation-{_latex_label(model)}}}",
        "  \\begin{tabular}{@{}l llrr llrr c@{}}",
        "    \\toprule",
        f"    & \\multicolumn{{4}}{{c}}{{{nat_head}}} & \\multicolumn{{4}}{{c}}{{{scn_head}}} & \\\\",
        "    \\cmidrule(lr){2-5} \\cmidrule(lr){6-9}",
        "    Configuration & Accuracy & $\\Delta$ & $p_{\\mathrm{Holm}}$ & $\\Delta$EV & "
        "Accuracy & $\\Delta$ & $p_{\\mathrm{Holm}}$ & $\\Delta$EV & Invalid \\\\",
        "    \\midrule",
        *body,
        "    \\bottomrule",
        "  \\end{tabular}",
        "\\end{table*}",
        "",
    ])


def latex_coverage_table(report: dict[str, Any]) -> str:
    caption = ("Accuracy (\\%, Wilson 95\\% CI) on first decisions in covered cells (a strategy-information "
               "principle applies) and uncovered cells. Descriptive only, not tested.")
    body = []
    for i, model in enumerate(report["models"]):
        if i:
            body.append("    \\midrule")
        body.append(f"    \\multicolumn{{5}}{{@{{}}l}}{{\\textit{{{latex_escape(model_label(model))}}}}} \\\\")
        for config in CONFIG_ORDER:
            result = report["results"][model][config]
            cells = [*_coverage_cells(result.get(NATURAL)), *_coverage_cells(result.get(SCENARIO))]
            cells = [latex_num(c.split(" (n=")[0]) for c in cells]
            body.append(f"    \\quad {latex_escape(config_label(config))} & " + " & ".join(cells) + " \\\\")
    counts = _coverage_counts(report)
    head = lambda kind, which: (f"{which} (n={counts[kind][which.lower()]})"  # noqa: E731
                                if counts[kind] else which)
    return LATEX_HEADER + "\n".join([
        "\\begin{table*}[t]",
        "  \\centering",
        "  \\small",
        f"  \\caption{{{caption}}}",
        "  \\label{tab:ablation-coverage}",
        "  \\begin{tabular}{@{}l llll@{}}",
        "    \\toprule",
        "    & \\multicolumn{2}{c}{Natural run} & \\multicolumn{2}{c}{Scenario set} \\\\",
        "    \\cmidrule(lr){2-3} \\cmidrule(lr){4-5}",
        f"    Configuration & {head(NATURAL, 'Covered')} & {head(NATURAL, 'Uncovered')} & "
        f"{head(SCENARIO, 'Covered')} & {head(SCENARIO, 'Uncovered')} \\\\",
        "    \\midrule",
        *body,
        "    \\bottomrule",
        "  \\end{tabular}",
        "\\end{table*}",
        "",
    ])


def _coverage_counts(report: dict[str, Any]) -> dict[str, Optional[dict[str, int]]]:
    """Covered/uncovered n per kind for the column headers, or None when the baseline runs disagree."""
    counts: dict[str, Optional[dict[str, int]]] = {}
    for kind in KINDS:
        seen = set()
        for model in report["models"]:
            numbers = report["results"][model]["baseline"].get(kind)
            if numbers and numbers.get("coverage"):
                cov = numbers["coverage"]
                seen.add((cov["covered"]["n"], cov["uncovered"]["n"]))
        counts[kind] = ({"covered": next(iter(seen))[0], "uncovered": next(iter(seen))[1]}
                        if len(seen) == 1 else None)
    return counts


def latex_flips_table(report: dict[str, Any]) -> str:
    caption = ("Self-evaluation on first decisions. A flip is a final answer that differs from the first; a fix "
               "goes from incorrect to correct, a break from correct to incorrect. Wrong$\\to$wrong: flipped "
               "between two incorrect actions. 2nd inv.: second reply invalid (the first answer was kept).")
    body = []
    for model, config, flips in flip_rows(report):
        cells = []
        for kind in KINDS:
            f = flips[kind]
            if f is None:
                cells += ["---"] * 5
            else:
                cells += [f"{fmt_pct(f['first_accuracy']['rate'])} $\\to$ {fmt_pct(f['final_accuracy']['rate'])}",
                          str(f["fixes"]), str(f["breaks"]), str(f["neutral"]), str(f["second_invalid"])]
        body.append(f"    {latex_escape(model_label(model))} & {latex_escape(config_label(config))} & "
                    + " & ".join(cells) + " \\\\")
    if not body:
        body.append("    \\multicolumn{12}{c}{\\textit{no self-evaluation runs}} \\\\")
    sub = "Accuracy & Fixes & Breaks & W$\\to$W & 2nd inv."
    return LATEX_HEADER + "\n".join([
        "\\begin{table*}[t]",
        "  \\centering",
        "  \\small",
        "  \\setlength{\\tabcolsep}{4pt}",
        f"  \\caption{{{caption}}}",
        "  \\label{tab:ablation-flips}",
        "  \\begin{tabular}{@{}ll lrrrr lrrrr@{}}",
        "    \\toprule",
        "    & & \\multicolumn{5}{c}{Natural run} & \\multicolumn{5}{c}{Scenario set} \\\\",
        "    \\cmidrule(lr){3-7} \\cmidrule(lr){8-12}",
        f"    Model & Configuration & {sub} & {sub} \\\\",
        "    \\midrule",
        *body,
        "    \\bottomrule",
        "  \\end{tabular}",
        "\\end{table*}",
        "",
    ])


# --- summary.md -------------------------------------------------------------------------


def render_summary(report: dict[str, Any], charts: dict[str, list[str]], tables: dict[str, str]) -> str:
    """summary.md: inventory, the tables (Markdown), chart links and the LaTeX files."""
    m = report["method"]
    lines = [f"# Blackjack harness ablation (label `{report['label']}`, seed {report['seed']})", ""]
    lines += ["## Method", "",
              f"- Accuracy: {m['accuracy']}; {m['accuracy_ci']} CIs.",
              f"- Difference vs the same model's baseline: {m['difference_ci']}.",
              f"- Test: {m['test']}; {m['correction']} "
              f"(natural: {m['family_sizes'][NATURAL]} tests, scenario: {m['family_sizes'][SCENARIO]} tests).",
              f"- EV loss: {m['ev_loss']}.",
              "- Bold p values: Holm-adjusted p < 0.05. Covered/uncovered and flips are descriptive (not tested).",
              ""]
    lines += ["## Runs", "", "| Model | Config | Kind | Folder |", "|---|---|---|---|"]
    lines += [f"| {r['model']} | {r['config']} | {r['kind']} | `{r['path']}` |" for r in report["runs"]]
    lines.append("")
    if report["missing"]:
        lines += ["## Missing runs (skipped)", ""]
        lines += [f"- {e['model']} {e['config']} {e['kind']}: expected `{e['expected_folder']}`"
                  for e in report["missing"]]
        lines.append("")
    if report["notes"]:
        lines += ["## Notes", ""] + [f"- {note}" for note in report["notes"]] + [""]

    for model in report["models"]:
        lines += [f"## {model_label(model)}", "", markdown_main_table(report, model), ""]
        best = report["best_config"].get(model)
        if best:
            lines += [f"Best config by scenario accuracy: **{config_label(best['config'])}** "
                      f"({fmt_acc_ci(best['scenario_accuracy'])}%).", ""]
    lines += ["## Covered vs uncovered cells (first decisions, descriptive)", "",
              markdown_coverage_table(report), ""]
    if flip_rows(report):
        lines += ["## Self-evaluation flips (first decisions)", "", markdown_flips_table(report), ""]

    if charts:
        lines += ["## Charts", ""]
        for title, files in charts.items():
            png = [f for f in files if f.endswith(".png")]
            pdf = [f for f in files if f.endswith(".pdf")]
            lines += [f"### {title}", ""] + [f"![{title}]({f})" for f in png]
            if pdf:
                lines += ["", "Vector: " + ", ".join(f"[`{f}`]({f})" for f in pdf)]
            lines.append("")
    if tables:
        lines += ["## LaTeX tables", "", "`\\input{...}` these (needs `\\usepackage{booktabs}`):", ""]
        lines += [f"- `{name}`: {what}" for name, what in tables.items()]
        lines.append("")
    return "\n".join(lines)
