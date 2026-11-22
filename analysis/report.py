"""Writes results.md for one run and the comparison table for several runs.

Everything here formats numbers that analysis.metrics computed from the logs.
The only number not from a run's own logs is BASIC_STRATEGY_RETURN, the exact
basic-strategy return under our rule set, and it is always labelled as such.

Scenario runs: every cell metric covers only the graded scenario cells, the
follow-up decisions get their own clearly labelled line, and returns are not
reported (the forced hands are not a natural sample).
"""

import csv
import math
from pathlib import Path

from analysis.metrics import ACTIONS, CHOSEN_COLUMNS, SMALL_SAMPLE_N, RunSummary
from analysis.stats import MeanCI, Proportion

# Exact return per hand of our basic strategy table under the rule set: every first
# deal enumerated with blackjack/ev.py (dealer blackjacks and 3:2 blackjacks
# included); -0.4568% to four digits. Pinned by tests/test_analysis_scenario.py.
BASIC_STRATEGY_RETURN = -0.00457
BASIC_STRATEGY_RETURN_SOURCE = "exact, computed; not from this run"
BASIC_STRATEGY_SIMULATION_NOTE = (
    "A 3,000,000-hand simulation of the same strategy (scripts/sanity_house_edge.py) "
    "gave -0.425% (95% CI -0.555% to -0.296%)."
)

CHART_CAPTIONS = {
    "accuracy_by_hand_type.png": "Decision accuracy for hard, soft and pair decisions; whiskers are Wilson 95% CIs, n = decisions.",
    "confusion_matrix.png": "Basic-strategy action (rows) vs the action the model chose (columns); outlined diagonal = correct decisions.",
    "accuracy_heatmap.png": "Decision accuracy by player hand and dealer upcard; each cell shows accuracy (n); grey cells had no decisions. Sized for full text width (figure*).",
    "action_frequency.png": "Share of decisions on which the model chose each action vs the basic-strategy action at the same decisions; bar labels are counts.",
    "ev_loss_heatmap.png": "Mean EV loss per decision (units per 1-unit bet) by player hand and dealer upcard; each cell shows mean loss (n); grey cells had no decisions. Sized for full text width (figure*).",
}

# Scenario runs: one graded decision per cell, so the heatmaps show single results.
SCENARIO_CHART_CAPTIONS = {
    **CHART_CAPTIONS,
    "accuracy_heatmap.png": "Scenario set: the model's action in each basic-strategy cell (one graded decision per cell); "
                            "blue = correct, orange = incorrect with the basic-strategy action in brackets. "
                            "Sized for full text width (figure*).",
    "ev_loss_heatmap.png": "Scenario set: EV loss of the model's action in each cell (units per 1-unit bet; one graded "
                           "decision per cell); grey cells are not in the scenario set. Sized for full text width (figure*).",
}

SCENARIO_SCOPE = (
    "> **Scenario run:** every cell metric below (accuracy, invalid actions, breakdowns, confusion matrix, "
    "action frequency, mistakes, EV loss, heatmaps) uses only the graded scenario cells, the first decision of "
    "each forced hand (is_scenario_cell = true). Later decisions in the same hands are reported only on the "
    "\"Follow-up decisions\" line. Returns are not reported: the forced hands are not a natural sample."
)


# --- formatting helpers ------------------------------------------------------------


def pct(value: float, digits: int = 1) -> str:
    """0.5 -> "50.0%"; nan -> "n/a"."""
    return "n/a" if math.isnan(value) else f"{value * 100:.{digits}f}%"


def proportion_text(p: Proportion) -> str:
    """E.g. "50.0% (11/22; 95% CI 30.7%-69.3%)"."""
    if p.n == 0:
        return "n/a (0 decisions)"
    return f"{pct(p.rate)} ({p.k}/{p.n}; 95% CI {pct(p.low)}-{pct(p.high)})"


def units(value: float) -> str:
    """Signed units with 3 decimals, e.g. "+0.150", "-1.000"."""
    return "n/a" if math.isnan(value) else f"{value:+.3f}"


def mean_text(m: MeanCI) -> str:
    """E.g. "-0.100 units/hand (95% CI -0.700 to +0.500; n = 20 hands)"."""
    if m.n == 0:
        return "n/a (0 hands)"
    ci = "CI not defined for n < 2" if math.isnan(m.half_width) else f"95% CI {units(m.low)} to {units(m.high)}"
    return f"{units(m.mean)} units/hand ({ci}; n = {m.n} hands)"


def number(value: float, digits: int = 2) -> str:
    return "n/a" if math.isnan(value) else f"{value:.{digits}f}"


def table(headers: list[str], rows: list[list[str]]) -> str:
    """A markdown table."""
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    lines += ["| " + " | ".join(str(cell) for cell in row) + " |" for row in rows]
    return "\n".join(lines)


def rule_set_text(rules: dict | None) -> str:
    """Plain-English one-liner from metadata['rule_set']."""
    if not rules:
        return "not logged"
    parts = [
        f"{rules['num_decks']} decks",
        "dealer hits soft 17" if rules["dealer_hits_soft_17"] else "dealer stands on soft 17",
        "double after split allowed" if rules["double_after_split"] else "no double after split",
        f"max {rules['max_splits']} split",
        "split aces get one card" if rules["split_aces_one_card"] else "split aces play on",
        "surrender allowed" if rules["surrender_allowed"] else "no surrender",
        "insurance offered" if rules["insurance_offered"] else "no insurance",
        "dealer peeks" if rules["dealer_peeks"] else "no peek",
        "blackjack pays 3:2" if rules["blackjack_payout"] == 1.5 else f"blackjack pays {rules['blackjack_payout']}:1",
        f"flat {rules['bet']}-unit bet",
    ]
    return ", ".join(parts)


def _harness_text(metadata: dict) -> str:
    flags = metadata.get("harness_flags") or {}
    on = [name for name, enabled in flags.items() if enabled]
    return f"{metadata.get('harness_config', 'not logged')} (components on: {', '.join(on) if on else 'none'})"


# --- results.md --------------------------------------------------------------------


def _counts_line(s: RunSummary) -> str:
    if not s.is_scenario:
        return f"- **Hands:** {len(s.run.hands)}  |  **Decisions:** {s.accuracy.n}"
    return (f"- **Run type:** scenario set ({s.run.metadata.get('scenario_set_version', 'version not logged')})  |  "
            f"**Scenario hands:** {len(s.run.hands)}  |  **Graded scenario cells:** {s.accuracy.n}  |  "
            f"**Follow-up decisions (not graded as cells):** {s.follow_up.n}")


def _header(s: RunSummary) -> str:
    md = s.run.metadata
    options = md.get("ollama_options") or {}
    started = md.get("started_at", "not logged")
    return "\n".join([
        f"# Results: {s.run.name}",
        "",
        f"- **Run id:** `{s.run.run_id}`",
        f"- **Model:** `{md.get('model', 'not logged')}` (digest `{md.get('model_digest', 'not logged')}`), Ollama {md.get('ollama_version', 'not logged')}",
        f"- **Prompt version:** {s.run.prompt_version}",
        f"- **Harness config:** {_harness_text(md)}",
        f"- **Rule set:** {rule_set_text(md.get('rule_set'))}",
        f"- **Sampling:** temperature {options.get('temperature', 'n/a')}, Ollama seed {options.get('seed', 'n/a')}, num_predict {options.get('num_predict', 'n/a')}",
        f"- **Run seed:** {md.get('run_seed', 'not logged')}",
        _counts_line(s),
        f"- **Date:** {started[:10]} (started {started})",
    ])


def _follow_up_text(s: RunSummary) -> str:
    if s.follow_up.n == 0:
        return "none"
    return f"{proportion_text(s.follow_up)}; {s.follow_up_invalid.k} invalid"


def _scenario_headline(s: RunSummary) -> str:
    rows = [
        ["Decision accuracy on scenario cells (primary metric)", proportion_text(s.accuracy)],
        ["Invalid-action rate (scenario cells)", proportion_text(s.invalid)],
        ["Secondary: follow-up decisions (is_scenario_cell = false; not chart cells, not in any other number here)",
         _follow_up_text(s)],
        ["Decisions per hand (all logged decisions)", number(s.decisions_per_hand)],
        ["Mean latency per decision", f"{number(s.mean_latency_s)} s"],
        ["Mean tokens generated per decision (eval_count)", number(s.mean_eval_count, 1)],
    ]
    return "## Headline numbers\n\n" + SCENARIO_SCOPE + "\n\n" + table(["Metric", "Value"], rows)


def _headline(s: RunSummary) -> str:
    if s.is_scenario:
        return _scenario_headline(s)
    rows = [
        ["Decision accuracy (primary metric)", proportion_text(s.accuracy)],
        ["Invalid-action rate", proportion_text(s.invalid)],
        ["Mean return per hand", mean_text(s.returns)],
        ["Net result", f"{units(s.total_payout)} units over {len(s.run.hands)} hands"],
        ["Reference: basic-strategy return", f"{pct(BASIC_STRATEGY_RETURN, 3)} per hand ({BASIC_STRATEGY_RETURN_SOURCE}). {BASIC_STRATEGY_SIMULATION_NOTE}"],
        ["Decisions per hand", number(s.decisions_per_hand)],
        ["Mean latency per decision", f"{number(s.mean_latency_s)} s"],
        ["Mean tokens generated per decision (eval_count)", number(s.mean_eval_count, 1)],
    ]
    note = (
        "> **Note on returns:** at this sample size, return per hand is dominated by card variance: "
        f"the 95% CI half-width is ±{number(s.returns.half_width, 3)} units/hand, against a basic-strategy "
        f"return of {BASIC_STRATEGY_RETURN:+.5f} units/hand. Decision accuracy is the meaningful number; "
        "returns are reported for completeness."
    )
    return "## Headline numbers\n\n" + table(["Metric", "Value"], rows) + "\n\n" + note


def _invalid_section(s: RunSummary) -> str:
    if not s.invalid_reasons:
        return "## Invalid actions\n\nNo invalid actions (0 of {} decisions).".format(s.invalid.n)
    rows = [[reason, count] for reason, count in sorted(s.invalid_reasons.items(), key=lambda kv: -kv[1])]
    return "## Invalid actions by reason\n\n" + table(["invalid_reason", "Count"], rows)


def _group_table(title: str, label_header: str, groups) -> str:
    rows = []
    for g in groups:
        p = g.result
        ci = f"{pct(p.low)}-{pct(p.high)}" if p.n else "n/a"
        rows.append([g.label, p.n, p.k, pct(p.rate), ci, "small sample" if g.small_sample else ""])
    return f"## {title}\n\n" + table([label_header, "n", "Correct", "Accuracy", "95% CI", "Flag"], rows) + (
        f"\n\n\"small sample\" = fewer than {SMALL_SAMPLE_N} decisions."
    )


def _confusion_section(s: RunSummary) -> str:
    rows = []
    for optimal in ACTIONS:
        counts = [s.confusion[optimal][chosen] for chosen in CHOSEN_COLUMNS]
        rows.append([f"**{optimal}**"] + counts + [sum(counts)])
    return (
        "## Confusion matrix (rows: basic-strategy action, columns: model's chosen action)\n\n"
        + table(["Basic strategy \\ Model"] + CHOSEN_COLUMNS + ["Total"], rows)
        + "\n\n\"invalid\" = invalid action (the engine stood as a fallback; that stand is not counted as a stand choice)."
    )


def _frequency_section(s: RunSummary) -> str:
    n = s.accuracy.n or 1
    model, strategy = s.frequency["model"], s.frequency["basic_strategy"]
    rows = [[a, model[a], pct(model[a] / n), strategy[a], pct(strategy[a] / n)] for a in CHOSEN_COLUMNS]
    sentences = [
        f"- The model chose {a} on {pct(model[a] / n)} of decisions; basic strategy calls for {a} on {pct(strategy[a] / n)}."
        for a in ACTIONS
    ]
    return (
        "## Action frequency (model vs basic strategy, same decisions)\n\n"
        + table(["Action", "Model count", "Model %", "Basic strategy count", "Basic strategy %"], rows)
        + "\n\n" + "\n".join(sentences)
    )


def _mistakes_section(s: RunSummary) -> str:
    if s.is_scenario:
        return (
            "## Mistakes\n\n"
            f"{s.accuracy.n - s.accuracy.k} of {s.accuracy.n} scenario cells were incorrect. Each cell is played once, "
            "so there is no by-count ranking: see the confusion matrix above for mistake types, the costliest "
            "mistakes below, and `accuracy_heatmap.png` for which cells were wrong."
        )
    if not s.mistakes:
        return "## Most common mistakes\n\nNo incorrect decisions."
    lines = [f"{i}. {text} ×{count}" for i, (text, count) in enumerate(s.mistakes, start=1)]
    return "## Most common mistakes (top 10 by count)\n\n" + "\n".join(lines)


def _ev_loss_section(s: RunSummary) -> str:
    ev = s.ev_loss
    if ev is None:
        return ""
    scope = (
        "Scenario run: only the graded scenario cell of each hand is counted (is_scenario_cell = true). "
        if s.is_scenario else ""
    )
    rows = [
        ["Total EV loss", f"{number(ev.total, 3)} units over {ev.n_decisions} decisions"],
        ["Mean EV loss per decision", f"{number(ev.mean_per_decision, 4)} units"],
        ["Mean EV loss per hand", f"{number(ev.mean_per_hand, 4)} units (n = {ev.n_hands} hands)"],
        ["Mean EV loss per mistake", f"{number(ev.mean_per_mistake, 4)} units (n = {ev.n_mistakes} incorrect decisions)"],
        ["Of which invalid actions", f"{number(ev.invalid.total, 3)} units over {ev.invalid.n} decisions "
                                     f"(mean {number(ev.invalid.mean, 4)})"],
        ["Decisions where the model beat the chart", f"{ev.n_negative} (total {number(ev.negative_total, 4)} units)"],
    ]
    type_rows = [[g.label, g.n, number(g.total, 3), number(g.mean, 4)] for g in ev.by_hand_type]
    costly = [[i, g.label, g.n, number(g.total, 3), number(g.mean, 4)] for i, g in enumerate(ev.costliest, start=1)]
    costly_text = (
        table(["#", "Mistake", "n", "Total EV loss", "Mean EV loss"], costly) if costly else "No incorrect decisions."
    )
    return "\n\n".join([
        "## EV loss (secondary metric)",
        "EV loss = EV(basic-strategy action) - EV(action played), in units per 1-unit initial bet; "
        "a correct decision has EV loss 0. EVs are exact for 6 decks with the player's cards and the "
        "dealer's upcard removed, given the dealer has no blackjack (blackjack/ev.py). "
        "Invalid actions are charged for the stand the engine played as a fallback. "
        "A few composition-dependent decisions (e.g. a three-card 16 vs 10) have a slightly negative "
        "loss when the model deviated from the chart; losses are not clipped. " + scope,
        table(["Metric", "Value"], rows),
        "### EV loss by hand type\n\n" + table(["Hand type", "n", "Total EV loss", "Mean EV loss"], type_rows),
        "### Costliest mistakes (top 10 by total EV loss)\n\n" + costly_text,
    ])


def _charts_section(chart_names: list[str], scenario: bool = False) -> str:
    captions = SCENARIO_CHART_CAPTIONS if scenario else CHART_CAPTIONS
    lines = [f"- `{name}`: {captions.get(name, '')}" for name in chart_names]
    return "## Charts\n\n" + "\n".join(lines)


def results_markdown(s: RunSummary, chart_names: list[str]) -> str:
    """The full results.md text for one run."""
    sections = [
        _header(s),
        _headline(s),
        _invalid_section(s),
        _group_table("Accuracy by hand type", "Hand type", s.by_hand_type)
        + "\n\nPair = splitting was legal at that decision; pairs that could not be split are counted by their hard/soft total.",
        _group_table("Accuracy by dealer upcard", "Upcard", s.by_upcard) + "\n\nJ, Q and K are counted as 10.",
        _confusion_section(s),
        _frequency_section(s),
        _mistakes_section(s),
        _ev_loss_section(s),
        _charts_section(chart_names, s.is_scenario),
    ]
    return "\n\n".join(section for section in sections if section) + "\n"


def write_results(s: RunSummary, out_dir: Path, chart_paths: list[Path]) -> Path:
    path = out_dir / "results.md"
    path.write_text(results_markdown(s, [p.name for p in chart_paths]), encoding="utf-8")
    return path


# --- multi-run comparison ------------------------------------------------------------


COMPARISON_HEADERS = [
    "run_dir", "run_id", "prompt_version", "harness_config", "model", "hands", "decisions",
    "accuracy", "accuracy_ci_low", "accuracy_ci_high", "invalid_rate", "invalid_count",
    "mean_return_per_hand", "return_ci_low", "return_ci_high",
    "ev_loss_total", "ev_loss_per_decision", "ev_loss_per_hand", "ev_loss_per_mistake", "ev_loss_invalid_total",
    "run_type", "follow_up_decisions", "follow_up_accuracy",
]


def _blank_if_none(value):
    return "" if value is None else value


def comparison_rows(summaries: list[RunSummary]) -> list[dict]:
    """One machine-readable row per run (also written as comparison.csv)."""
    rows = []
    for s in summaries:
        md = s.run.metadata
        rows.append({
            "run_dir": s.run.name,
            "run_id": s.run.run_id,
            "prompt_version": s.run.prompt_version,
            "harness_config": md.get("harness_config", "not logged"),
            "model": md.get("model", "not logged"),
            "hands": len(s.run.hands),
            "decisions": s.accuracy.n,
            "accuracy": s.accuracy.rate,
            "accuracy_ci_low": s.accuracy.low,
            "accuracy_ci_high": s.accuracy.high,
            "invalid_rate": s.invalid.rate,
            "invalid_count": s.invalid.k,
            "mean_return_per_hand": _blank_if_none(s.returns and s.returns.mean),
            "return_ci_low": _blank_if_none(s.returns and s.returns.low),
            "return_ci_high": _blank_if_none(s.returns and s.returns.high),
            "ev_loss_total": s.ev_loss.total,
            "ev_loss_per_decision": s.ev_loss.mean_per_decision,
            "ev_loss_per_hand": s.ev_loss.mean_per_hand,
            "ev_loss_per_mistake": s.ev_loss.mean_per_mistake,
            "ev_loss_invalid_total": s.ev_loss.invalid.total,
            "run_type": s.run_type,
            "follow_up_decisions": _blank_if_none(s.follow_up and s.follow_up.n),
            "follow_up_accuracy": _blank_if_none(s.follow_up and s.follow_up.rate),
        })
    return rows


def comparison_markdown(summaries: list[RunSummary]) -> str:
    rows = []
    for s in summaries:
        md = s.run.metadata
        rows.append([
            f"`{s.run.run_id}`", s.run_type, s.run.prompt_version, _harness_text(md), f"`{md.get('model', 'not logged')}`",
            len(s.run.hands), s.accuracy.n, proportion_text(s.accuracy), proportion_text(s.invalid),
            "not reported (scenario run)" if s.returns is None else mean_text(s.returns),
            number(s.ev_loss.mean_per_decision, 4), number(s.ev_loss.mean_per_hand, 4),
        ])
    headers = ["run_id", "Run type", "prompt_version", "Harness config", "Model", "Hands", "Decisions",
               "Accuracy (95% CI)", "Invalid rate (95% CI)", "Mean return/hand (95% CI)",
               "EV loss/decision", "EV loss/hand"]
    notes = ""
    if len({s.run_type for s in summaries}) > 1:
        notes = (
            "\n\nRuns of different types are shown side by side and not pooled. A natural run weights each "
            "basic-strategy cell by how often it is dealt; the scenario set grades every cell exactly once, so "
            "the two accuracies answer different questions and are never combined into one number."
        )
    if any(s.is_scenario for s in summaries):
        notes += (
            "\n\nFor scenario runs, Decisions and every accuracy, invalid and EV-loss figure count only the graded "
            "scenario cells (is_scenario_cell = true); follow-up decisions are in comparison.csv "
            "(follow_up_decisions, follow_up_accuracy) and in the run's results.md."
        )
    return (
        "# Run comparison\n\n" + table(headers, rows) + notes + "\n"
        + "\nAccuracy and invalid-rate CIs are Wilson 95% intervals; return CIs are normal-approximation 95% intervals."
        + " EV loss is in units per 1-unit bet (0 = every decision matched basic strategy)."
        + " Each run's full breakdown is in its own subfolder.\n\n"
        + "- `comparison_accuracy.png`: decision accuracy per run with Wilson 95% CIs; n = decisions.\n"
    )


def write_comparison(summaries: list[RunSummary], out_dir: Path) -> list[Path]:
    md_path = out_dir / "comparison.md"
    md_path.write_text(comparison_markdown(summaries), encoding="utf-8")
    csv_path = out_dir / "comparison.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COMPARISON_HEADERS)
        writer.writeheader()
        writer.writerows(comparison_rows(summaries))
    return [md_path, csv_path]
