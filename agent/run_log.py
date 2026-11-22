"""Writes a run's logs as JSON Lines (one JSON object per line) and supports resume.

Files in the run directory:
    decisions.jsonl  one row per decision
    hands.jsonl      one row per hand, including hands with no decisions (blackjacks)
    metadata.json    written by the run script

A hand's decision rows can only be finished once the hand is over (the payout is
known then), so the runner builds them after play_hand returns and writes the
hand's decisions, then the hand row, then flushes. A hand counts as finished only
once its row is in hands.jsonl. On resume, decision rows for unfinished hands are
dropped so a hand that was interrupted is replayed cleanly.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent.config import HarnessConfig
from agent.llm_player import DecisionDetail
from blackjack.engine import HandRecord
from blackjack.strategy import best_legal_action, chart_code

# Every field a decision row must have (tests check this list).
DECISION_FIELDS = [
    "run_id", "model", "model_digest", "harness_config", "harness_flags", "prompt_version",
    "parser_version", "run_seed", "ollama_seed", "hand_number", "decision_index", "split_hand_index", "from_split",
    "player_cards", "total", "is_soft", "is_pair", "dealer_upcard", "legal_actions", "num_cards",
    "prompt", "raw_response", "marker_words", "parsed_action", "action_taken",
    "optimal_action", "chart_code", "correct", "invalid", "invalid_reason",
    "done_reason", "eval_count", "latency_s",
    "hand_payout", "sub_hand_payout", "sub_hand_result", "sub_hand_final_cards",
]

# Every field a hand row must have.
HAND_FIELDS = [
    "run_id", "model", "harness_config", "run_seed", "hand_number", "shoe_seed",
    "initial_player_cards", "dealer_upcard", "dealer_cards", "dealer_total",
    "player_blackjack", "dealer_blackjack", "player_hands",
    "num_decisions", "num_correct", "num_invalid", "payout",
]


@dataclass(frozen=True)
class RunInfo:
    """Facts about the run that are repeated on every row."""

    run_id: str
    model: str
    model_digest: str | None
    harness_config: HarnessConfig
    run_seed: int
    ollama_seed: int | None
    prompt_version: str
    parser_version: str


def check_resume_compatible(metadata: dict[str, Any], expected: dict[str, Any]) -> None:
    """Raise ValueError if an existing run's metadata differs from this run's settings.

    A missing key counts as a mismatch, so runs from before a key existed (e.g. v1
    runs without prompt_version) can never be resumed under a newer setting.
    """
    for key, value in expected.items():
        if metadata.get(key) != value:
            raise ValueError(f"it was run with {key}={metadata.get(key)!r}, not {value!r}")


def result_word(payout: float) -> str:
    """'win', 'loss', or 'push' from a payout in units."""
    if payout > 0:
        return "win"
    if payout < 0:
        return "loss"
    return "push"


def decision_rows(record: HandRecord, details: list[DecisionDetail], info: RunInfo) -> list[dict[str, Any]]:
    """One row per decision in this hand. `details` must line up with record.decisions."""
    if len(details) != len(record.decisions):
        raise ValueError(f"{len(details)} details for {len(record.decisions)} decisions in hand {record.hand_number}")

    rows = []
    for index, (decision, detail) in enumerate(zip(record.decisions, details)):
        state = decision.state
        optimal = best_legal_action(state)
        invalid = not decision.is_valid
        sub_hand = record.player_hands[state.hand_index]  # indices are stable: only one split is allowed
        rows.append({
            "run_id": info.run_id,
            "model": info.model,
            "model_digest": info.model_digest,
            "harness_config": info.harness_config.name,
            "harness_flags": info.harness_config.flags(),
            "prompt_version": info.prompt_version,
            "parser_version": info.parser_version,
            "run_seed": info.run_seed,
            "ollama_seed": info.ollama_seed,
            "hand_number": record.hand_number,
            "decision_index": index,
            "split_hand_index": state.hand_index,
            "from_split": state.from_split,
            "player_cards": list(state.player_cards),
            "total": state.total,
            "is_soft": state.is_soft,
            "is_pair": state.is_pair,
            "dealer_upcard": state.dealer_upcard,
            "legal_actions": list(state.legal_actions),
            "num_cards": state.num_cards,
            "prompt": {"system": detail.system_prompt, "user": detail.user_prompt},
            "raw_response": detail.raw_response,
            "marker_words": detail.marker_words,
            "parsed_action": detail.parsed_action,
            "action_taken": decision.action_taken,
            "optimal_action": optimal,
            "chart_code": chart_code(state),
            "correct": (not invalid) and decision.action_taken == optimal,
            "invalid": invalid,
            "invalid_reason": detail.invalid_reason,
            "done_reason": detail.done_reason,
            "eval_count": detail.eval_count,
            "latency_s": round(detail.latency_s, 3),
            "hand_payout": record.payout,
            "sub_hand_payout": sub_hand.payout,
            "sub_hand_result": result_word(sub_hand.payout),
            "sub_hand_final_cards": list(sub_hand.cards),
        })
    return rows


def hand_row(record: HandRecord, rows: list[dict[str, Any]], info: RunInfo) -> dict[str, Any]:
    """One summary row for the hand. `rows` are this hand's decision rows."""
    return {
        "run_id": info.run_id,
        "model": info.model,
        "harness_config": info.harness_config.name,
        "run_seed": record.run_seed,
        "hand_number": record.hand_number,
        "shoe_seed": record.shoe_seed,
        "initial_player_cards": record.initial_player_cards,
        "dealer_upcard": record.dealer_upcard,
        "dealer_cards": record.dealer_cards,
        "dealer_total": record.dealer_total,
        "player_blackjack": record.player_blackjack,
        "dealer_blackjack": record.dealer_blackjack,
        "player_hands": [
            {
                "cards": hand.cards,
                "total": hand.total,
                "doubled": hand.doubled,
                "from_split": hand.from_split,
                "payout": hand.payout,
                "result": result_word(hand.payout),
            }
            for hand in record.player_hands
        ],
        "num_decisions": len(rows),
        "num_correct": sum(row["correct"] for row in rows),
        "num_invalid": sum(row["invalid"] for row in rows),
        "payout": record.payout,
    }


class RunWriter:
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

    def previous_hand_rows(self) -> list[dict[str, Any]]:
        """Hand rows already written (used for running totals on resume)."""
        return _read_jsonl(self.hands_path)

    def previous_decision_rows(self) -> list[dict[str, Any]]:
        """Decision rows already written (used for running totals on resume)."""
        return _read_jsonl(self.decisions_path)

    def write_hand(self, rows: list[dict[str, Any]], hand: dict[str, Any]) -> None:
        """Write one finished hand: its decision rows first, then its hand row."""
        with open(self.decisions_path, "a", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row) + "\n")
            f.flush()
        with open(self.hands_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(hand) + "\n")
            f.flush()

    def _clean_up_after_interruption(self) -> None:
        """Drop partial last lines and decision rows of hands that never got a hand row."""
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
