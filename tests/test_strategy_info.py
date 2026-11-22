"""Tests for the strategy information principles (agent/strategy_info.py)."""

import json
from collections import Counter
from pathlib import Path

import pytest

from agent.scenarios import build_scenarios
from agent.strategy_info import (
    PRINCIPLES,
    STRATEGY_INFO_VERSION,
    Cell,
    all_chart_cells,
    cell_for_decision,
    chart_code_for_cell,
    covering_principles,
    is_covered,
    is_decision_covered,
    principle_action,
    principle_code,
    principles_block,
    scenario_cells,
)
from blackjack.cards import card_value, hand_total
from blackjack.engine import DOUBLE, HIT, SPLIT, STAND, DecisionState
from blackjack.strategy import best_legal_action, chart_code

REFERENCE_DECISIONS = Path(__file__).parent.parent / "hcc/reference/mac_smoke_seed2026_v2/decisions.jsonl"


# --- Every principle agrees with basic strategy ------------------------------


@pytest.mark.parametrize("cell", scenario_cells(), ids=str)
def test_every_applicable_principle_matches_the_chart_on_scenario_cells(cell):
    for number in covering_principles(cell):
        assert PRINCIPLES[number - 1].code_for(cell) == chart_code_for_cell(cell), (number, cell)


def test_every_applicable_principle_matches_the_chart_on_every_chart_cell():
    # The full chart also has cells a natural hand can reach but the scenario set
    # never deals: hard 4, hard 20-21, soft 12, soft 21.
    for cell in all_chart_cells():
        for number in covering_principles(cell):
            assert PRINCIPLES[number - 1].code_for(cell) == chart_code_for_cell(cell), (number, cell)


def test_no_two_principles_conflict_on_any_cell():
    for cell in all_chart_cells():
        codes = {PRINCIPLES[n - 1].code_for(cell) for n in covering_principles(cell)}
        assert len(codes) <= 1, cell


def test_principle_codes_are_chart_codes():
    for cell in all_chart_cells():
        code = principle_code(cell)
        assert code in (None, "H", "S", "Dh", "Ds", "P")


def test_principle_code_is_none_exactly_when_uncovered():
    for cell in all_chart_cells():
        assert (principle_code(cell) is None) == (not is_covered(cell))


def test_every_principle_covers_at_least_one_scenario_cell():
    used = Counter(n for cell in scenario_cells() for n in covering_principles(cell))
    assert set(used) == set(range(1, len(PRINCIPLES) + 1))


# --- Coverage ----------------------------------------------------------------


def test_scenario_cells_are_the_330_scenarios():
    cells = scenario_cells()
    assert len(cells) == 330
    assert len(set(cells)) == 330
    assert cells == [Cell(s.kind, s.row, s.dealer_upcard) for s in build_scenarios()]


def test_covered_count_on_the_scenario_set():
    covered = Counter(cell.kind for cell in scenario_cells() if is_covered(cell))
    assert covered == {"hard": 140, "soft": 45, "pair": 40}
    assert sum(covered.values()) == 225  # 225 / 330 = 68.2%


def test_soft_and_pairs_are_only_partly_covered():
    for kind in ("soft", "pair"):
        cells = [c for c in scenario_cells() if c.kind == kind]
        assert 0 < sum(map(is_covered, cells)) < len(cells)


def test_known_uncovered_cells():
    for cell in [Cell("hard", 9, "3"), Cell("soft", 18, "9"), Cell("pair", "9", "7"), Cell("pair", "4", "5")]:
        assert not is_covered(cell)


def test_known_covered_cells():
    assert principle_code(Cell("hard", 16, "10")) == "H"
    assert principle_code(Cell("hard", 12, "4")) == "S"
    assert principle_code(Cell("hard", 11, "10")) == "Dh"
    assert principle_code(Cell("hard", 11, "A")) == "H"
    assert principle_code(Cell("pair", "5", "9")) == "Dh"
    assert principle_code(Cell("pair", "8", "A")) == "P"
    assert principle_code(Cell("pair", "10", "6")) == "S"
    assert principle_code(Cell("soft", 19, "6")) == "S"
    assert principle_code(Cell("soft", 17, "7")) == "H"


# --- Turning a chart code into an action -------------------------------------


def test_principle_action_resolves_double_codes_by_legality():
    cell = Cell("hard", 11, "6")
    assert principle_action(cell, ["hit", "stand", "double"]) == DOUBLE
    assert principle_action(cell, ["hit", "stand"]) == HIT
    assert principle_action(Cell("pair", "8", "6"), ["hit", "stand", "double", "split"]) == SPLIT
    assert principle_action(Cell("hard", 17, "6"), ["hit", "stand"]) == STAND
    assert principle_action(Cell("hard", 9, "3"), ["hit", "stand", "double"]) is None


# --- Labelling logged decisions ----------------------------------------------


def _state(cards, total, soft, pair, upcard, legal, num_cards=None, from_split=False):
    return DecisionState(
        player_cards=tuple(cards), total=total, is_soft=soft, is_pair=pair, dealer_upcard=upcard,
        legal_actions=tuple(legal), hand_index=0, num_cards=num_cards or len(cards), from_split=from_split,
    )


def _row(state):
    return {
        "player_cards": list(state.player_cards), "total": state.total, "is_soft": state.is_soft,
        "is_pair": state.is_pair, "dealer_upcard": state.dealer_upcard,
        "legal_actions": list(state.legal_actions), "num_cards": state.num_cards,
    }


def test_cell_for_decision_uses_the_same_lookup_as_the_chart():
    assert cell_for_decision(_row(_state(["K", "6"], 16, False, False, "Q", ["hit", "stand", "double"]))) == Cell(
        "hard", 16, "10")
    assert cell_for_decision(_row(_state(["A", "7"], 18, True, False, "9", ["hit", "stand"]))) == Cell(
        "soft", 18, "9")
    assert cell_for_decision(_row(_state(["K", "Q"], 20, False, True, "5", ["hit", "stand", "double", "split"]))) == Cell(
        "pair", "10", "5")
    # A pair that can no longer be split (already split once) is its hard total.
    assert cell_for_decision(_row(_state(["8", "8"], 16, False, False, "6", ["hit", "stand", "double"],
                                         from_split=True))) == Cell("hard", 16, "6")


def test_later_decisions_map_to_their_total_cell():
    state = _state(["2", "3", "6"], 11, False, False, "6", ["hit", "stand"])
    assert cell_for_decision(_row(state)) == Cell("hard", 11, "6")
    assert is_decision_covered(_row(state))
    # Doubling is not legal on three cards, so "double if allowed, otherwise hit" means hit.
    assert principle_action(cell_for_decision(_row(state)), state.legal_actions) == HIT == best_legal_action(state)


def test_decision_labels_agree_with_the_logged_reference_run():
    rows = [json.loads(line) for line in REFERENCE_DECISIONS.read_text().splitlines() if line.strip()]
    assert rows
    for row in rows:
        cell = cell_for_decision(row)
        assert chart_code_for_cell(cell) == row["chart_code"]
        if is_decision_covered(row):
            assert principle_action(cell, row["legal_actions"]) == row["optimal_action"]


def test_covered_decisions_always_give_the_graded_action_over_many_states():
    # Every two-card start the engine can produce, with and without double/split legal.
    ranks = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "A"]
    for a in ranks:
        for b in ranks:
            total, soft = hand_total([a, b])
            if total == 21:
                continue
            pairable = card_value(a) == card_value(b)
            for upcard in ["2", "3", "4", "5", "6", "7", "8", "9", "10", "K", "A"]:
                for can_double in (True, False):
                    for can_split in ((True, False) if pairable else (False,)):
                        legal = ["hit", "stand"] + (["double"] if can_double else []) + (["split"] if can_split else [])
                        state = _state([a, b], total, soft, can_split, upcard, legal)
                        cell = cell_for_decision(_row(state))
                        assert chart_code_for_cell(cell) == chart_code(state)
                        if is_covered(cell):
                            assert principle_action(cell, legal) == best_legal_action(state)


# --- The prompt text ---------------------------------------------------------


EXPECTED_BLOCK = """\
Strategy principles (these cover many hands but not all of them). The hard and soft rules apply only when you are not holding a pair you can split; pairs have their own rules.
1. Always split aces and 8s.
2. Stand on hard 17 or more. Never split 10s: stand on any two 10-value cards.
3. With hard 13 to 16, stand against a dealer 2 to 6 and hit against a dealer 7 to ace.
4. With hard 12, stand against a dealer 4 to 6 and hit against a dealer 2, 3 or 7 to ace.
5. Always hit a hard 8 or less.
6. With hard 10 or 11, double (or hit if doubling is not allowed) when your total is higher than the dealer's upcard, counting the dealer's ace as 11; otherwise hit. Never split 5s: play a pair of 5s exactly like hard 10.
7. Stand on soft 19 or more.
8. With soft 17 or less, hit against a dealer 7 to ace."""


def test_principles_block_text_is_stable():
    assert principles_block() == EXPECTED_BLOCK


def test_principles_block_numbers_match_principles():
    lines = principles_block().splitlines()[1:]
    assert len(lines) == len(PRINCIPLES) == 8
    for number, (line, principle) in enumerate(zip(lines, PRINCIPLES), start=1):
        assert line == f"{number}. {principle.text}"


def test_version_string():
    assert STRATEGY_INFO_VERSION == "strategy-info-v1"
