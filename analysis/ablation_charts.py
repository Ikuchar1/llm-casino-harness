"""Figures for the final ablation (scripts/ablation_report.py), drawn from build_report's data.

Every chart is saved twice: a 300 dpi PNG (slides) and a vector PDF (the paper, fonts
embedded as TrueType). Each config keeps one color in every chart and for every model;
the baseline is neutral gray. Models are separated by panel, never by color. The
palette was checked with the dataviz validator (adjacent pairs pass the colorblind and
normal-vision separation floors); identity never rests on color alone, because every
mark is also named on its axis or in a legend.
"""

import math
import textwrap
from pathlib import Path
from typing import Any, Optional

import matplotlib

matplotlib.use("Agg")  # draw to files only

import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Patch, Rectangle  # noqa: E402

from analysis.ablation_report import (  # noqa: E402
    BOTH_RIGHT,
    BOTH_WRONG,
    BROKE,
    CONFIG_ORDER,
    FIXED,
    KIND_LABELS,
    KINDS,
    NATURAL,
    SCENARIO,
    config_label,
    flip_rows,
    model_label,
)
from analysis.metrics import UPCARDS  # noqa: E402

DPI = 300
TEXT_WIDTH_IN = 7.0

# One color per config, fixed across models and charts; baseline is neutral gray.
CONFIG_COLORS = {
    "baseline": "#898781",
    "prob": "#2a78d6",
    "prob_strat": "#eb6834",
    "prob_strat_self": "#1baf7a",
    "strat": "#eda100",
    "self": "#e87ba4",
}

# Scenario heatmap: config vs baseline on one cell. Blue = config better, red = worse.
CATEGORY_COLORS = {FIXED: "#1c5cab", BOTH_RIGHT: "#9ec5f4", BOTH_WRONG: "#f2a29f", BROKE: "#c42f30"}
CATEGORY_DARK = {FIXED: True, BOTH_RIGHT: False, BOTH_WRONG: False, BROKE: True}  # white text on dark fills
CATEGORY_LABELS = {FIXED: "Fixed (baseline wrong, config right)", BOTH_RIGHT: "Both right",
                   BOTH_WRONG: "Both wrong", BROKE: "Broke (baseline right, config wrong)"}

INK = "#0b0b0b"
INK_2 = "#52514e"
INK_MUTED = "#898781"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
SURFACE = "#ffffff"
BASELINE_BAND = "#ecebe6"
EMPTY_CELL = "#f1f0ec"

ACTION_LETTERS = {"hit": "H", "stand": "S", "double": "D", "split": "P", "invalid": "inv"}

STYLE = {
    "font.family": "sans-serif",
    "font.sans-serif": ["Arial", "Liberation Sans", "DejaVu Sans"],  # Arial has the arrow glyphs
    "font.size": 8,
    "axes.titlesize": 8.5,
    "axes.labelsize": 7.5,
    "xtick.labelsize": 7,
    "ytick.labelsize": 7.5,
    "legend.fontsize": 7,
    "axes.edgecolor": AXIS,
    "axes.linewidth": 0.6,
    "axes.labelcolor": INK_2,
    "axes.titlecolor": INK,
    "xtick.color": INK_2,
    "ytick.color": INK,
    "xtick.major.size": 0,
    "ytick.major.size": 0,
    "xtick.major.pad": 3,
    "ytick.major.pad": 4,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.spines.left": False,
    "figure.facecolor": SURFACE,
    "axes.facecolor": SURFACE,
    "savefig.facecolor": SURFACE,
    "savefig.dpi": DPI,
    "pdf.fonttype": 42,  # embed TrueType so the PDF text stays selectable and editable
    "ps.fonttype": 42,
    "legend.frameon": False,
}


def _save(fig, stem: Path) -> list[Path]:
    stem.parent.mkdir(parents=True, exist_ok=True)
    paths = [stem.parent / f"{stem.name}.png", stem.parent / f"{stem.name}.pdf"]  # names may contain dots
    for path in paths:
        fig.savefig(path, bbox_inches="tight", pad_inches=0.08)
    plt.close(fig)
    return paths


def _titles(fig, title: Optional[str], subtitle: Optional[str], top: float) -> None:
    """Left-aligned title and subtitle above the panels (y in figure coordinates)."""
    if title:
        fig.text(0.01, top, title, ha="left", va="bottom", fontsize=11, fontweight="bold", color=INK)
    if subtitle:
        subtitle = "\n".join(textwrap.wrap(subtitle, width=int(17 * fig.get_figwidth())))
        fig.text(0.01, top - 0.012, subtitle, ha="left", va="top", fontsize=7.5, color=INK_2)


def _pct(value: Optional[float]) -> str:
    return "" if value is None else f"{100 * value:.1f}"


def _grid_x(ax) -> None:
    ax.xaxis.grid(True, color=GRID, linewidth=0.5)
    ax.set_axisbelow(True)


def _accuracy_limits(report: dict[str, Any], key: str = "accuracy") -> tuple[float, float]:
    lows, highs = [], []
    for model in report["models"]:
        for config in CONFIG_ORDER:
            for kind in KINDS:
                numbers = report["results"][model][config].get(kind)
                if numbers and numbers[key]["rate"] is not None:
                    lows.append(numbers[key]["ci_low"])
                    highs.append(numbers[key]["ci_high"])
    if not lows:
        return 0.0, 1.0
    low, high = min(lows), max(highs)
    span = max(high - low, 0.1)
    # small pad on the left so a dot at 0% is not clipped; room on the right for the value labels
    return low - 0.04 * span, high + 0.42 * span


def _percent_ticks(ax, low: float, high: float) -> None:
    step = next(s for s in (0.05, 0.1, 0.2, 0.25) if (high - low) / s <= 7)
    first = max(0.0, step * math.ceil(low / step - 1e-9))
    ticks = []
    value = first
    while value <= min(high, 1.0) + 1e-9:
        ticks.append(round(value, 4))
        value += step
    ax.set_xticks(ticks)
    ax.set_xticklabels([f"{100 * t:.0f}" for t in ticks])


def _panel_grid(report: dict[str, Any], height_per_model: float, top_room: float, bottom_room: float = 0.45):
    models = report["models"]
    n = max(len(models), 1)
    height = height_per_model * n + top_room + bottom_room - 0.45
    fig, axes = plt.subplots(n, 2, figsize=(TEXT_WIDTH_IN, height), squeeze=False,
                             gridspec_kw={"wspace": 0.08, "hspace": 0.55})
    fig.subplots_adjust(left=0.17, right=0.99, top=1 - top_room / height, bottom=bottom_room / height)
    return fig, axes, models


# --- 1. accuracy by config ---------------------------------------------------------------


def accuracy_chart(report: dict[str, Any], stem: Path, titles: bool = True) -> list[Path]:
    """Dot + 95% CI per config, natural and scenario side by side, one row of panels per model."""
    with plt.rc_context(STYLE):
        fig, axes, models = _panel_grid(report, 1.75, 0.66 if titles else 0.2)
        low, high = _accuracy_limits(report)
        for i, model in enumerate(models):
            for j, kind in enumerate(KINDS):
                ax = axes[i][j]
                _accuracy_panel(ax, report, model, kind, low, high)
                n = _panel_n(report, model, kind)
                ax.set_title(f"{model_label(model)} · {KIND_LABELS[kind]}" + (f" (n = {n:,})" if n else ""),
                             loc="left", fontsize=8.5, fontweight="bold", pad=6)
                if j:
                    ax.set_yticklabels([])
                if i == len(models) - 1:
                    ax.set_xlabel("First-decision accuracy (%), 95% Wilson CI")
        if titles:
            _titles(fig, "Accuracy by harness configuration",
                    "Gray band: the same model's baseline (95% CI). Labels: accuracy, then the paired change "
                    "from baseline in points, starred when the Holm-adjusted McNemar p < 0.05.",
                    top=1 - 0.12 / fig.get_figheight())
        return _save(fig, stem)


def _panel_n(report, model, kind) -> Optional[int]:
    numbers = report["results"][model]["baseline"].get(kind)
    return numbers["accuracy"]["n"] if numbers else None


def _accuracy_panel(ax, report, model, kind, low, high) -> None:
    configs = CONFIG_ORDER
    y = {config: k for k, config in enumerate(configs)}
    base = report["results"][model]["baseline"].get(kind)
    if base:
        b = base["accuracy"]
        ax.axvspan(b["ci_low"], b["ci_high"], color=BASELINE_BAND, linewidth=0, zorder=0)
        ax.axvline(b["rate"], color=INK_MUTED, linewidth=0.8, zorder=1)
    for config in configs:
        numbers = report["results"][model][config].get(kind)
        yy = y[config]
        if not numbers or numbers["accuracy"]["rate"] is None:
            ax.text(low + 0.01 * (high - low), yy, "missing", va="center", ha="left", fontsize=6.5,
                    color=INK_MUTED, style="italic")
            continue
        p = numbers["accuracy"]
        color = CONFIG_COLORS[config]
        ax.plot([p["ci_low"], p["ci_high"]], [yy, yy], color=color, linewidth=2, solid_capstyle="round", zorder=2)
        ax.plot([p["rate"]], [yy], marker="o", markersize=6.5, color=color, markeredgecolor=SURFACE,
                markeredgewidth=1.2, zorder=3)
        label = _pct(p["rate"])
        c = numbers.get("comparison")
        if c and c["difference"] is not None:
            star = "*" if c["p_holm"] is not None and c["p_holm"] < 0.05 else ""
            label += f"  {100 * c['difference']:+.1f}{star}"
        ax.annotate(label, (max(p["ci_high"], p["rate"]), yy), xytext=(6, 0), textcoords="offset points",
                    va="center", ha="left", fontsize=6.8, color=INK if c else INK_2)
    ax.set_yticks(range(len(configs)))
    ax.set_yticklabels([config_label(c) for c in configs])
    ax.set_ylim(len(configs) - 0.4, -0.6)
    ax.set_xlim(low, high)
    _percent_ticks(ax, low, high)
    _grid_x(ax)


# --- 2. covered vs uncovered --------------------------------------------------------------


def coverage_chart(report: dict[str, Any], stem: Path, titles: bool = True) -> Optional[list[Path]]:
    """Dumbbell per config: covered (filled) vs uncovered (open) first-decision accuracy."""
    if not any((report["results"][m][c].get(k) or {}).get("coverage")
               for m in report["models"] for c in CONFIG_ORDER for k in KINDS):
        return None
    with plt.rc_context(STYLE):
        fig, axes, models = _panel_grid(report, 1.75, 0.62 if titles else 0.2, bottom_room=0.75)
        for i, model in enumerate(models):
            for j, kind in enumerate(KINDS):
                ax = axes[i][j]
                _coverage_panel(ax, report, model, kind)
                ax.set_title(f"{model_label(model)} · {KIND_LABELS[kind]}", loc="left", fontsize=8.5,
                             fontweight="bold", pad=6)
                if j:
                    ax.set_yticklabels([])
                if i == len(models) - 1:
                    ax.set_xlabel("First-decision accuracy (%)")
        handles = [Line2D([], [], marker="o", linestyle="", markersize=6, color=INK_2, label="Covered cells"),
                   Line2D([], [], marker="o", linestyle="", markersize=6, markerfacecolor=SURFACE,
                          markeredgecolor=INK_2, markeredgewidth=1.4, label="Uncovered cells")]
        top = 1 - (0.12 if titles else 0.05) / fig.get_figheight()
        if titles:
            _titles(fig, "Covered vs uncovered cells",
                    "Covered: a strategy-information principle applies to the cell. Descriptive only (not tested).",
                    top=top)
        fig.legend(handles=handles, loc="lower center", bbox_to_anchor=(0.58, 0.0), ncol=2,
                   handletextpad=0.3, columnspacing=1.6)
        return _save(fig, stem)


def _coverage_panel(ax, report, model, kind) -> None:
    configs = CONFIG_ORDER
    for k, config in enumerate(configs):
        numbers = report["results"][model][config].get(kind)
        cov = (numbers or {}).get("coverage")
        if not cov:
            ax.text(0.01, k, "missing", va="center", ha="left", fontsize=6.5, color=INK_MUTED, style="italic")
            continue
        color = CONFIG_COLORS[config]
        cv, un = cov["covered"]["rate"], cov["uncovered"]["rate"]
        if cv is not None and un is not None:
            ax.plot([cv, un], [k, k], color=color, linewidth=1.6, alpha=0.55, solid_capstyle="round", zorder=2)
        if un is not None:
            ax.plot([un], [k], marker="o", markersize=6.5, markerfacecolor=SURFACE, markeredgecolor=color,
                    markeredgewidth=1.6, zorder=3)
        if cv is not None:
            ax.plot([cv], [k], marker="o", markersize=6.5, color=color, markeredgecolor=SURFACE,
                    markeredgewidth=1.0, zorder=4)
        values = [v for v in (cv, un) if v is not None]
        if values:
            lo, hi = min(values), max(values)
            for value, anchor in ((lo, "right"), (hi, "left")) if len(values) == 2 and hi - lo > 1e-9 else ((hi, "left"),):
                ax.annotate(_pct(value), (value, k), xytext=(-7 if anchor == "right" else 7, 0),
                            textcoords="offset points", va="center", ha=anchor, fontsize=6.5, color=INK_2)
    ax.set_yticks(range(len(configs)))
    ax.set_yticklabels([config_label(c) for c in configs])
    ax.set_ylim(len(configs) - 0.4, -0.6)
    ax.set_xlim(-0.08, 1.08)
    ax.set_xticks([0, 0.25, 0.5, 0.75, 1.0])
    ax.set_xticklabels(["0", "25", "50", "75", "100"])
    _grid_x(ax)


# --- 3. self-evaluation flips -----------------------------------------------------------


def flips_chart(report: dict[str, Any], stem: Path, titles: bool = True) -> Optional[list[Path]]:
    """Diverging bars per self-evaluation config: breaks to the left, fixes to the right."""
    rows = flip_rows(report)
    if not rows:
        return None
    with plt.rc_context(STYLE):
        top_room = 0.72 if titles else 0.3
        bottom_room = 0.7
        height = 0.55 * len(rows) + bottom_room + top_room
        fig, axes = plt.subplots(1, 2, figsize=(TEXT_WIDTH_IN, height), squeeze=False,
                                 gridspec_kw={"wspace": 0.1})
        fig.subplots_adjust(left=0.24, right=0.99, top=1 - top_room / height, bottom=bottom_room / height)
        for j, kind in enumerate(KINDS):
            ax = axes[0][j]
            extent = max([max(f[kind]["fixes"], f[kind]["breaks"]) for _, _, f in rows if f[kind]] + [1])
            _flips_panel(ax, rows, kind, extent)
            ax.set_title(KIND_LABELS[kind], loc="left", fontsize=8.5, fontweight="bold", pad=6)
            if j:
                ax.set_yticklabels([])
        top = 1 - (0.12 if titles else 0.05) / height
        if titles:
            _titles(fig, "What self-evaluation changes",
                    "Flips of the first decision after the re-check. Fix: wrong to right; break: right to wrong. "
                    "Under each bar: net change, wrong-to-wrong flips, invalid second replies.", top=top)
        handles = [Patch(facecolor=INK_2, label="Fixes (wrong → right)"),
                   Patch(facecolor=SURFACE, edgecolor=INK_2, hatch="//////", linewidth=0.8,
                         label="Breaks (right → wrong)")]
        fig.legend(handles=handles, loc="lower center", bbox_to_anchor=(0.615, 0.0), ncol=2,
                   handletextpad=0.4, columnspacing=1.6)
        return _save(fig, stem)


def _flips_panel(ax, rows, kind, extent) -> None:
    labels = []
    for k, (model, config, flips) in enumerate(rows):
        labels.append(f"{model_label(model)}  {config_label(config)}")
        f = flips[kind]
        if f is None:
            ax.text(0, k, "missing", ha="center", va="center", fontsize=6.5, color=INK_MUTED, style="italic")
            continue
        color = CONFIG_COLORS[config]
        yb = k - 0.12
        ax.barh(yb, f["fixes"], height=0.44, color=color, edgecolor=SURFACE, linewidth=1.0, zorder=2)
        ax.barh(yb, -f["breaks"], height=0.44, color=SURFACE, edgecolor=color, hatch="//////", linewidth=0.9,
                zorder=2)
        pad = 0.03 * extent
        ax.text(f["fixes"] + pad, yb, str(f["fixes"]), va="center", ha="left", fontsize=7, color=INK)
        ax.text(-f["breaks"] - pad, yb, str(f["breaks"]), va="center", ha="right", fontsize=7, color=INK)
        net = f["fixes"] - f["breaks"]
        ax.text(0, k + 0.3, f"net {net:+d} · wrong→wrong {f['neutral']} · invalid {f['second_invalid']}",
                va="center", ha="center", fontsize=6, color=INK_2, zorder=4,
                bbox=dict(boxstyle="square,pad=0.15", facecolor=SURFACE, edgecolor="none"))
    ax.axvline(0, color=INK_2, linewidth=0.8, zorder=3)
    ax.set_yticks([k - 0.12 for k in range(len(rows))])
    ax.set_yticklabels(labels)
    ax.set_ylim(len(rows) - 0.4, -0.6)
    ax.set_xlim(-1.3 * extent, 1.3 * extent)
    ticks = [t for t in ax.get_xticks() if -1.3 * extent <= t <= 1.3 * extent and float(t).is_integer()]
    ax.set_xticks(ticks)
    ax.set_xticklabels([str(abs(int(t))) for t in ticks])
    ax.set_xlabel("Decisions (breaks ←  |  → fixes)")
    _grid_x(ax)


# --- 4. best config vs baseline on the scenario grid --------------------------------------


def heatmap_chart(report: dict[str, Any], model: str, stem: Path, titles: bool = True) -> Optional[list[Path]]:
    """Every scenario cell: did the best config fix, break, or match the baseline's decision?"""
    grid = report["heatmaps"].get(model)
    if not grid:
        return None
    rows = grid["rows"]
    cells = {(c["row"], c["upcard"]): c for c in grid["cells"]}
    groups = [label.split()[0] if " " in label else "pair" for label in rows]
    gap = 0.45
    ys, y = [], 0.0
    for i, group in enumerate(groups):
        if i and group != groups[i - 1]:
            y += gap
        ys.append(y)
        y += 1
    total = y

    with plt.rc_context(STYLE):
        top_room = 1.05 if titles else 0.55
        cell_h = 0.165
        height = cell_h * total + top_room + 0.55
        fig, ax = plt.subplots(figsize=(TEXT_WIDTH_IN, height))
        fig.subplots_adjust(left=0.1, right=0.99, top=1 - top_room / height, bottom=0.55 / height)
        for i, label in enumerate(rows):
            for j, upcard in enumerate(UPCARDS):
                cell = cells.get((label, upcard))
                fill = EMPTY_CELL if cell is None else CATEGORY_COLORS[cell["category"]]
                ax.add_patch(Rectangle((j + 0.04, ys[i] + 0.06), 0.92, 0.88, facecolor=fill, linewidth=0))
                if cell is not None:
                    dark = CATEGORY_DARK[cell["category"]]
                    ax.text(j + 0.5, ys[i] + 0.5, _cell_text(cell), ha="center", va="center", fontsize=6,
                            color=SURFACE if dark else INK, fontweight="bold" if dark else "normal")
        ax.set_xlim(0, len(UPCARDS))
        ax.set_ylim(total, 0)
        ax.set_xticks([j + 0.5 for j in range(len(UPCARDS))])
        ax.set_xticklabels(UPCARDS, fontsize=7.5)
        ax.xaxis.tick_top()
        ax.set_xlabel("Dealer upcard", labelpad=6)
        ax.xaxis.set_label_position("top")
        ax.set_yticks([yy + 0.5 for yy in ys])
        ax.set_yticklabels([label if " " in label else f"pair {label}" for label in rows], fontsize=6.5)
        for spine in ax.spines.values():
            spine.set_visible(False)

        counts = grid["counts"]
        handles = [Patch(facecolor=CATEGORY_COLORS[c], label=f"{CATEGORY_LABELS[c]}: {counts[c]}")
                   for c in (FIXED, BROKE, BOTH_RIGHT, BOTH_WRONG)]
        ax.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, -0.004), ncol=4, fontsize=6.5,
                  handlelength=1.1, handleheight=1.1, columnspacing=1.3, handletextpad=0.4)
        if titles:
            best = config_label(grid["config"])
            _titles(fig, f"{model_label(model)}: {best} vs baseline, cell by cell",
                    f"{best} is this model's best configuration by scenario accuracy. Changed cells show "
                    "baseline → config action; others show the shared action, with the basic-strategy "
                    "action in brackets when both are wrong. H hit, S stand, D double, P split, inv invalid.",
                    top=1 - 0.12 / height)
        return _save(fig, stem)


def _cell_text(cell: dict[str, Any]) -> str:
    base, conf = ACTION_LETTERS[cell["baseline_action"]], ACTION_LETTERS[cell["config_action"]]
    if base != conf:
        return f"{base}→{conf}"
    if cell["category"] == BOTH_WRONG:
        return f"{conf} ({ACTION_LETTERS[cell['optimal_action']]})"
    return conf


# --- all charts ---------------------------------------------------------------------------


def write_charts(report: dict[str, Any], out_dir: Path, titles: bool = True) -> dict[str, list[str]]:
    """Draw every chart into out_dir/charts; {chart title: [file paths relative to out_dir]}."""
    charts_dir = Path(out_dir) / "charts"
    made: dict[str, Optional[list[Path]]] = {
        "Accuracy by configuration": accuracy_chart(report, charts_dir / "accuracy_by_config", titles),
        "Covered vs uncovered cells": coverage_chart(report, charts_dir / "coverage_by_config", titles),
        "Self-evaluation fixes and breaks": flips_chart(report, charts_dir / "self_eval_flips", titles),
    }
    for model in report["models"]:
        slug = model.replace(":", "-")
        made[f"{model_label(model)}: best config vs baseline (scenario cells)"] = heatmap_chart(
            report, model, charts_dir / f"scenario_heatmap_{slug}", titles)
    return {title: [str(p.relative_to(out_dir)) for p in paths] for title, paths in made.items() if paths}
