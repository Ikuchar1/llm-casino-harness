"""Writes a poker match's logs as JSON Lines (one JSON object per line).

Files in the run directory, as in agent/run_log.py:
    decisions.jsonl  one row per decision
    hands.jsonl      one row per hand

A hand counts as finished only once its row is in hands.jsonl. Reopening a run
directory drops a half-written last line and the decision rows of any hand that
never got its hand row, so an interrupted hand is replayed cleanly.
"""

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from poker.engine import HandRecord

# Every field a decision row must have, in order (tests check this list).
DECISION_FIELDS = [
    "seed", "hand_number", "decision_index", "player", "seat", "street",
    "hole_cards", "board", "pot", "stack", "opponent_stack", "to_call", "is_button",
    "history", "menu", "choice", "action", "amount", "fallback", "clamped", "clamps",
]

# Every field a hand row must have, in order (tests check this list).
HAND_FIELDS = [
    "seed", "hand_number", "seats", "button", "hole_cards", "board", "actions",
    "showdown", "chip_delta", "num_decisions", "num_fallbacks", "num_clamped",
]


def decision_rows(record: HandRecord) -> list[dict[str, Any]]:
    """One row per decision in this hand: the state summary, the menu offered, and what happened."""
    rows = []
    for index, decision in enumerate(record.decisions):
        state = decision.state
        rows.append({
            "seed": record.seed,
            "hand_number": record.hand_number,
            "decision_index": index,
            "player": decision.player,
            "seat": state.seat,
            "street": state.street,
            "hole_cards": list(state.hole_cards),
            "board": list(state.board),
            "pot": state.pot,
            "stack": state.stack,
            "opponent_stack": state.opponent_stack,
            "to_call": state.to_call,
            "is_button": state.is_button,
            "history": [asdict(action) for action in state.history],
            "menu": [asdict(item) for item in state.menu],
            "choice": decision.choice,
            "action": decision.action,
            "amount": decision.amount,
            "fallback": decision.fallback,
            "clamped": decision.clamped,
            "clamps": [asdict(clamp) for clamp in decision.clamps],
        })
    return rows


def hand_row(record: HandRecord) -> dict[str, Any]:
    """One summary row for the hand."""
    return {
        "seed": record.seed,
        "hand_number": record.hand_number,
        "seats": dict(record.seats),
        "button": record.button,
        "hole_cards": {name: list(cards) for name, cards in record.hole_cards.items()},
        "board": list(record.board),
        "actions": [asdict(action) for action in record.actions],
        "showdown": record.showdown,
        "chip_delta": dict(record.chip_delta),
        "num_decisions": len(record.decisions),
        "num_fallbacks": sum(decision.fallback for decision in record.decisions),
        "num_clamped": sum(decision.clamped for decision in record.decisions),
    }


class PokerRunWriter:
    """Appends rows to decisions.jsonl and hands.jsonl in one run directory."""

    def __init__(self, out_dir: Path | str):
        self.out_dir = Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.decisions_path = self.out_dir / "decisions.jsonl"
        self.hands_path = self.out_dir / "hands.jsonl"
        self._clean_up_after_interruption()

    def completed_hands(self) -> set[int]:
        """Hand numbers already in hands.jsonl."""
        return {row["hand_number"] for row in _read_jsonl(self.hands_path)}

    def write_hand(self, record: HandRecord) -> None:
        """Write one finished hand: its decision rows first, then its hand row."""
        with open(self.decisions_path, "a", encoding="utf-8") as f:
            for row in decision_rows(record):
                f.write(json.dumps(row) + "\n")
            f.flush()
        with open(self.hands_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(hand_row(record)) + "\n")
            f.flush()

    def _clean_up_after_interruption(self) -> None:
        hands = _read_jsonl(self.hands_path)
        _rewrite_jsonl(self.hands_path, hands)
        finished = {row["hand_number"] for row in hands}
        decisions = [row for row in _read_jsonl(self.decisions_path) if row.get("hand_number") in finished]
        _rewrite_jsonl(self.decisions_path, decisions)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Read a JSONL file, skipping a line cut off by a crash. Missing file -> []."""
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue  # only possible for a half-written last line
    return rows


def _rewrite_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    if not path.exists():
        return
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")
