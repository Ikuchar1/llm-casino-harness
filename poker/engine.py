"""Plays one heads-up no-limit Hold'em hand on PokerKit for any two players.

The engine does not care whether a player is a leak bot or an LLM: anything with a
`decide(state) -> str` method works, returning the action name of one menu item.
Every hand starts from fresh 100bb stacks (docs/poker-plan.md, decision 6) and is
scored on its own.

PokerKit never draws cards here: every card comes from our own seeded deck, dealt
in this order: button hole cards, big blind hole cards, burn, flop (3), burn, turn,
burn, river.

Heads-up seats: in PokerKit the button posts the small blind and is player index 1;
the big blind is index 0. The button acts first preflop and last after the flop.
"""

from dataclasses import dataclass, field
from typing import Optional, Protocol

from pokerkit import Automation, NoLimitTexasHoldem

from poker.cards import make_deck

SMALL_BLIND = 1
BIG_BLIND = 2
STARTING_STACK = 100 * BIG_BLIND

BUTTON = "button"
BIG_BLIND_SEAT = "big_blind"
SEATS = (BUTTON, BIG_BLIND_SEAT)
_POKERKIT_INDEX = {BIG_BLIND_SEAT: 0, BUTTON: 1}

STREETS = ("preflop", "flop", "turn", "river")

FOLD = "fold"
CHECK = "check"
CALL = "call"

_AUTOMATIONS = (
    Automation.ANTE_POSTING,
    Automation.BET_COLLECTION,
    Automation.BLIND_OR_STRADDLE_POSTING,
    Automation.HOLE_CARDS_SHOWING_OR_MUCKING,
    Automation.HAND_KILLING,
    Automation.CHIPS_PUSHING,
    Automation.CHIPS_PULLING,
)


@dataclass(frozen=True)
class MenuItem:
    """One legal choice. `amount` is chips to call, or the raise-to total for raises."""

    action: str
    amount: int = 0


@dataclass(frozen=True)
class DecisionState:
    """Everything a player sees at one decision. Frozen so logged snapshots never change."""

    seat: str
    hole_cards: tuple[str, ...]
    board: tuple[str, ...]
    street: str
    pot: int  # every chip put in this hand so far, including this street's bets
    stack: int
    opponent_stack: int
    to_call: int
    is_button: bool
    menu: tuple[MenuItem, ...]


class Player(Protocol):
    """Anything that can choose an action. Return the action name of one state.menu item."""

    def decide(self, state: DecisionState) -> Optional[str]: ...


@dataclass
class HandRecord:
    """One finished hand. Plain values only, so dataclasses.asdict gives JSON-ready data."""

    seed: int
    button: str  # name of the player on the button
    hole_cards: dict[str, list[str]]  # player name -> their two cards
    board: list[str]
    showdown: bool
    chip_delta: dict[str, int]  # player name -> chips won (negative = lost); sums to 0


def play_hand(seed: int, players: dict[str, Player], button: str, deck: Optional[list[str]] = None) -> HandRecord:
    """Play one hand. `players` maps two names to players; `button` names the one on the button.

    The cards come from make_deck(seed) unless a stacked `deck` is given (tests).
    """
    if len(players) != 2 or button not in players:
        raise ValueError("need exactly two players, one of them on the button")
    big_blind = next(name for name in players if name != button)
    seat_names = {BUTTON: button, BIG_BLIND_SEAT: big_blind}
    cards = iter(deck if deck is not None else make_deck(seed))
    state = NoLimitTexasHoldem.create_state(
        _AUTOMATIONS, True, 0, (SMALL_BLIND, BIG_BLIND), BIG_BLIND, STARTING_STACK, 2
    )
    hole = {BUTTON: [next(cards), next(cards)], BIG_BLIND_SEAT: [next(cards), next(cards)]}
    state.deal_hole("".join(hole[BIG_BLIND_SEAT]))
    state.deal_hole("".join(hole[BUTTON]))
    board: list[str] = []

    while state.status:
        if state.actor_index is not None:
            seat = BUTTON if state.actor_index == _POKERKIT_INDEX[BUTTON] else BIG_BLIND_SEAT
            snapshot = _decision_state(state, seat, hole[seat], board)
            choice = players[seat_names[seat]].decide(snapshot)
            if choice == FOLD:
                state.fold()
            else:
                state.check_or_call()
        elif state.can_burn_card():
            state.burn_card(next(cards))
        elif state.can_deal_board():
            count = 3 if not board else 1
            dealt = [next(cards) for _ in range(count)]
            state.deal_board("".join(dealt))
            board.extend(dealt)

    showdown = not any(type(op).__name__ == "Folding" for op in state.operations)
    return HandRecord(
        seed=seed,
        button=button,
        hole_cards={seat_names[seat]: hole[seat] for seat in SEATS},
        board=board,
        showdown=showdown,
        chip_delta={seat_names[seat]: int(state.payoffs[_POKERKIT_INDEX[seat]]) for seat in SEATS},
    )


def _decision_state(state, seat: str, hole_cards: list[str], board: list[str]) -> DecisionState:
    me = _POKERKIT_INDEX[seat]
    to_call = state.checking_or_calling_amount
    menu = [MenuItem(CALL, to_call) if to_call else MenuItem(CHECK)]
    if state.can_fold():
        menu.insert(0, MenuItem(FOLD))
    return DecisionState(
        seat=seat,
        hole_cards=tuple(hole_cards),
        board=tuple(board),
        street=STREETS[state.street_index],
        pot=state.total_pot_amount,
        stack=state.stacks[me],
        opponent_stack=state.stacks[1 - me],
        to_call=to_call,
        is_button=seat == BUTTON,
        menu=tuple(menu),
    )
