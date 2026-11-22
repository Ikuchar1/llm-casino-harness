"""Strategy information: a short list of plain-English principles, never the full chart.

Each principle is stored twice: as the text the model sees, and as a rule that maps a
chart cell to the chart code it prescribes (H, S, Dh, Ds or P), or None when the
principle says nothing about that cell. The tests check every rule against
blackjack/strategy.py on every chart cell, so a principle is exactly true wherever
it applies.

Cells. A cell is the chart lookup key used by blackjack.strategy.chart_code: a pair
row when splitting is legal, otherwise the soft or hard total, against the dealer
upcard (J/Q/K = "10"). The scenario set is 330 of these cells (agent/scenarios.py).

Doubling. Principles are checked against the raw chart code, so a principle that
says "double, or hit if doubling is not allowed" must match a Dh cell exactly (and
"double, or stand" a Ds cell). principle_action turns the code into the action for
the legal actions at hand, the same way best_legal_action grades decisions.

Logged decisions. A decision is labelled by the cell its own state looks up in the
chart, whatever its number of cards: a three-card hard 11 is the hard 11 cell, where
the principle "double (or hit if doubling is not allowed)" means hit. A pair that can
no longer be split (after the one split) is its hard or soft total, as in the chart.
So a later decision is covered iff its total's cell is covered, and when it is the
principle's action equals the graded optimal action.
"""

from dataclasses import dataclass
from typing import Any, Callable, Iterable, Optional

from agent.scenarios import build_scenarios
from blackjack.cards import card_value
from blackjack.engine import DOUBLE, HIT, SPLIT, STAND
from blackjack.strategy import DEALER_UPCARDS, HARD_TOTALS, PAIRS, SOFT_TOTALS

# Bump if the principles' text or rules change; log it with the run.
STRATEGY_INFO_VERSION = "strategy-info-v1"

HEADING = (
    "Strategy principles (these cover many hands but not all of them). The hard and soft rules "
    "apply only when you are not holding a pair you can split; pairs have their own rules."
)


def _chart_key(rank: str) -> str:
    """A rank as the chart writes it: J/Q/K become "10"."""
    return "A" if rank == "A" else str(card_value(rank))


@dataclass(frozen=True)
class Cell:
    """One chart cell: kind "hard"/"soft" with an int total, or "pair" with a rank."""

    kind: str
    row: int | str
    dealer_upcard: str  # chart key: "2".."10" or "A"

    def __str__(self) -> str:
        return f"{self.kind}{self.row}_vs_{self.dealer_upcard}"

    @property
    def upcard_value(self) -> int:
        """The upcard as a number, with an ace counted as 11."""
        return 11 if self.dealer_upcard == "A" else int(self.dealer_upcard)


Rule = Callable[[Cell], Optional[str]]


@dataclass(frozen=True)
class Principle:
    text: str
    rule: Rule

    def code_for(self, cell: Cell) -> Optional[str]:
        """The chart code this principle prescribes for the cell, or None if it does not apply."""
        return self.rule(cell)


def _hard(cell: Cell, low: int, high: int) -> bool:
    return cell.kind == "hard" and low <= cell.row <= high


def _soft(cell: Cell, low: int, high: int) -> bool:
    return cell.kind == "soft" and low <= cell.row <= high


def _pair(cell: Cell, *ranks: str) -> bool:
    return cell.kind == "pair" and cell.row in ranks


def _split_aces_and_eights(cell: Cell) -> Optional[str]:
    return "P" if _pair(cell, "A", "8") else None


def _stand_hard_17_and_tens(cell: Cell) -> Optional[str]:
    return "S" if _hard(cell, 17, 21) or _pair(cell, "10") else None


def _hard_13_to_16(cell: Cell) -> Optional[str]:
    if not _hard(cell, 13, 16):
        return None
    return "S" if cell.upcard_value <= 6 else "H"


def _hard_12(cell: Cell) -> Optional[str]:
    if not _hard(cell, 12, 12):
        return None
    return "S" if 4 <= cell.upcard_value <= 6 else "H"


def _hit_hard_8_or_less(cell: Cell) -> Optional[str]:
    return "H" if _hard(cell, 2, 8) else None


def _hard_10_11_and_fives(cell: Cell) -> Optional[str]:
    if _hard(cell, 10, 11):
        total = cell.row
    elif _pair(cell, "5"):
        total = 10
    else:
        return None
    return "Dh" if total > cell.upcard_value else "H"


def _stand_soft_19(cell: Cell) -> Optional[str]:
    return "S" if _soft(cell, 19, 21) else None


def _hit_soft_17_vs_7_up(cell: Cell) -> Optional[str]:
    return "H" if _soft(cell, 12, 17) and cell.upcard_value >= 7 else None


PRINCIPLES: tuple[Principle, ...] = (
    Principle("Always split aces and 8s.", _split_aces_and_eights),
    Principle("Stand on hard 17 or more. Never split 10s: stand on any two 10-value cards.",
              _stand_hard_17_and_tens),
    Principle("With hard 13 to 16, stand against a dealer 2 to 6 and hit against a dealer 7 to ace.",
              _hard_13_to_16),
    Principle("With hard 12, stand against a dealer 4 to 6 and hit against a dealer 2, 3 or 7 to ace.",
              _hard_12),
    Principle("Always hit a hard 8 or less.", _hit_hard_8_or_less),
    Principle(
        "With hard 10 or 11, double (or hit if doubling is not allowed) when your total is higher than "
        "the dealer's upcard, counting the dealer's ace as 11; otherwise hit. Never split 5s: play a "
        "pair of 5s exactly like hard 10.",
        _hard_10_11_and_fives,
    ),
    Principle("Stand on soft 19 or more.", _stand_soft_19),
    Principle("With soft 17 or less, hit against a dealer 7 to ace.", _hit_soft_17_vs_7_up),
)


def principles_block() -> str:
    """The strategy information text for the prompt: a heading and a numbered list."""
    lines = [HEADING] + [f"{n}. {p.text}" for n, p in enumerate(PRINCIPLES, start=1)]
    return "\n".join(lines)


def covering_principles(cell: Cell) -> list[int]:
    """The 1-based numbers of the principles that apply to this cell."""
    return [n for n, p in enumerate(PRINCIPLES, start=1) if p.code_for(cell) is not None]


def principle_code(cell: Cell) -> Optional[str]:
    """The chart code the principles prescribe for the cell, or None if it is uncovered."""
    codes = {PRINCIPLES[n - 1].code_for(cell) for n in covering_principles(cell)}
    if len(codes) > 1:
        raise ValueError(f"Principles disagree on {cell}: {sorted(codes)}")
    return codes.pop() if codes else None


def is_covered(cell: Cell) -> bool:
    """True iff at least one principle applies to the cell (a covered cell)."""
    return principle_code(cell) is not None


def principle_action(cell: Cell, legal_actions: Iterable[str]) -> Optional[str]:
    """The action the principles prescribe, given what is legal now; None if uncovered."""
    code = principle_code(cell)
    if code is None:
        return None
    can_double = DOUBLE in legal_actions
    return {
        "H": HIT,
        "S": STAND,
        "P": SPLIT,
        "Dh": DOUBLE if can_double else HIT,
        "Ds": DOUBLE if can_double else STAND,
    }[code]


def chart_code_for_cell(cell: Cell) -> str:
    """Basic strategy's chart code for a cell."""
    column = DEALER_UPCARDS.index(cell.dealer_upcard)
    table = {"hard": HARD_TOTALS, "soft": SOFT_TOTALS, "pair": PAIRS}[cell.kind]
    return table[cell.row][column]


def scenario_cells() -> list[Cell]:
    """The 330 scenario-set cells, in scenario order."""
    return [Cell(s.kind, s.row, s.dealer_upcard) for s in build_scenarios()]


def all_chart_cells() -> list[Cell]:
    """Every cell on the chart, including rows the scenario set does not deal."""
    cells = []
    for kind, table in (("hard", HARD_TOTALS), ("soft", SOFT_TOTALS), ("pair", PAIRS)):
        for row in table:
            cells.extend(Cell(kind, row, upcard) for upcard in DEALER_UPCARDS)
    return cells


def cell_for_decision(row: dict[str, Any]) -> Cell:
    """The chart cell a logged decision row looks up (same rule as chart_code).

    Uses the row's player_cards, total, is_soft, is_pair and dealer_upcard. is_pair is
    True exactly when splitting was legal, so a pair that could not be split falls
    through to its hard or soft total. The number of cards does not matter.
    """
    upcard = _chart_key(row["dealer_upcard"])
    if row["is_pair"]:
        return Cell("pair", _chart_key(row["player_cards"][0]), upcard)
    return Cell("soft" if row["is_soft"] else "hard", row["total"], upcard)


def is_decision_covered(row: dict[str, Any]) -> bool:
    """True iff the logged decision's cell is a covered cell."""
    return is_covered(cell_for_decision(row))
