"""Export two scenario runs into demo/demo_data.json for the showcase demo.

Usage (from the repo root):
    .venv/bin/python scripts/export_demo_data.py
    .venv/bin/python scripts/export_demo_data.py --baseline runs/hcc_scenarios_baseline \\
        --full runs/hcc_scenarios_prob_strat_self

The baseline seat and the full harness seat (CONTEXT.md) are each one scenario run
folder made by scripts/run_scenarios.py. For every scenario in agent/scenarios.py the
export writes the deal, the basic strategy answer, the scenario's forced shoe (the
exact card order every seat draws from, so the visitor sees the same cards the agents
saw) and, per agent seat, the recorded answer, reasoning and full played-out hand.

A seat with no finished hand for a scenario is marked "pending". That covers a run
that is still going (its decisions.jsonl may be partial) and a missing run folder.
Re-run the export once a run finishes; the demo server picks up the new file on its
next request.

The shoe is written as one string with one character per card ("T" = the rank 10,
every other rank is its own one-letter name), so demo/engine.js can replay any play-out.
"""

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from agent.prompt import ODDS_HEADER  # noqa: E402
from agent.run_log import _read_jsonl  # noqa: E402
from agent.scenarios import SCENARIO_SET_VERSION, Scenario, build_scenarios, forced_shoe  # noqa: E402
from blackjack.cards import hand_total  # noqa: E402
from blackjack.engine import SPLIT, DecisionState, PlayerHand, legal_actions  # noqa: E402
from blackjack.rules import DEFAULT_RULES, RuleSet  # noqa: E402
from blackjack.strategy import best_legal_action, chart_code  # noqa: E402

FORMAT_VERSION = "demo-data-v1"
DEFAULT_SEED = 2026
DEFAULT_BASELINE = REPO_ROOT / "runs" / "mac_demo_scenarios_baseline"
DEFAULT_FULL = REPO_ROOT / "runs" / "mac_demo_scenarios_prob_strat_self"
DEFAULT_OUT = REPO_ROOT / "demo" / "demo_data.json"

# The two agent seats, keyed the way demo/app.js reads them.
SEATS = ("baseline", "full")

# Metadata keys copied into the export so a demo can say exactly what it is showing.
SOURCE_KEYS = (
    "run_id", "model", "model_digest", "harness_config", "harness_flags", "prompt_version",
    "parser_version", "scenario_set_version", "strategy_info_version", "self_eval_version",
    "run_seed", "started_at", "ended_at", "git_commit",
)


def encode_shoe(cards: list[str]) -> str:
    """One character per card: "10" becomes "T", every other rank is already one letter."""
    return "".join("T" if card == "10" else card for card in cards)


def decode_shoe(text: str) -> list[str]:
    return ["10" if char == "T" else char for char in text]


def first_decision_state(scenario: Scenario, rules: RuleSet = DEFAULT_RULES) -> DecisionState:
    """The state every seat sees at the scenario's graded first decision."""
    hand = PlayerHand(cards=list(scenario.player_cards))
    actions = legal_actions(hand, splits_done=0, rules=rules)
    total, is_soft = hand_total(hand.cards)
    return DecisionState(
        player_cards=tuple(hand.cards),
        total=total,
        is_soft=is_soft,
        is_pair=SPLIT in actions,
        dealer_upcard=scenario.dealer_upcard,
        legal_actions=actions,
        hand_index=0,
        num_cards=2,
        from_split=False,
    )


def scenario_label(scenario: Scenario) -> str:
    """How the demo names a deal, e.g. "Hard 16", "Soft 18", "Pair of 8s"."""
    if scenario.kind == "pair":
        rank = scenario.row
        return "Pair of aces" if rank == "A" else f"Pair of {rank}s"
    return f"{scenario.kind.capitalize()} {scenario.row}"


# ---------- probability tool block ----------

_PERCENT = r"(\d+(?:\.\d+)?)%"


def odds_block(user_prompt: str) -> Optional[str]:
    """The probability tool's lines from a decision prompt, or None if it has none."""
    lines = user_prompt.splitlines()
    if ODDS_HEADER not in lines:
        return None
    start = lines.index(ODDS_HEADER)
    block = [lines[start]]
    for line in lines[start + 1:]:
        if not line.startswith("- "):
            break
        block.append(line)
    return "\n".join(block)


def parse_odds(block: str) -> dict[str, Any]:
    """The numbers in an odds block, so the demo can draw them as bars."""
    parsed: dict[str, Any] = {}
    bust = re.search(r"If you hit once: " + _PERCENT, block)
    if bust:
        parsed["bust_if_hit"] = float(bust.group(1))
    dealer = re.search(r"- Dealer final total[^:]*: (.*)\.$", block, re.MULTILINE)
    if dealer:
        parsed["dealer"] = [
            [outcome, float(pct)] for outcome, pct in re.findall(r"(\w+): " + _PERCENT, dealer.group(1))
        ]
        parsed["dealer_no_blackjack"] = "(no blackjack)" in block
    stand = re.search(r"win " + _PERCENT + r", push " + _PERCENT + r", lose " + _PERCENT, block)
    if stand:
        parsed["stand"] = {"win": float(stand.group(1)), "push": float(stand.group(2)), "lose": float(stand.group(3))}
    return parsed


# ---------- run folders ----------


def read_run(run_dir: Path) -> dict[str, Any]:
    """A run folder's metadata, finished hands and their decision rows (by scenario_id).

    A hand counts as finished only once its row is in hands.jsonl (agent/run_log.py),
    so decision rows of a hand still being played are left out.
    """
    run_dir = Path(run_dir)
    if not run_dir.is_dir():
        return {"exists": False, "metadata": {}, "hands": {}, "decisions": {}}
    metadata_path = run_dir / "metadata.json"
    metadata = json.loads(metadata_path.read_text()) if metadata_path.exists() else {}
    hands = {row["scenario_id"]: row for row in _read_jsonl(run_dir / "hands.jsonl") if "scenario_id" in row}
    finished = {row["hand_number"] for row in hands.values()}
    decisions: dict[str, list[dict[str, Any]]] = {}
    for row in _read_jsonl(run_dir / "decisions.jsonl"):
        if row.get("hand_number") in finished and "scenario_id" in row:
            decisions.setdefault(row["scenario_id"], []).append(row)
    for rows in decisions.values():
        rows.sort(key=lambda row: row["decision_index"])
    return {"exists": True, "metadata": metadata, "hands": hands, "decisions": decisions}


def run_status(run: dict[str, Any]) -> str:
    """'missing', 'completed', or 'running' (anything that has not finished)."""
    if not run["exists"]:
        return "missing"
    sessions = run["metadata"].get("sessions") or []
    if sessions and sessions[-1].get("status") == "completed" and run["metadata"].get("ended_at"):
        return "completed"
    return "running"


def source_info(seat: str, run_dir: Path, run: dict[str, Any]) -> dict[str, Any]:
    info: dict[str, Any] = {"seat": seat, "dir": _display_path(run_dir), "status": run_status(run)}
    for key in SOURCE_KEYS:
        if key in run["metadata"]:
            info[key] = run["metadata"][key]
    info["hands_finished"] = len(run["hands"])
    return info


def _display_path(path: Path) -> str:
    path = Path(path).resolve()
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


# ---------- one seat of one scenario ----------


def seat_entry(seat: str, scenario: Scenario, run: dict[str, Any]) -> dict[str, Any]:
    """The seat's recorded answer and played-out hand, or {"status": "pending"}."""
    hand = run["hands"].get(scenario.scenario_id)
    rows = run["decisions"].get(scenario.scenario_id, [])
    if hand is None or not rows or len(rows) != hand.get("num_decisions"):
        return {"status": "pending"}

    first = rows[0]
    entry: dict[str, Any] = {
        "status": "answered",
        "action": first["parsed_action"],  # None when the reply was invalid
        "taken": first["action_taken"],
        "correct": bool(first["correct"]),
        "invalid": bool(first["invalid"]),
        "invalid_reason": first["invalid_reason"],
        "reasoning": first["raw_response"],
        "decisions": [
            {
                "hand": row["split_hand_index"],
                "cards": row["player_cards"],
                "legal": row["legal_actions"],
                "action": row["parsed_action"],
                "taken": row["action_taken"],
                "invalid": bool(row["invalid"]),
                "correct": bool(row["correct"]),
                "optimal": row["optimal_action"],
            }
            for row in rows
        ],
        "result": {
            "player_hands": [
                {key: sub[key] for key in ("cards", "total", "doubled", "from_split", "payout", "result")}
                for sub in hand["player_hands"]
            ],
            "dealer_cards": hand["dealer_cards"],
            "dealer_total": hand["dealer_total"],
            "payout": hand["payout"],
        },
    }
    block = odds_block(first["prompt"]["user"]) if isinstance(first.get("prompt"), dict) else None
    if block is not None:
        entry["odds_text"] = block
        entry["odds"] = parse_odds(block)
    self_eval = first.get("self_eval")
    if self_eval:
        entry["self_eval"] = {
            key: self_eval.get(key)
            for key in ("first_action", "first_valid", "first_correct", "first_raw",
                        "second_action", "second_valid", "second_raw", "final_action", "flipped")
        }
        entry["reasoning"] = self_eval.get("second_raw") or first["raw_response"]
    return entry


def check_seat(seat: str, scenario: Scenario, entry: dict[str, Any], shoe: list[str]) -> None:
    """Fail loudly if a run was dealt something other than this scenario's forced shoe."""
    if entry["status"] != "answered":
        return
    result = entry["result"]
    if result["dealer_cards"][:2] != [shoe[1], shoe[3]]:
        raise ValueError(
            f"{seat} run, {scenario.scenario_id}: dealer cards {result['dealer_cards'][:2]} do not match "
            f"the forced shoe {[shoe[1], shoe[3]]} (wrong --seed?)"
        )


# ---------- the whole export ----------


def build_demo_data(
    baseline_dir: Path, full_dir: Path, seed: int = DEFAULT_SEED, rules: RuleSet = DEFAULT_RULES,
) -> dict[str, Any]:
    runs = {"baseline": read_run(baseline_dir), "full": read_run(full_dir)}
    dirs = {"baseline": baseline_dir, "full": full_dir}
    for seat, run in runs.items():
        run_seed = run["metadata"].get("run_seed")
        if run_seed is not None and run_seed != seed:
            raise ValueError(f"{seat} run {dirs[seat]} used run seed {run_seed}, not {seed}")
        version = run["metadata"].get("scenario_set_version")
        if version is not None and version != SCENARIO_SET_VERSION:
            raise ValueError(f"{seat} run {dirs[seat]} used {version}, not {SCENARIO_SET_VERSION}")

    scenarios = []
    for scenario in build_scenarios():
        shoe = forced_shoe(scenario, seed, rules.num_decks)
        state = first_decision_state(scenario, rules)
        seats = {}
        for seat in SEATS:
            entry = seat_entry(seat, scenario, runs[seat])
            check_seat(seat, scenario, entry, shoe)
            seats[seat] = entry
        scenarios.append({
            "id": scenario.scenario_id,
            "kind": scenario.kind,
            "row": scenario.row,
            "label": scenario_label(scenario),
            "player": list(scenario.player_cards),
            "upcard": scenario.dealer_upcard,
            "hole": shoe[3],
            "total": state.total,
            "soft": state.is_soft,
            "legal": list(state.legal_actions),
            "basic": best_legal_action(state),
            "chart_code": chart_code(state),
            "shoe": encode_shoe(shoe),
            "ready": all(seats[seat]["status"] == "answered" for seat in SEATS),
            "seats": seats,
        })

    counts = {"scenarios": len(scenarios), "ready": sum(s["ready"] for s in scenarios)}
    for seat in SEATS:
        counts[f"{seat}_answered"] = sum(s["seats"][seat]["status"] == "answered" for s in scenarios)
    models = sorted({run["metadata"]["model"] for run in runs.values() if run["metadata"].get("model")})
    return {
        "format": FORMAT_VERSION,
        "exported_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "scenario_set_version": SCENARIO_SET_VERSION,
        "run_seed": seed,
        "model": ", ".join(models) if models else None,
        "rule_set": {
            "num_decks": rules.num_decks,
            "dealer_hits_soft_17": rules.dealer_hits_soft_17,
            "double_after_split": rules.double_after_split,
            "max_splits": rules.max_splits,
            "split_aces_one_card": rules.split_aces_one_card,
            "blackjack_payout": rules.blackjack_payout,
            "bet": rules.bet,
        },
        "shoe_encoding": "one character per card; T = 10",
        "sources": {seat: source_info(seat, dirs[seat], runs[seat]) for seat in SEATS},
        "counts": counts,
        "scenarios": scenarios,
    }


def write_demo_data(data: dict[str, Any], out: Path) -> None:
    """Write atomically, so the running demo server never reads a half-written file."""
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(out.suffix + ".tmp")
    tmp.write_text(json.dumps(data, separators=(",", ":")) + "\n", encoding="utf-8")
    tmp.replace(out)


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export two scenario runs into demo/demo_data.json.")
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE,
                        help="baseline scenario run folder (default runs/mac_demo_scenarios_baseline)")
    parser.add_argument("--full", type=Path, default=DEFAULT_FULL,
                        help="full harness scenario run folder (default runs/mac_demo_scenarios_prob_strat_self)")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help=f"run seed of both runs (default {DEFAULT_SEED})")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="output file (default demo/demo_data.json)")
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    try:
        data = build_demo_data(args.baseline, args.full, args.seed)
    except ValueError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    write_demo_data(data, args.out)
    counts = data["counts"]
    print(f"Wrote {_display_path(args.out)}")
    for seat in SEATS:
        source = data["sources"][seat]
        print(f"  {seat:8s} {counts[f'{seat}_answered']:3d}/{counts['scenarios']} answered  "
              f"[{source['status']}] {source['dir']} {source.get('run_id', '')}")
    print(f"  ready (both seats answered): {counts['ready']}/{counts['scenarios']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
