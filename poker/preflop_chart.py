"""The poker strategy tool: a fixed heads-up preflop chart by hand class and spot.

The harness looks the decision up and shows the chart's play in the full-tools
prompt (preflop only); the model does not call anything. A hand class is one of
the 169 starting-hand types ("AKs", "T2o", "77"). A spot is what the player faces
before the flop: on the button with no raise yet, in the big blind after a limp,
facing one raise, or facing a re-raise. Each spot lists its plays in priority order
(raise, then call or check, then the default for every other hand).

Rationale. This is a deliberately simple, standard-shaped heads-up chart, not a
solver output and not tuned to the leak bots:
- The button opens wide (about 62% of hands here, raise or fold, no limping): it
  acts last on every later street and only one player, who has already posted, is
  left to get through. Heads-up references have the button play most of its hands
  (W. Tipton, Expert Heads Up No-Limit Hold'em, Vol. 1, 2012; E. Sklansky and
  E. Miller, No Limit Hold'em: Theory and Practice, 2006); this chart sits at the
  tighter end so a small model is not pushed into marginal spots.
- The big blind defends wide against one raise (about 44% of hands, a value
  re-raise with 99+/ATs+/AQo+/KQs): the blind already in the pot gives it a good
  price on the call (pot odds; B. Chen and J. Ankenman, The Mathematics of Poker,
  2006). After a limp it raises strong hands and
  checks the rest, since folding a free check is never right.
- Facing a re-raise, ranges narrow to strong pairs and big aces (QQ+/AK raise,
  77-JJ/AQ/AJs/KQs call): the standard tightening as raises go up.
The ranges are fixed here and listed in CHART; tests check each one names only
real hand classes and that the button opens about 60% of hands.
"""

from typing import Optional

from poker.cards import RANKS
from poker.engine import CALL as _ENGINE_CALL
from poker.engine import CHECK as _ENGINE_CHECK
from poker.engine import FOLD as _ENGINE_FOLD
from poker.engine import DecisionState

# Bump if the chart's ranges or block text change; log it with the run.
PREFLOP_CHART_VERSION = "preflop-chart-v1"

RAISE, CALL, CHECK, FOLD = "raise", "call", "check", "fold"

# Spots: who is acting and what they face before the flop.
OPEN = "open"  # button, nobody has raised: raise or fold (no limping)
VS_LIMP = "vs_limp"  # the big blind after the button only called: raise or check (never fold for free)
VS_RAISE = "vs_raise"  # facing one raise (the big blind against an open): re-raise, call or fold
VS_RERAISE = "vs_reraise"  # facing a second raise or more, either seat: re-raise, call or fold


def hand_class(hole_cards: tuple[str, ...]) -> str:
    """The 169-class name of two hole cards, high rank first: "AKs", "T2o", "77"."""
    first, second = sorted(hole_cards, key=lambda card: RANKS.index(card[0]), reverse=True)
    if first[0] == second[0]:
        return first[0] + second[0]
    return first[0] + second[0] + ("s" if first[1] == second[1] else "o")


def expand_range(notation: str) -> set[str]:
    """Hand classes from comma-separated range notation.

    "TT+" is TT up to AA, "22-44" is 22, 33, 44, "K9o+" raises the kicker up to one
    below the top card (K9o, KTo, KJo, KQo), and a bare class ("QJs") is itself.
    """
    classes: set[str] = set()
    for part in (piece.strip() for piece in notation.split(",")):
        if "-" in part:
            low, high = part.split("-")
            classes |= {rank * 2 for rank in RANKS[RANKS.index(low[0]): RANKS.index(high[0]) + 1]}
        elif part.endswith("+") and part[0] == part[1]:
            classes |= {rank * 2 for rank in RANKS[RANKS.index(part[0]):]}
        elif part.endswith("+"):
            top, kicker, suit = part[0], part[1], part[2]
            classes |= {top + rank + suit for rank in RANKS[RANKS.index(kicker): RANKS.index(top)]}
        else:
            classes.add(part)
    return classes


# For each spot, the plays in priority order with the hands that make them; any other
# hand gets the spot's last play.
CHART: dict[str, tuple[tuple[str, str], ...]] = {
    OPEN: (
        (RAISE, "22+, A2s+, A2o+, K2s+, K2o+, Q2s+, Q5o+, J2s+, J7o+, T2s+, T7o+, 95s+, 97o+, 84s+, 87o, "
                "74s+, 63s+, 53s+, 43s"),
        (FOLD, ""),
    ),
    VS_LIMP: (
        (RAISE, "77+, A9s+, ATo+, KTs+, KQo, QJs"),
        (CHECK, ""),
    ),
    VS_RAISE: (
        (RAISE, "99+, ATs+, AQo+, KQs"),
        (CALL, "22+, A2s+, A2o+, K2s+, K7o+, Q4s+, Q9o+, J6s+, J9o+, T6s+, T9o, 96s+, 98o, 85s+, 75s+, "
               "64s+, 54s"),
        (FOLD, ""),
    ),
    VS_RERAISE: (
        (RAISE, "QQ+, AKs, AKo"),
        (CALL, "77-JJ, AQs, AQo, AJs, KQs"),
        (FOLD, ""),
    ),
}

_CALM_ACTIONS = (_ENGINE_FOLD, _ENGINE_CHECK, _ENGINE_CALL)  # every other action is a bet or raise


def spot(state: DecisionState) -> Optional[str]:
    """The chart spot of a preflop decision, None after the flop."""
    if state.street != "preflop":
        return None
    raises = sum(1 for action in state.history if action.street == "preflop" and action.action not in _CALM_ACTIONS)
    if raises == 0:
        return OPEN if state.is_button else VS_LIMP
    return VS_RAISE if raises == 1 else VS_RERAISE


def chart_play(state: DecisionState) -> Optional[str]:
    """The chart's play for this decision (raise, call, check or fold), None after the flop."""
    where = spot(state)
    if where is None:
        return None
    hand = hand_class(state.hole_cards)
    plays = CHART[where]
    play = next((play for play, notation in plays[:-1] if hand in _RANGES[notation]), plays[-1][0])
    if play == RAISE and not any(item.action not in _CALM_ACTIONS for item in state.menu):
        return CALL  # e.g. facing an all-in: nothing left to raise
    return play


_RANGES = {notation: expand_range(notation) for plays in CHART.values() for _, notation in plays if notation}


# The block heading. Prompts without the strategy tool never contain it.
CHART_HEADER = (
    "Preflop chart (a simple, standard heads-up starting-hand chart; it ignores this opponent's habits "
    "and says nothing after the flop):"
)

_SPOT_WORDS = {
    OPEN: "on the button, nobody has raised yet",
    VS_LIMP: "in the big blind, the button only called",
    VS_RAISE: "facing one raise",
    VS_RERAISE: "facing a re-raise",
}
_PLAY_WORDS = {RAISE: "raise (any raise size on the menu)"}


def chart_lines(state: DecisionState) -> list[str]:
    """The strategy tool's block for the prompt; empty after the flop."""
    play = chart_play(state)
    if play is None:
        return []
    spot_words = _SPOT_WORDS[spot(state)]
    return [CHART_HEADER, f"- Your hand: {hand_class(state.hole_cards)}. Spot: {spot_words}. "
                          f"Chart play: {_PLAY_WORDS.get(play, play)}."]
