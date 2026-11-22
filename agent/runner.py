"""Plays a run of hands with a player and logs every one, skipping hands already logged."""

import time
from dataclasses import dataclass
from typing import Callable, Iterable, Optional

from agent.llm_player import LLMPlayer
from agent.run_log import RunInfo, RunWriter, decision_rows, hand_row
from blackjack.engine import play_hand
from blackjack.rules import DEFAULT_RULES, RuleSet


@dataclass
class Progress:
    """Running totals after each hand, for the progress line."""

    hand_number: int
    hands_done: int  # in this run directory, including resumed ones
    hands_total: int
    hand_decisions: int
    decisions: int
    correct: int
    invalid: int
    payout: float
    seconds_per_decision: float  # this session only
    seconds_per_hand: float  # this session only


def check_player_config(player: LLMPlayer, info: RunInfo) -> None:
    """Raise ValueError if the player runs a different harness config than the rows will say."""
    player_config = getattr(player, "config", None)
    if player_config != info.harness_config:
        raise ValueError(
            f"player harness config {getattr(player_config, 'name', None)!r} does not match "
            f"the run's harness config {info.harness_config.name!r}"
        )


def run_hands(
    player: LLMPlayer,
    writer: RunWriter,
    info: RunInfo,
    hand_numbers: Iterable[int],
    rules: RuleSet = DEFAULT_RULES,
    on_hand: Optional[Callable[[Progress], None]] = None,
) -> Progress | None:
    """Play every hand in hand_numbers that isn't already in the log.

    Errors from the player (e.g. Ollama unreachable) propagate: the interrupted
    hand is not written, so a later resume replays it.
    """
    check_player_config(player, info)
    hand_numbers = list(hand_numbers)
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

    for hand_number in hand_numbers:
        if hand_number in done:
            continue
        player.take_hand_details()  # start the hand with an empty buffer
        record = play_hand(player, info.run_seed, hand_number, rules)
        rows = decision_rows(record, player.take_hand_details(), info)
        hand = hand_row(record, rows, info)
        writer.write_hand(rows, hand)

        hands_done += 1
        session_hands += 1
        decisions += len(rows)
        session_decisions += len(rows)
        # Model time per decision, including the self-evaluation second call.
        session_latency += sum(row["latency_s"] + (row.get("self_eval") or {}).get("latency_s", 0) for row in rows)
        correct += hand["num_correct"]
        invalid += hand["num_invalid"]
        payout += hand["payout"]
        progress = Progress(
            hand_number=hand_number,
            hands_done=hands_done,
            hands_total=len(hand_numbers),
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

