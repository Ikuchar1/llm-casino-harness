"""Sanity check: a basic strategy bot should lose roughly 0.4-0.5% per hand under our rule set.

Usage (from the repo root):
    .venv/bin/python scripts/sanity_house_edge.py            # default hand count
    .venv/bin/python scripts/sanity_house_edge.py 200000 7   # hands, run seed

Prints the mean return per hand (units bet) with a 95% confidence interval and
the elapsed time. This is a check on the simulator and strategy table, not a test.
"""

import math
import sys
import time
from pathlib import Path

# Let the script import the blackjack package when run from anywhere.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from blackjack.engine import play_hand  # noqa: E402
from blackjack.rules import DEFAULT_RULES  # noqa: E402
from blackjack.strategy import BasicStrategyPlayer  # noqa: E402

DEFAULT_HANDS = 1_000_000
DEFAULT_RUN_SEED = 2026


def main() -> None:
    num_hands = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_HANDS
    run_seed = int(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_RUN_SEED

    player = BasicStrategyPlayer()
    total = 0.0
    total_squared = 0.0
    start = time.perf_counter()

    for hand_number in range(num_hands):
        payout = play_hand(player, run_seed, hand_number, DEFAULT_RULES).payout
        total += payout
        total_squared += payout * payout

    elapsed = time.perf_counter() - start
    mean = total / num_hands
    variance = (total_squared - num_hands * mean * mean) / (num_hands - 1)
    half_width = 1.96 * math.sqrt(variance / num_hands)

    print(f"Rules: {DEFAULT_RULES}")
    print(f"Hands: {num_hands:,}   run seed: {run_seed}")
    print(f"Mean return per hand: {mean * 100:+.3f}%  (95% CI {(mean - half_width) * 100:+.3f}% to {(mean + half_width) * 100:+.3f}%)")
    print(f"Std dev per hand: {math.sqrt(variance):.4f} units")
    print(f"Elapsed: {elapsed:.1f} s")


if __name__ == "__main__":
    main()
