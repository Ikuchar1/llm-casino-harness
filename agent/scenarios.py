"""The scenario set: one forced starting hand for every basic strategy chart cell.

A scenario is one cell of the chart: a player starting hand (a chart row) against
one dealer upcard. The rows are hard 5-19, soft 13-20 (A,2-A,9) and the ten pairs
(2,2-10,10 and A,A), each against upcards 2-10 and A: 33 x 10 = 330 scenarios.
Hard 4 and hard 20 are missing from the hard rows because they only exist as
pairs (2,2 and 10,10), which the pair rows cover.

Each scenario is dealt from a stacked 6-deck shoe (see forced_shoe) so the player
gets exactly the scenario's two cards and the dealer the scenario's upcard.
"""

import random
from dataclasses import dataclass

from blackjack.cards import CARDS_PER_RANK_PER_DECK, RANKS, is_blackjack
from blackjack.strategy import DEALER_UPCARDS

# Bump this if the list, its order, or the composition rule ever changes, so a
# resumed run never mixes two different scenario sets (checked on resume).
SCENARIO_SET_VERSION = "scenarios-v1"

# Written into metadata.json so the paper can quote it.
COMPOSITION_RULE = (
    "Hard totals 5-19 use one fixed two-card hand: a 10 plus (total - 10) when the total "
    "allows it (hard 12-19 = 10,2 ... 10,9), otherwise 2 plus (total - 2) (hard 5-11 = "
    "2,3 ... 2,9); none is a pair and none contains an ace. Soft totals are A,2-A,9 "
    "(soft 13-20). Pairs are 2,2-9,9, 10,10 (never mixed face cards) and A,A. "
    "The player's cards are dealt in the order listed. Every row is played against "
    "dealer upcards 2, 3, 4, 5, 6, 7, 8, 9, 10, A (10 = the rank '10')."
)

PAIR_RANKS = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "A"]


@dataclass(frozen=True)
class Scenario:
    """One chart cell to test: a player starting hand against a dealer upcard."""

    scenario_id: str  # e.g. "hard16_vs_10", "soft18_vs_9", "pair8_vs_A"
    kind: str  # "hard", "soft" or "pair"
    row: int | str  # hard/soft total (int), or the pair's rank (str)
    player_cards: tuple[str, str]
    dealer_upcard: str


def hard_cards(total: int) -> tuple[str, str]:
    """The fixed two-card, non-pair, ace-free hand for a hard total of 5-19."""
    if not 5 <= total <= 19:
        raise ValueError(f"No two-card non-pair hard hand is used for total {total}")
    if total >= 12:
        return ("10", str(total - 10))
    return ("2", str(total - 2))


def build_scenarios() -> list[Scenario]:
    """Every chart cell once, in a fixed order: hard rows, soft rows, then pairs.

    Within each row the upcards go 2, 3, ..., 10, A. A scenario's position in
    this list (1-based) is its hand_number in the run log.
    """
    rows: list[tuple[str, int | str, tuple[str, str]]] = []
    for total in range(5, 20):
        rows.append(("hard", total, hard_cards(total)))
    for second_card in range(2, 10):
        rows.append(("soft", 11 + second_card, ("A", str(second_card))))
    for rank in PAIR_RANKS:
        rows.append(("pair", rank, (rank, rank)))

    scenarios = []
    for kind, row, cards in rows:
        for upcard in DEALER_UPCARDS:
            scenarios.append(
                Scenario(
                    scenario_id=f"{kind}{row}_vs_{upcard}",
                    kind=kind,
                    row=row,
                    player_cards=cards,
                    dealer_upcard=upcard,
                )
            )
    return scenarios


def scenario_shoe_seed(run_seed: int, scenario_id: str) -> str:
    """The string a scenario's shoe RNG is seeded with. Logged as the hand's shoe_seed.

    The "scenario-" prefix keeps it different from natural-dealing seeds like "2026-7".
    """
    return f"scenario-{run_seed}-{scenario_id}"


def forced_shoe(scenario: Scenario, run_seed: int, num_decks: int = 6) -> list[str]:
    """A full shoe stacked so play_hand deals this scenario.

    play_hand deals in the order player, dealer upcard, player, dealer hole, so the
    shoe starts [player card 1, upcard, player card 2, hole card]. The three forced
    cards are taken out of a normal 6-deck shoe, the rest is shuffled with a seed
    built from (run_seed, scenario_id), and the hole card is the first card of that
    shuffle that does not give the dealer blackjack. (With an A or 10 upcard a dealer
    blackjack would end the hand before the player decides anything.)
    """
    remaining = RANKS * (CARDS_PER_RANK_PER_DECK * num_decks)
    first_card, second_card = scenario.player_cards
    for card in (first_card, scenario.dealer_upcard, second_card):
        remaining.remove(card)  # removes one copy, so card counts stay realistic

    rng = random.Random(scenario_shoe_seed(run_seed, scenario.scenario_id))
    rng.shuffle(remaining)

    hole_index = next(
        i for i, card in enumerate(remaining) if not is_blackjack([scenario.dealer_upcard, card])
    )
    hole_card = remaining.pop(hole_index)
    return [first_card, scenario.dealer_upcard, second_card, hole_card] + remaining
