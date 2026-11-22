"""Plays the scenario set with a player and logs every hand, skipping scenarios already logged.

This mirrors agent/runner.py (same rows, same files, same resume), with three
differences:
- each hand is dealt from forced_shoe(scenario) instead of the per-hand seeded shoe;
- hand_number is the scenario's 1-based position in the list;
- every row gets run_type="scenario" and scenario_id, and decision rows also get
  is_scenario_cell, which is True only for the hand's first decision (the chart
  cell being tested). Later decisions in the same hand are logged but not graded
  as part of the scenario set.

Payouts are still logged so the rows have the usual shape, but the scenario set
is not a natural sample of hands, so its returns mean nothing.
"""

import time
from typing import Any, Callable, Optional, Sequence

from agent.llm_player import LLMPlayer
from agent.run_log import RunInfo, RunWriter, decision_rows, hand_row
from agent.runner import Progress
from agent.scenarios import Scenario, forced_shoe, scenario_shoe_seed
from blackjack.engine import play_hand
from blackjack.rules import DEFAULT_RULES, RuleSet

RUN_TYPE = "scenario"


def scenario_decision_rows(rows: list[dict[str, Any]], scenario: Scenario) -> list[dict[str, Any]]:
    """Add the scenario fields to one hand's decision rows (the first one is the graded cell)."""
    for index, row in enumerate(rows):
        row["run_type"] = RUN_TYPE
        row["scenario_id"] = scenario.scenario_id
        row["is_scenario_cell"] = index == 0
    return rows


def run_scenarios(
    player: LLMPlayer,
    writer: RunWriter,
    info: RunInfo,
    scenarios: Sequence[Scenario],
    rules: RuleSet = DEFAULT_RULES,
    on_hand: Optional[Callable[[Progress], None]] = None,
) -> Progress | None:
    """Play every scenario that isn't already in the log. Scenario i is hand_number i (1-based).

    Errors from the player (e.g. Ollama unreachable) propagate: the interrupted
    hand is not written, so a later resume replays it.
    """
    hand_numbers = range(1, len(scenarios) + 1)
    done = writer.completed_hands()
    previous = writer.previous_decision_rows()
    decisions = len(previous)
    correct = sum(row["correct"] for row in previous)
    invalid = sum(row["invalid"] for row in previous)
    payout = sum(row["payout"] for row in writer.previous_hand_rows())
    hands_done = len(done & set(hand_numbers))

    session_start = time.perf_counter()
    session_latency = 0.0
    session_decisions = 0
    session_hands = 0
    progress = None

    for hand_number, scenario in zip(hand_numbers, scenarios):
        if hand_number in done:
            continue
        shoe = forced_shoe(scenario, info.run_seed, rules.num_decks)
        player.take_hand_details()  # start the hand with an empty buffer
        record = play_hand(player, info.run_seed, hand_number, rules, shoe=shoe)
        record.shoe_seed = scenario_shoe_seed(info.run_seed, scenario.scenario_id)

        rows = decision_rows(record, player.take_hand_details(), info)
        rows = scenario_decision_rows(rows, scenario)
        hand = hand_row(record, rows, info)
        hand["run_type"] = RUN_TYPE
        hand["scenario_id"] = scenario.scenario_id
        writer.write_hand(rows, hand)

        hands_done += 1
        session_hands += 1
        decisions += len(rows)
        session_decisions += len(rows)
        session_latency += sum(row["latency_s"] for row in rows)
        correct += hand["num_correct"]
        invalid += hand["num_invalid"]
        payout += hand["payout"]
        progress = Progress(
            hand_number=hand_number,
            hands_done=hands_done,
            hands_total=len(scenarios),
            hand_decisions=len(rows),
            decisions=decisions,
            correct=correct,
            invalid=invalid,
            payout=payout,
            seconds_per_decision=session_latency / session_decisions if session_decisions else 0.0,
            seconds_per_hand=(time.perf_counter() - session_start) / session_hands,
        )
        if on_hand is not None:
            on_hand(progress)
    return progress
