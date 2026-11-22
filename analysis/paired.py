"""Paired statistics for one harness configuration against the same model's baseline.

Pairing (see docs/ablation-plan.md, "Statistics"):
- Natural runs pair on hand_number, using only the FIRST decision of each hand
  (decision_index 0). The same run seed deals the same cards, so those first
  decisions face identical spots; later decisions depend on earlier actions and
  are not paired.
- Scenario runs pair on scenario_id, using only the graded cell (is_scenario_cell).
- Natural and scenario runs are never paired with each other or pooled.

A hand where only one side has a first decision is dropped and counted
(`dropped`). A hand where neither side decided (a blackjack) is counted as
`no_decision`; that is expected. Runs whose model, run seed, hand set or
scenario set differ, whose stack differs (model digest, prompt, parser, Ollama
version or options, GPUs), or whose paired first decisions show different cards,
cannot be paired and raise PairingError. A field missing on either side is
skipped, so older run folders still pair.

Statistics per comparison:
- Discordant counts b (baseline correct, config wrong) and c (baseline wrong,
  config correct). Correctness is the row's top-level `correct`, which for a
  self-evaluation run is the graded final answer.
- Exact McNemar p-value: two-sided binomial test of b vs c with p = 1/2.
- Accuracy difference (config - baseline) with Newcombe's hybrid score interval
  for paired proportions (Newcombe 1998, method 10): Wilson intervals for each
  marginal accuracy, combined with the phi correlation of the 2x2 table. It
  stays inside [-1, 1] and behaves at small n and near 0 or 1, unlike Wald.
- Holm-Bonferroni adjustment (holm_adjust), applied by the caller per family.
- EV-loss change: mean EV loss per paired first decision (analysis/ev_loss.py),
  config minus baseline, with a normal-approximation CI on the per-pair differences.

Descriptive only (no test): accuracy of later decisions, accuracy on covered vs
uncovered cells (with an injected classifier), and self-evaluation flip stats.
"""

import math
from dataclasses import dataclass
from typing import Any, Callable

from analysis.ev_loss import decision_ev
from analysis.loading import Run
from analysis.metrics import Row, accuracy, is_scenario_run
from analysis.stats import MeanCI, Proportion, mean_with_ci, wilson_interval

NATURAL = "natural"
SCENARIO = "scenario"


class PairingError(ValueError):
    """Two runs that cannot be paired decision by decision."""


# --- basic statistics -----------------------------------------------------------------


def exact_mcnemar_p(b: int, c: int) -> float:
    """Two-sided exact McNemar p-value: binomial test of min(b, c) out of b + c at p = 1/2."""
    n = b + c
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, k) for k in range(min(b, c) + 1)) / 2**n
    return min(1.0, 2 * tail)


def holm_adjust(p_values: list[float]) -> list[float]:
    """Holm-Bonferroni adjusted p-values, returned in the input order."""
    m = len(p_values)
    order = sorted(range(m), key=lambda i: p_values[i])
    adjusted = [0.0] * m
    running = 0.0
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (m - rank) * p_values[i]))
        adjusted[i] = running
    return adjusted


def newcombe_paired_diff_ci(a: int, b: int, c: int, d: int) -> tuple[float, float]:
    """95% CI for (config accuracy - baseline accuracy) from a paired 2x2 table.

    a = both correct, b = baseline only, c = config only, d = both wrong.
    Newcombe (1998) method 10 (hybrid score, no continuity correction).
    """
    n = a + b + c + d
    if n == 0:
        return math.nan, math.nan
    p1, p2 = (a + c) / n, (a + b) / n  # config, baseline
    l1, u1 = wilson_interval(a + c, n)
    l2, u2 = wilson_interval(a + b, n)
    denominator = (a + b) * (c + d) * (a + c) * (b + d)
    phi = (a * d - b * c) / math.sqrt(denominator) if denominator else 0.0
    diff = p1 - p2
    lower = (p1 - l1) ** 2 - 2 * phi * (p1 - l1) * (u2 - p2) + (u2 - p2) ** 2
    upper = (u1 - p1) ** 2 - 2 * phi * (u1 - p1) * (p2 - l2) + (p2 - l2) ** 2
    return max(-1.0, diff - math.sqrt(max(lower, 0.0))), min(1.0, diff + math.sqrt(max(upper, 0.0)))


# --- run identity and first decisions -----------------------------------------------


def run_kind(run: Run) -> str:
    """"scenario" or "natural"."""
    return SCENARIO if is_scenario_run(run) else NATURAL


def config_name(run: Run) -> str:
    """The harness config name from metadata (a string, or a dict with "name"); else the folder name."""
    value = run.metadata.get("harness_config")
    if isinstance(value, dict):
        value = value.get("name")
    return value or run.name


def _is_first(row: Row, kind: str) -> bool:
    if kind == SCENARIO:
        return bool(row.get("is_scenario_cell"))
    return row.get("decision_index", 0) == 0


def first_decisions(run: Run) -> dict[Any, Row]:
    """{pairing key: first decision}. Key is hand_number (natural) or scenario_id (scenario)."""
    kind = run_kind(run)
    firsts: dict[Any, Row] = {}
    for row in run.decisions:
        if not _is_first(row, kind):
            continue
        key = row.get("scenario_id", row["hand_number"]) if kind == SCENARIO else row["hand_number"]
        if key in firsts:
            raise PairingError(f"{run.name}: two first decisions for {key!r}")
        firsts[key] = row
    return firsts


def later_decisions(run: Run) -> Proportion:
    """Accuracy of every decision that is not a hand's first (descriptive; unpaired)."""
    kind = run_kind(run)
    return accuracy([row for row in run.decisions if not _is_first(row, kind)])


def _hand_keys(run: Run) -> set[Any]:
    """Every pairable unit of the run, including hands with no decision."""
    if run_kind(run) == SCENARIO:
        return {hand.get("scenario_id", hand["hand_number"]) for hand in run.hands} | set(first_decisions(run))
    return {hand["hand_number"] for hand in run.hands}


# --- pairing ------------------------------------------------------------------------


@dataclass(frozen=True)
class Pair:
    key: Any
    baseline: Row
    config: Row


@dataclass
class PairedRuns:
    kind: str
    pairs: list[Pair]
    dropped: int  # units where only one side has a first decision
    no_decision: int  # units where neither side has one (natural blackjacks)


def _check_same(baseline: Run, config: Run, key: str, label: str) -> None:
    left, right = baseline.metadata.get(key), config.metadata.get(key)
    if left is not None and right is not None and left != right:
        raise PairingError(f"cannot pair {baseline.name} with {config.name}: {label} differs ({left!r} vs {right!r})")


# Software/hardware stack that must match for two temperature-0 runs to be comparable
# (metadata key, label). Per-job fields (hostname, slurm_job_id, timestamps) are not compared.
STACK_FIELDS = [
    ("model_digest", "model digest"),
    ("prompt_version", "prompt version"),
    ("parser_version", "parser version"),
    ("ollama_version", "Ollama version"),
    ("ollama_options", "Ollama options"),
]


def _gpu_sets(run: Run) -> set[tuple[str, ...]] | None:
    """Every GPU list the run was played on (top level plus each session); None if none recorded."""
    sources = [run.metadata] + list(run.metadata.get("sessions") or [])
    found = {tuple(s["gpus"]) for s in sources if s.get("gpus")}
    return found or None


def _check_same_gpus(baseline: Run, config: Run) -> None:
    left, right = _gpu_sets(baseline), _gpu_sets(config)
    if left is not None and right is not None and left != right:
        raise PairingError(f"cannot pair {baseline.name} with {config.name}: GPUs differ "
                           f"({sorted(left)!r} vs {sorted(right)!r})")


def pair_runs(baseline: Run, config: Run) -> PairedRuns:
    """Pair two runs' first decisions; raise PairingError if the runs can't be paired."""
    kinds = run_kind(baseline), run_kind(config)
    if kinds[0] != kinds[1]:
        raise PairingError(f"cannot pair a {kinds[0]} run ({baseline.name}) with a {kinds[1]} run ({config.name}); "
                           "natural and scenario runs are analysed separately")
    kind = kinds[0]
    _check_same(baseline, config, "model", "model")
    _check_same(baseline, config, "run_seed", "run seed")
    if kind == SCENARIO:
        _check_same(baseline, config, "scenario_set_version", "scenario set version")
    for key, label in STACK_FIELDS:
        _check_same(baseline, config, key, label)
    _check_same_gpus(baseline, config)

    keys_base, keys_conf = _hand_keys(baseline), _hand_keys(config)
    if keys_base != keys_conf:
        what = "scenario cells" if kind == SCENARIO else "hand numbers"
        raise PairingError(f"cannot pair {baseline.name} ({len(keys_base)} hands) with {config.name} "
                           f"({len(keys_conf)} hands): the {what} differ")

    first_base, first_conf = first_decisions(baseline), first_decisions(config)
    pairs, dropped, no_decision = [], 0, 0
    for key in sorted(keys_base, key=lambda k: (str(type(k)), k)):
        row_b, row_c = first_base.get(key), first_conf.get(key)
        if row_b is None and row_c is None:
            no_decision += 1
            continue
        if row_b is None or row_c is None:
            dropped += 1
            continue
        if (row_b["player_cards"], row_b["dealer_upcard"]) != (row_c["player_cards"], row_c["dealer_upcard"]):
            raise PairingError(f"{key!r}: first decisions saw different cards ({row_b['player_cards']} vs "
                               f"{row_b['dealer_upcard']} and {row_c['player_cards']} vs {row_c['dealer_upcard']}); "
                               "the runs were not dealt the same hands")
        pairs.append(Pair(key, row_b, row_c))
    return PairedRuns(kind, pairs, dropped, no_decision)


# --- one comparison -----------------------------------------------------------------


@dataclass
class Comparison:
    """One config against the same model's baseline, on paired first decisions."""

    kind: str
    model: str
    baseline_name: str
    config_name: str
    a: int  # both correct
    b: int  # baseline correct, config wrong
    c: int  # baseline wrong, config correct
    d: int  # both wrong
    dropped: int
    no_decision: int
    baseline_invalid: int
    config_invalid: int
    baseline_ev_loss: float  # mean EV loss per paired first decision
    config_ev_loss: float
    ev_loss_diff: MeanCI  # per-pair (config - baseline) EV loss
    p_value: float
    ci_low: float
    ci_high: float
    p_holm: float | None = None  # filled by the caller across a family

    @property
    def n(self) -> int:
        return self.a + self.b + self.c + self.d

    @property
    def baseline_accuracy(self) -> Proportion:
        return Proportion(self.a + self.b, self.n)

    @property
    def config_accuracy(self) -> Proportion:
        return Proportion(self.a + self.c, self.n)

    @property
    def difference(self) -> float:
        return (self.c - self.b) / self.n if self.n else math.nan

    @property
    def ev_loss_change(self) -> float:
        return self.config_ev_loss - self.baseline_ev_loss


def compare_to_baseline(baseline: Run, config: Run) -> Comparison:
    paired = pair_runs(baseline, config)
    counts = {"a": 0, "b": 0, "c": 0, "d": 0}
    for pair in paired.pairs:
        base_ok, conf_ok = bool(pair.baseline["correct"]), bool(pair.config["correct"])
        counts["a" if base_ok and conf_ok else "b" if base_ok else "c" if conf_ok else "d"] += 1
    loss_base = [decision_ev(p.baseline).loss for p in paired.pairs]
    loss_conf = [decision_ev(p.config).loss for p in paired.pairs]
    mean = lambda values: sum(values) / len(values) if values else math.nan  # noqa: E731
    low, high = newcombe_paired_diff_ci(**counts)
    return Comparison(
        kind=paired.kind,
        model=config.metadata.get("model") or baseline.metadata.get("model") or "?",
        baseline_name=config_name(baseline),
        config_name=config_name(config),
        **counts,
        dropped=paired.dropped,
        no_decision=paired.no_decision,
        baseline_invalid=sum(1 for p in paired.pairs if p.baseline["invalid"]),
        config_invalid=sum(1 for p in paired.pairs if p.config["invalid"]),
        baseline_ev_loss=mean(loss_base),
        config_ev_loss=mean(loss_conf),
        ev_loss_diff=mean_with_ci([lc - lb for lb, lc in zip(loss_base, loss_conf)]),
        p_value=exact_mcnemar_p(counts["b"], counts["c"]),
        ci_low=low,
        ci_high=high,
    )


# --- descriptive breakdowns ---------------------------------------------------------


Classifier = Callable[[Row], bool]


def accuracy_by_coverage(rows: list[Row], classifier: Classifier) -> tuple[Proportion, Proportion]:
    """(covered accuracy, uncovered accuracy). classifier(row) is True for a covered cell."""
    covered = [row for row in rows if classifier(row)]
    uncovered = [row for row in rows if not classifier(row)]
    return accuracy(covered), accuracy(uncovered)


@dataclass
class FlipStats:
    """Self-evaluation flips over rows carrying a `self_eval` dict.

    Expected self_eval keys: first_action, first_valid, first_correct,
    second_action, second_valid, final_action, flipped (plus raw replies).
    Final correctness is the row's top-level `correct` (the graded answer).
    """

    n: int = 0
    flips: int = 0
    fixes: int = 0  # first incorrect -> final correct
    breaks: int = 0  # first correct -> final incorrect
    neutral: int = 0  # flipped, wrong -> wrong
    second_invalid: int = 0
    first_correct: int = 0
    final_correct: int = 0

    @property
    def first_accuracy(self) -> Proportion:
        return Proportion(self.first_correct, self.n)

    @property
    def final_accuracy(self) -> Proportion:
        return Proportion(self.final_correct, self.n)


def flip_stats(rows: list[Row]) -> FlipStats:
    stats = FlipStats()
    for row in rows:
        info = row.get("self_eval")
        if not isinstance(info, dict):
            continue
        stats.n += 1
        first_ok, final_ok = bool(info.get("first_correct")), bool(row["correct"])
        stats.first_correct += first_ok
        stats.final_correct += final_ok
        if not info.get("second_valid", True):
            stats.second_invalid += 1
        flipped = info.get("flipped")
        if flipped is None:
            flipped = info.get("first_action") != info.get("final_action")
        if not flipped:
            continue
        stats.flips += 1
        if not first_ok and final_ok:
            stats.fixes += 1
        elif first_ok and not final_ok:
            stats.breaks += 1
        elif not first_ok and not final_ok:
            stats.neutral += 1
    return stats
