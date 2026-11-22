"""PNG figures for the paper (300 dpi, sized for an ACM two-column layout).

Single-column figures are 3.33 in wide. The heatmap has 34+ rows, so it is drawn
for the full text width (7 in, a LaTeX figure*) to keep its cell labels readable. Colors come from a colorblind-safe palette: blue for the model and for
sequential color scales, orange for basic strategy.
"""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # draw to files only; no window needed

import matplotlib.pyplot as plt  # noqa: E402  (must come after matplotlib.use)
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402

from analysis.ev_loss import ev_loss_grid  # noqa: E402
from analysis.metrics import (  # noqa: E402
    ACTIONS,
    CHOSEN_COLUMNS,
    UPCARDS,
    Row,
    RunSummary,
    accuracy_grid,
    chosen_action,
    graded_rows,
    heatmap_row_label,
    heatmap_row_labels,
    upcard_label,
)

DPI = 300
COLUMN_WIDTH_IN = 3.33
TEXT_WIDTH_IN = 7.0
MODEL_COLOR = "#2a78d6"  # blue
STRATEGY_COLOR = "#eb6834"  # orange
EMPTY_COLOR = "#ededeb"  # grey for heatmap cells with no decisions
CORRECT_FILL = "#86b6ef"  # scenario heatmap: light blue = correct
WRONG_FILL = "#f4b48f"  # scenario heatmap: light orange = incorrect
TEXT_COLOR = "#0b0b0b"
MUTED_TEXT = "#52514e"
GRID_COLOR = "#d9d9d6"

# Sequential one-hue blue ramp, light (low) to dark (high).
BLUES = LinearSegmentedColormap.from_list("blues", ["#b7d3f6", "#86b6ef", "#3987e5", "#1c5cab", "#0d366b"])

plt.rcParams.update({
    "font.size": 8,
    "axes.titlesize": 8,
    "axes.labelsize": 8,
    "xtick.labelsize": 7,
    "ytick.labelsize": 7,
    "legend.fontsize": 7,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.edgecolor": MUTED_TEXT,
    "axes.labelcolor": TEXT_COLOR,
    "xtick.color": MUTED_TEXT,
    "ytick.color": MUTED_TEXT,
    "savefig.dpi": DPI,
    "savefig.bbox": "tight",
})


def _save(fig, path: Path) -> Path:
    fig.savefig(path)
    plt.close(fig)
    return path


def _percent_axis(ax, label: str = "Decision accuracy (%)") -> None:
    """0-100% y axis with a light horizontal grid behind the bars."""
    ax.set_ylim(0, 1.12)  # headroom for the n labels above 100%
    ax.set_yticks([0, 0.25, 0.5, 0.75, 1.0])
    ax.set_yticklabels(["0", "25", "50", "75", "100"])
    ax.set_ylabel(label)
    ax.yaxis.grid(True, color=GRID_COLOR, linewidth=0.5)
    ax.set_axisbelow(True)


def _accuracy_bars(ax, labels, proportions, color=MODEL_COLOR) -> None:
    """Bars of accuracy with Wilson 95% CI whiskers and an n label above each bar."""
    positions = range(len(labels))
    rates = [p.rate if p.n else 0 for p in proportions]
    lower = [p.rate - p.low if p.n else 0 for p in proportions]
    upper = [p.high - p.rate if p.n else 0 for p in proportions]
    ax.bar(positions, rates, width=0.6, color=color)
    ax.errorbar(positions, rates, yerr=[lower, upper], fmt="none", ecolor=TEXT_COLOR, elinewidth=0.8, capsize=3)
    for x, p in zip(positions, proportions):
        text = f"{p.rate:.0%}\nn={p.n}" if p.n else "n=0"
        ax.text(x, (p.high if p.n else 0) + 0.02, text, ha="center", va="bottom", fontsize=6.5, color=TEXT_COLOR)
    ax.set_xticks(list(positions))
    ax.set_xticklabels(labels)


def accuracy_by_hand_type_chart(summary: RunSummary, path: Path) -> Path:
    """Figure 1: accuracy for hard / soft / pair decisions with 95% CIs."""
    fig, ax = plt.subplots(figsize=(COLUMN_WIDTH_IN, 2.3))
    groups = summary.by_hand_type
    _accuracy_bars(ax, [g.label.capitalize() for g in groups], [g.result for g in groups])
    _percent_axis(ax)
    ax.set_xlabel("Player hand type")
    return _save(fig, path)


def confusion_matrix_chart(summary: RunSummary, path: Path) -> Path:
    """Figure 2: basic-strategy action (rows) vs the model's chosen action (columns)."""
    matrix = [[summary.confusion[optimal][chosen] for chosen in CHOSEN_COLUMNS] for optimal in ACTIONS]
    biggest = max(max(row) for row in matrix) or 1

    fig, ax = plt.subplots(figsize=(COLUMN_WIDTH_IN, 2.5))
    ax.imshow(matrix, cmap=BLUES, vmin=0, vmax=biggest, aspect="auto")
    for i, row in enumerate(matrix):
        for j, count in enumerate(row):
            dark = count > biggest * 0.55
            ax.text(j, i, str(count), ha="center", va="center", fontsize=8,
                    color="white" if dark else TEXT_COLOR, fontweight="bold" if i == j else "normal")
    # Outline the diagonal (correct decisions).
    for i in range(len(ACTIONS)):
        ax.add_patch(plt.Rectangle((i - 0.5, i - 0.5), 1, 1, fill=False, edgecolor=TEXT_COLOR, linewidth=1.2))
    ax.set_xticks(range(len(CHOSEN_COLUMNS)))
    ax.set_xticklabels([c.capitalize() for c in CHOSEN_COLUMNS])
    ax.set_yticks(range(len(ACTIONS)))
    ax.set_yticklabels([a.capitalize() for a in ACTIONS])
    ax.set_xlabel("Action chosen by the model")
    ax.set_ylabel("Basic strategy action")
    ax.tick_params(length=0)
    for spine in ax.spines.values():
        spine.set_visible(False)
    return _save(fig, path)


def _grid_heatmap(row_labels, cells, color_of, text_of, footer: str, path: Path) -> Path:
    """Player hand (rows) x dealer upcard (columns) grid; cells maps (row, upcard) -> value, grey = missing.

    color_of(value) gives (fill color, dark?) and text_of(value) the cell label.
    """
    fig, ax = plt.subplots(figsize=(TEXT_WIDTH_IN, 0.17 * len(row_labels) + 0.6))
    for i, row_label in enumerate(row_labels):
        for j, upcard in enumerate(UPCARDS):
            cell = cells.get((row_label, upcard))
            color, dark = (EMPTY_COLOR, False) if cell is None else color_of(cell)
            ax.add_patch(plt.Rectangle((j, i), 1, 1, facecolor=color, edgecolor="white", linewidth=0.8))
            if cell is not None:
                ax.text(j + 0.5, i + 0.5, text_of(cell), ha="center", va="center",
                        fontsize=6.5, color="white" if dark else TEXT_COLOR)

    # Separate the hard / soft / pair blocks with a thicker line.
    kinds = [label.split()[0] if " " in label else "pair" for label in row_labels]
    for i in range(1, len(kinds)):
        if kinds[i] != kinds[i - 1]:
            ax.axhline(i, color=TEXT_COLOR, linewidth=1.0)

    ax.set_xlim(0, len(UPCARDS))
    ax.set_ylim(len(row_labels), 0)  # first row at the top
    ax.set_xticks([j + 0.5 for j in range(len(UPCARDS))])
    ax.set_xticklabels(UPCARDS)
    ax.xaxis.tick_top()
    ax.xaxis.set_label_position("top")
    ax.set_yticks([i + 0.5 for i in range(len(row_labels))])
    ax.set_yticklabels([label if " " in label else f"pair {label}" for label in row_labels], fontsize=7)
    ax.set_xlabel("Dealer upcard")
    ax.set_ylabel("Player hand")
    ax.tick_params(length=0)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.text(0.5, -0.01, footer, transform=ax.transAxes, ha="center", va="top", fontsize=7, color=MUTED_TEXT)
    return _save(fig, path)


_ACTION_LETTERS = {"hit": "H", "stand": "S", "double": "D", "split": "P", "invalid": "inv"}


def scenario_cell_label(row: Row) -> str:
    """The model's action as a letter, plus the basic-strategy action in brackets when wrong: "D (S)"."""
    chosen = _ACTION_LETTERS[chosen_action(row)]
    return chosen if row["correct"] else f"{chosen} ({_ACTION_LETTERS[row['optimal_action']]})"


def heatmap_rows_for(summary: RunSummary) -> list[str]:
    """Heatmap rows: every standard chart row for a natural run; only the tested rows for a scenario run."""
    rows = graded_rows(summary.run)
    labels = heatmap_row_labels(rows)
    if not summary.is_scenario:
        return labels
    present = {heatmap_row_label(row) for row in rows}
    return [label for label in labels if label in present]


def _scenario_heatmap(summary: RunSummary, path: Path) -> Path:
    """One graded decision per cell: the model's action, blue if correct, orange (with the chart action) if not."""
    rows = graded_rows(summary.run)
    cells = {(heatmap_row_label(row), upcard_label(row["dealer_upcard"])): row for row in rows}
    k, n = summary.accuracy.k, summary.accuracy.n
    return _grid_heatmap(
        heatmap_rows_for(summary),
        cells,
        color_of=lambda row: (CORRECT_FILL if row["correct"] else WRONG_FILL, False),
        text_of=scenario_cell_label,
        footer=(f"Model's action (H hit, S stand, D double, P split, inv invalid). Blue: correct ({k}). "
                f"Orange: incorrect ({n - k}), basic-strategy action in brackets."),
        path=path,
    )


def accuracy_heatmap_chart(summary: RunSummary, path: Path) -> Path:
    """Figure 3: accuracy per player total x dealer upcard; grey = no decisions.

    Scenario runs have one graded decision per cell, so they show correct/incorrect instead.
    """
    if summary.is_scenario:
        return _scenario_heatmap(summary, path)
    rows = summary.run.decisions
    return _grid_heatmap(
        heatmap_row_labels(rows),
        accuracy_grid(rows),
        color_of=lambda cell: (BLUES(cell.rate), cell.rate > 0.55),
        text_of=lambda cell: f"{cell.rate:.0%} ({cell.n})",
        footer="Cell: accuracy (n decisions). Grey: no decisions.",
        path=path,
    )


def ev_loss_heatmap_chart(summary: RunSummary, path: Path) -> Path:
    """Mean EV loss per player total x dealer upcard (darker = costlier); grey = no decisions.

    The color scale runs from 0 to the run's largest cell mean (at least 0.1 units),
    and slightly negative cells (model beat the chart) are drawn as 0.
    """
    rows = graded_rows(summary.run)
    grid = ev_loss_grid(rows)
    top = max([0.1] + [cell.mean for cell in grid.values()])

    def color_of(cell):
        shade = max(cell.mean, 0) / top
        return BLUES(shade), shade > 0.55

    return _grid_heatmap(
        heatmap_rows_for(summary),
        grid,
        color_of=color_of,
        text_of=lambda cell: f"{cell.mean:.2f} ({cell.n})",
        footer=f"Cell: mean EV loss in units per 1-unit bet (n decisions); darkest = {top:.2f}. Grey: no decisions.",
        path=path,
    )


def action_frequency_chart(summary: RunSummary, path: Path) -> Path:
    """Figure 4: share of decisions per action, model vs basic strategy."""
    freq = summary.frequency
    total = sum(freq["model"].values()) or 1
    actions = ACTIONS + (["invalid"] if freq["model"]["invalid"] else [])
    width = 0.38

    fig, ax = plt.subplots(figsize=(COLUMN_WIDTH_IN, 2.3))
    for offset, key, color, name in [(-width / 2, "model", MODEL_COLOR, "Model"),
                                     (width / 2, "basic_strategy", STRATEGY_COLOR, "Basic strategy")]:
        counts = [freq[key][a] for a in actions]
        xs = [i + offset for i in range(len(actions))]
        ax.bar(xs, [c / total for c in counts], width=width - 0.03, color=color, label=name)
        for x, c in zip(xs, counts):
            ax.text(x, c / total + 0.015, str(c), ha="center", va="bottom", fontsize=6.5, color=TEXT_COLOR)
    ax.set_xticks(range(len(actions)))
    ax.set_xticklabels([a.capitalize() for a in actions])
    ax.set_ylim(0, 1.0)
    ax.set_yticks([0, 0.25, 0.5, 0.75, 1.0])
    ax.set_yticklabels(["0", "25", "50", "75", "100"])
    ax.set_ylabel(f"Share of decisions (%), n={total}")
    ax.set_xlabel("Action")
    ax.yaxis.grid(True, color=GRID_COLOR, linewidth=0.5)
    ax.set_axisbelow(True)
    ax.legend(frameon=False, loc="upper right")
    return _save(fig, path)


def comparison_accuracy_chart(summaries: list[RunSummary], path: Path) -> Path:
    """Accuracy with 95% CI for each run, labelled by run directory and prompt version."""
    labels = [f"{s.run.name}\n{s.run_type}, prompt: {s.run.prompt_version}" for s in summaries]
    fig, ax = plt.subplots(figsize=(max(COLUMN_WIDTH_IN, 1.1 * len(summaries) + 1), 2.4))
    _accuracy_bars(ax, labels, [s.accuracy for s in summaries])
    _percent_axis(ax)
    ax.set_xlabel("Run (run type, prompt version)")
    ax.tick_params(axis="x", labelsize=6)
    return _save(fig, path)


def write_run_charts(summary: RunSummary, out_dir: Path) -> list[Path]:
    """Write the per-run figures into out_dir and return their paths."""
    return [
        accuracy_by_hand_type_chart(summary, out_dir / "accuracy_by_hand_type.png"),
        confusion_matrix_chart(summary, out_dir / "confusion_matrix.png"),
        accuracy_heatmap_chart(summary, out_dir / "accuracy_heatmap.png"),
        action_frequency_chart(summary, out_dir / "action_frequency.png"),
        ev_loss_heatmap_chart(summary, out_dir / "ev_loss_heatmap.png"),
    ]
