"""The poker probability tool: equity against a random hand, and the pot odds of a call.

The harness works these out for every decision and shows them in the full-tools
prompt; the model does not call anything. Equity is Monte Carlo (poker.hands.
equity_vs_random) with a seed taken from a SHA-256 hash of the cards, like the
control bot's, so the same spot always shows the same number, in every run.
"""

import hashlib
import random
from dataclasses import dataclass
from typing import Optional

from poker.engine import DecisionState
from poker.hands import equity_vs_random

# 2000 samples: about 30 ms a decision, standard error under 1.2 percentage points.
EQUITY_SAMPLES = 2000

# The block heading. Prompts without the probability tool never contain it.
EQUITY_HEADER = (
    "Equity (worked out by the harness by simulation, treating the opponent's cards as a random hand, "
    "not as the hands this opponent actually plays):"
)


@dataclass(frozen=True)
class EquityInfo:
    """What the probability tool worked out for one decision."""

    equity: float  # share of pots won (ties half) against one random hand
    seed: int  # the Monte Carlo seed, from the cards
    samples: int
    pot_odds: Optional[float]  # to_call / (pot + to_call): the equity a call needs to break even; None if nothing to call
    to_call: int
    pot_after_call: int

    def lines(self) -> list[str]:
        """The probability tool's block for the prompt: the heading, equity, then pot odds."""
        if self.pot_odds is None:
            odds = "- Nothing to call: checking costs no chips."
        else:
            odds = (f"- Pot odds: calling {self.to_call} chips makes the pot {self.pot_after_call} chips, "
                    f"so the call breaks even at {_percent(self.pot_odds)} equity.")
        return [EQUITY_HEADER, f"- Your equity against a random hand: {_percent(self.equity)}.", odds]


def equity_seed(state: DecisionState) -> int:
    """A stable seed from the hole cards and board (Python's hash() changes between runs)."""
    cards = "equity-info|" + ",".join(sorted(state.hole_cards)) + "|" + ",".join(state.board)
    return int.from_bytes(hashlib.sha256(cards.encode()).digest()[:8], "big")


def equity_info(state: DecisionState) -> EquityInfo:
    """The seeded equity for this decision's cards."""
    seed = equity_seed(state)
    equity = equity_vs_random(list(state.hole_cards), list(state.board), EQUITY_SAMPLES, random.Random(seed))
    pot_odds = state.to_call / (state.pot + state.to_call) if state.to_call else None
    return EquityInfo(equity=equity, seed=seed, samples=EQUITY_SAMPLES, pot_odds=pot_odds,
                      to_call=state.to_call, pot_after_call=state.pot + state.to_call)


def _percent(share: float) -> str:
    return f"{100 * share:.1f}%"
