"""Compare two runs of the same hands decision by decision (e.g. a Mac run vs an HCC run).

    python scripts/compare_runs.py RUN_A RUN_B

Decisions are aligned by (hand_number, decision_index). Once the two runs take
different actions in a hand, the later decisions in that hand were dealt
different cards, so only decisions up to and including the first divergence in
each hand are compared; the rest are counted as "not comparable".

Exit code: 0 when every compared action matches and no decision is unmatched
(IDENTICAL or SAME ACTIONS), 1 when the runs diverge.
"""

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

MAX_DIVERGENCE_LINES = 20
PLATFORM_KEYS = ("platform", "hostname", "gpus", "slurm_job_id")  # printed when the metadata records them


@dataclass
class RunData:
    name: str
    metadata: dict[str, Any]
    decisions: list[dict[str, Any]]
    hands: list[dict[str, Any]]


@dataclass
class Divergence:
    hand: int
    index: int
    action_a: Optional[str]
    action_b: Optional[str]
    cards: list[str]
    upcard: Optional[str]
    cards_differ: bool  # the two runs saw different cards here (should not happen with the same seed)


@dataclass
class Comparison:
    n_a: int = 0
    n_b: int = 0
    aligned: int = 0  # decision keys present in both runs
    compared: int = 0  # aligned and at or before the first divergence of its hand
    same_action: int = 0
    same_reply: int = 0
    not_comparable: int = 0  # decisions (in either run) after a divergence in their hand
    unmatched: int = 0  # comparable decisions present in only one run
    divergences: list[Divergence] = field(default_factory=list)

    def verdict(self) -> str:
        differ = self.compared - self.same_action
        if differ or self.unmatched:
            text = f"DIVERGES ({differ} of {self.compared} compared actions differ)"
            if self.unmatched:
                text += f"; {self.unmatched} decisions exist in only one run"
            return text
        if self.same_reply == self.compared:
            return "IDENTICAL"
        return "SAME ACTIONS"


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def load(run_dir: Path | str) -> RunData:
    run_dir = Path(run_dir)
    metadata = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
    return RunData(run_dir.name, metadata, _read_jsonl(run_dir / "decisions.jsonl"), _read_jsonl(run_dir / "hands.jsonl"))


def _by_hand(decisions: list[dict[str, Any]]) -> dict[int, dict[int, dict[str, Any]]]:
    hands: dict[int, dict[int, dict[str, Any]]] = {}
    for row in decisions:
        hands.setdefault(row["hand_number"], {})[row["decision_index"]] = row
    return hands


def compare(a: RunData, b: RunData) -> Comparison:
    result = Comparison(n_a=len(a.decisions), n_b=len(b.decisions))
    hands_a, hands_b = _by_hand(a.decisions), _by_hand(b.decisions)
    for hand in sorted(set(hands_a) | set(hands_b)):
        rows_a, rows_b = hands_a.get(hand, {}), hands_b.get(hand, {})
        diverged = False
        for index in sorted(set(rows_a) | set(rows_b)):
            row_a, row_b = rows_a.get(index), rows_b.get(index)
            present = (row_a is not None) + (row_b is not None)
            if row_a is not None and row_b is not None:
                result.aligned += 1
            if diverged:
                result.not_comparable += present
                continue
            if row_a is None or row_b is None:
                result.unmatched += 1
                continue
            result.compared += 1
            same_cards = (row_a["player_cards"], row_a["dealer_upcard"]) == (row_b["player_cards"], row_b["dealer_upcard"])
            if row_a["raw_response"] == row_b["raw_response"]:
                result.same_reply += 1
            if row_a["action_taken"] == row_b["action_taken"] and same_cards:
                result.same_action += 1
                continue
            diverged = True
            result.divergences.append(
                Divergence(hand, index, row_a["action_taken"], row_b["action_taken"],
                           row_a.get("player_cards") or [], row_a.get("dealer_upcard"), not same_cards)
            )
    return result


def _accuracy_and_payout(run: RunData) -> str:
    correct = sum(1 for row in run.decisions if row.get("correct"))
    total = len(run.decisions)
    pct = 100 * correct / total if total else 0.0
    payout = sum(h.get("payout", 0) for h in run.hands)
    return f"accuracy {pct:.1f}% ({correct}/{total}), payout {payout:+g} over {len(run.hands)} hands"


def _platform_value(value: Any) -> str:
    return " + ".join(map(str, value)) if isinstance(value, list) else str(value)  # gpus is a list


def _header(label: str, run: RunData) -> str:
    meta = run.metadata
    digest = (meta.get("model_digest") or "not recorded")[:12]
    platform = ", ".join(f"{k}={_platform_value(meta[k])}" for k in PLATFORM_KEYS if meta.get(k)) or "not recorded"
    return (
        f"{label}: {run.name}\n"
        f"  model {meta.get('model', '?')} digest {digest}, prompt {meta.get('prompt_version') or 'not logged'}, "
        f"parser {meta.get('parser_version') or 'not logged'}, ollama {meta.get('ollama_version') or 'not recorded'}\n"
        f"  platform: {platform}"
    )


def report(a: RunData, b: RunData) -> str:
    result = compare(a, b)
    lines = [_header("A", a), _header("B", b), ""]
    lines.append(
        f"Decisions: A {result.n_a}, B {result.n_b}; aligned {result.aligned}; compared {result.compared}; "
        f"same action {result.same_action}; same reply text {result.same_reply}; "
        f"not comparable {result.not_comparable}; unmatched {result.unmatched}"
    )
    if result.divergences:
        lines.append(f"First divergence per hand ({len(result.divergences)} hands):")
        for d in result.divergences[:MAX_DIVERGENCE_LINES]:
            note = " (cards differ!)" if d.cards_differ else ""
            lines.append(f"  hand {d.hand} decision {d.index}: {','.join(d.cards)} vs {d.upcard}: "
                         f"{d.action_a} vs {d.action_b}{note}")
        if len(result.divergences) > MAX_DIVERGENCE_LINES:
            lines.append(f"  ... {len(result.divergences) - MAX_DIVERGENCE_LINES} more")
    lines += ["", f"A: {_accuracy_and_payout(a)}", f"B: {_accuracy_and_payout(b)}", "", f"Verdict: {result.verdict()}"]
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("run_a", help="run directory A (metadata.json, decisions.jsonl, hands.jsonl)")
    parser.add_argument("run_b", help="run directory B")
    args = parser.parse_args(argv)
    a, b = load(args.run_a), load(args.run_b)
    print(report(a, b))
    return 1 if compare(a, b).verdict().startswith("DIVERGES") else 0


if __name__ == "__main__":
    sys.exit(main())
