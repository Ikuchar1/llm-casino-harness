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

from pokerkit import Automation, Folding, NoLimitTexasHoldem

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
RAISE_HALF_POT = "raise_half_pot"
RAISE_POT = "raise_pot"
ALL_IN = "all_in"

# Pot-size raises: raise-to = the bet being faced + fraction x (pot after calling).
_POT_FRACTIONS = ((RAISE_HALF_POT, 0.5), (RAISE_POT, 1.0))

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
class Action:
    """One action taken this hand. `amount` is chips called or the raise-to total."""

    street: str
    seat: str
    action: str
    amount: int


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
    history: tuple[Action, ...]  # every action this hand so far, oldest first (blinds not included)
    menu: tuple[MenuItem, ...]


@dataclass(frozen=True)
class Clamp:
    """A pot-size raise whose formula amount was outside PokerKit's min/max raise-to."""

    action: str
    requested: int  # the pot-size formula's raise-to
    actual: int  # after clamping; dropped from the menu if another item has this amount


class Player(Protocol):
    """Anything that can choose an action. Return the action name of one state.menu item."""

    def decide(self, state: DecisionState) -> Optional[str]: ...


@dataclass
class DecisionRecord:
    """One decision: what the player saw and what the engine did with its choice."""

    player: str
    state: DecisionState  # includes the menu offered
    choice: Optional[str]  # exactly what the player returned
    action: str  # the menu action applied: the choice, or the fallback
    amount: int  # chips to call, or the raise-to total; 0 for fold and check
    fallback: bool  # the choice was not on the menu, so check (or fold) was applied
    clamps: list[Clamp]


@dataclass
class HandRecord:
    """One finished hand. Plain values only, so dataclasses.asdict gives JSON-ready data."""

    seed: int
    hand_number: int  # position in the match, from 0
    button: str  # name of the player on the button
    seats: dict[str, str]  # seat ("button", "big_blind") -> player name
    hole_cards: dict[str, list[str]]  # player name -> their two cards
    board: list[str]
    actions: list[Action]  # every action this hand, oldest first
    showdown: bool  # True when the hand ended with no fold
    chip_delta: dict[str, int]  # player name -> chips won (negative = lost); sums to 0
    decisions: list[DecisionRecord]


def play_hand(
    seed: int, players: dict[str, Player], button: str, hand_number: int = 0, deck: Optional[list[str]] = None
) -> HandRecord:
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
    decisions: list[DecisionRecord] = []
    history: list[Action] = []

    while state.status:
        if state.actor_index is not None:
            seat = BUTTON if state.actor_index == _POKERKIT_INDEX[BUTTON] else BIG_BLIND_SEAT
            menu, clamps = _menu(state)
            snapshot = _decision_state(state, seat, hole[seat], board, history, menu)
            choice = players[seat_names[seat]].decide(snapshot)
            item = next((item for item in menu if item.action == choice), None)
            fallback = item is None
            if fallback:
                item = _fallback_item(menu)
            decisions.append(DecisionRecord(
                player=seat_names[seat], state=snapshot, choice=choice, action=item.action,
                amount=item.amount, fallback=fallback, clamps=clamps,
            ))
            history.append(Action(snapshot.street, seat, item.action, item.amount))
            if item.action == FOLD:
                state.fold()
            elif item.action in (CHECK, CALL):
                state.check_or_call()
            else:
                state.complete_bet_or_raise_to(item.amount)
        elif state.can_burn_card():
            state.burn_card(next(cards))
        elif state.can_deal_board():
            count = 3 if not board else 1
            dealt = [next(cards) for _ in range(count)]
            state.deal_board("".join(dealt))
            board.extend(dealt)
        else:
            raise RuntimeError("PokerKit is waiting on an operation the engine does not perform")

    showdown = not any(isinstance(op, Folding) for op in state.operations)
    return HandRecord(
        seed=seed,
        hand_number=hand_number,
        button=button,
        seats=dict(seat_names),
        hole_cards={seat_names[seat]: hole[seat] for seat in SEATS},
        board=board,
        actions=history,
        showdown=showdown,
        chip_delta={seat_names[seat]: int(state.payoffs[_POKERKIT_INDEX[seat]]) for seat in SEATS},
        decisions=decisions,
    )


def play_duplicate(
    seed: int, players: dict[str, Player], first_button: str, first_hand_number: int = 0
) -> tuple[HandRecord, HandRecord]:
    """Deal one seeded deck twice with the players swapped between seats (decision 5).

    The cards stay with the seat, so on the second deal each player holds the cards
    the other held on the first.
    """
    second_button = next(name for name in players if name != first_button)
    return (
        play_hand(seed, players, button=first_button, hand_number=first_hand_number),
        play_hand(seed, players, button=second_button, hand_number=first_hand_number + 1),
    )


def play_match(seeds: list[int], players: dict[str, Player]) -> list[HandRecord]:
    """Play every seed as a duplicate pair: 2 x len(seeds) hands.

    The first player named in `players` is on the button for the first deal of every
    pair, so the button alternates every hand.
    """
    first_button = next(iter(players))
    hands: list[HandRecord] = []
    for index, seed in enumerate(seeds):
        hands.extend(play_duplicate(seed, players, first_button, first_hand_number=2 * index))
    return hands


def _decision_state(
    state, seat: str, hole_cards: list[str], board: list[str], history: list[Action], menu: list[MenuItem]
) -> DecisionState:
    me = _POKERKIT_INDEX[seat]
    to_call = state.checking_or_calling_amount
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
        history=tuple(history),
        menu=tuple(menu),
    )


def _fallback_item(menu: list[MenuItem]) -> MenuItem:
    """Check if check is on the menu, else fold (docs/poker-plan.md, decision 12)."""
    by_action = {item.action: item for item in menu}
    return by_action.get(CHECK) or by_action[FOLD]


def _menu(state) -> tuple[list[MenuItem], list[Clamp]]:
    """The legal menu right now: fold, check or call, the pot-size raises, all-in.

    Raise sizes are clamped to PokerKit's min/max raise-to; a raise that clamps to an
    amount already on the menu (often the all-in) is dropped. Every clamp is returned.
    """
    to_call = state.checking_or_calling_amount
    menu = []
    clamps: list[Clamp] = []
    if state.can_fold():
        menu.append(MenuItem(FOLD))
    menu.append(MenuItem(CALL, to_call) if to_call else MenuItem(CHECK))
    if not state.can_complete_bet_or_raise_to():
        return menu, clamps

    low = state.min_completion_betting_or_raising_to_amount
    high = state.max_completion_betting_or_raising_to_amount
    facing = max(state.bets)
    taken = {high}
    for action, fraction in _POT_FRACTIONS:
        requested = facing + int(fraction * (state.total_pot_amount + to_call))
        actual = min(max(requested, low), high)
        if actual != requested:
            clamps.append(Clamp(action, requested, actual))
        if actual not in taken:
            menu.append(MenuItem(action, actual))
            taken.add(actual)
    menu.append(MenuItem(ALL_IN, high))
    return menu, clamps
