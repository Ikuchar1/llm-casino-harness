"""Plays one blackjack hand for any Player and returns a full record of it.

The engine does not care whether the player is a bot or an LLM: anything with a
`decide(state) -> str` method works. Deal order is player, dealer upcard,
player, dealer hole card, then every later draw in order.
"""

from dataclasses import dataclass, field
from typing import Optional, Protocol

from blackjack.cards import card_value, hand_total, is_blackjack, make_shoe_for_hand, shoe_seed_string
from blackjack.rules import DEFAULT_RULES, RuleSet

HIT = "hit"
STAND = "stand"
DOUBLE = "double"
SPLIT = "split"

# Applied when the player returns an invalid action (unparseable, None, or not legal).
FALLBACK_ACTION = STAND


@dataclass(frozen=True)
class DecisionState:
    """Everything a player sees at one decision. Frozen so logged snapshots never change."""

    player_cards: tuple[str, ...]  # ranks, e.g. ("K", "7")
    total: int
    is_soft: bool
    is_pair: bool  # True exactly when split is currently legal
    dealer_upcard: str
    legal_actions: tuple[str, ...]
    hand_index: int  # 0 or 1 within a split; 0 when there was no split
    num_cards: int
    from_split: bool


class Player(Protocol):
    """Anything that can choose an action. Return one of state.legal_actions."""

    def decide(self, state: DecisionState) -> Optional[str]: ...


@dataclass
class Decision:
    """One decision: what the player saw, what it asked for, and what the engine did."""

    state: DecisionState
    action_requested: Optional[str]  # exactly what the player returned
    action_taken: str  # the requested action, or FALLBACK_ACTION if it was invalid
    is_valid: bool


@dataclass
class PlayerHand:
    """One player hand. There are two after a split."""

    cards: list[str]
    from_split: bool = False
    is_split_aces: bool = False
    doubled: bool = False
    finished: bool = False
    payout: float = 0.0

    @property
    def total(self) -> int:
        return hand_total(self.cards)[0]

    @property
    def is_soft(self) -> bool:
        return hand_total(self.cards)[1]

    @property
    def is_bust(self) -> bool:
        return self.total > 21

    @property
    def is_blackjack(self) -> bool:
        # A two-card 21 after a split is just 21.
        return not self.from_split and is_blackjack(self.cards)


@dataclass
class HandRecord:
    """The full result of one hand, ready to log."""

    hand_number: int
    run_seed: int
    shoe_seed: str  # the exact string the shoe RNG was seeded with
    initial_player_cards: list[str]
    dealer_upcard: str
    player_blackjack: bool
    dealer_blackjack: bool
    decisions: list[Decision] = field(default_factory=list)
    player_hands: list[PlayerHand] = field(default_factory=list)
    dealer_cards: list[str] = field(default_factory=list)
    dealer_total: int = 0
    payout: float = 0.0  # total units won or lost, summed over split hands


class Shoe:
    """Hands out cards from a list in order."""

    def __init__(self, cards: list[str]):
        self.cards = cards
        self.next_index = 0

    def draw(self) -> str:
        card = self.cards[self.next_index]
        self.next_index += 1
        return card


def play_hand(
    player: Player,
    run_seed: int,
    hand_number: int,
    rules: RuleSet = DEFAULT_RULES,
    shoe: Optional[list[str]] = None,
) -> HandRecord:
    """Play one hand from start to payout.

    Normally the shoe is built from (run_seed, hand_number) per ADR 0001.
    Tests may pass `shoe` to stack the deck.
    """
    if shoe is None:
        shoe = make_shoe_for_hand(run_seed, hand_number, rules.num_decks)
    deck = Shoe(shoe)

    first_card = deck.draw()
    dealer_upcard = deck.draw()
    second_card = deck.draw()
    dealer_hole = deck.draw()

    first_hand = PlayerHand(cards=[first_card, second_card])
    dealer_cards = [dealer_upcard, dealer_hole]

    record = HandRecord(
        hand_number=hand_number,
        run_seed=run_seed,
        shoe_seed=shoe_seed_string(run_seed, hand_number),
        initial_player_cards=[first_card, second_card],
        dealer_upcard=dealer_upcard,
        player_blackjack=first_hand.is_blackjack,
        dealer_blackjack=is_blackjack(dealer_cards),
        player_hands=[first_hand],
        dealer_cards=dealer_cards,
    )

    # Blackjacks end the hand immediately with no decisions. Because the dealer
    # peeks under an A or 10-value upcard, a dealer blackjack is known before
    # the player acts. (A dealer can only have blackjack with one of those upcards.)
    if record.dealer_blackjack or record.player_blackjack:
        first_hand.finished = True
        if record.dealer_blackjack and record.player_blackjack:
            first_hand.payout = 0
        elif record.dealer_blackjack:
            first_hand.payout = -rules.bet
        else:
            first_hand.payout = rules.bet * rules.blackjack_payout
        _finish_record(record)
        return record

    _play_player_hands(player, record, deck, rules)

    if any(not hand.is_bust for hand in record.player_hands):
        _play_dealer(dealer_cards, deck, rules)

    dealer_total = hand_total(dealer_cards)[0]
    for hand in record.player_hands:
        hand.payout = _settle(hand, dealer_total, rules)
    _finish_record(record)
    return record


def legal_actions(hand: PlayerHand, splits_done: int, rules: RuleSet) -> tuple[str, ...]:
    """The actions the player may take on this hand right now."""
    actions = [HIT, STAND]
    if len(hand.cards) == 2:
        if not hand.from_split or rules.double_after_split:
            actions.append(DOUBLE)
        same_value = card_value(hand.cards[0]) == card_value(hand.cards[1])
        if same_value and splits_done < rules.max_splits:
            actions.append(SPLIT)
    return tuple(actions)


def _play_player_hands(player: Player, record: HandRecord, deck: Shoe, rules: RuleSet) -> None:
    """Ask the player for decisions until every player hand is finished."""
    splits_done = 0
    hand_index = 0
    while hand_index < len(record.player_hands):
        hand = record.player_hands[hand_index]

        # A split hand starts with one card; it gets its second card when its turn comes.
        if len(hand.cards) == 1:
            hand.cards.append(deck.draw())

        if hand.is_split_aces or hand.total >= 21:
            hand.finished = True

        while not hand.finished:
            state = _make_state(hand, hand_index, record.dealer_upcard, splits_done, rules)
            requested = player.decide(state)
            is_valid = requested in state.legal_actions
            action = requested if is_valid else FALLBACK_ACTION
            record.decisions.append(Decision(state, requested, action, is_valid))

            if action == HIT:
                hand.cards.append(deck.draw())
                if hand.total >= 21:
                    hand.finished = True
            elif action == STAND:
                hand.finished = True
            elif action == DOUBLE:
                hand.doubled = True
                hand.cards.append(deck.draw())
                hand.finished = True
            elif action == SPLIT:
                splits_done += 1
                is_aces = hand.cards[0] == "A"
                split_aces = is_aces and rules.split_aces_one_card
                second_card = hand.cards.pop()
                hand.from_split = True
                hand.is_split_aces = split_aces
                new_hand = PlayerHand(cards=[second_card], from_split=True, is_split_aces=split_aces)
                record.player_hands.insert(hand_index + 1, new_hand)
                hand.cards.append(deck.draw())
                if hand.is_split_aces or hand.total >= 21:
                    hand.finished = True

        hand_index += 1


def _make_state(
    hand: PlayerHand, hand_index: int, dealer_upcard: str, splits_done: int, rules: RuleSet
) -> DecisionState:
    actions = legal_actions(hand, splits_done, rules)
    return DecisionState(
        player_cards=tuple(hand.cards),
        total=hand.total,
        is_soft=hand.is_soft,
        is_pair=SPLIT in actions,
        dealer_upcard=dealer_upcard,
        legal_actions=actions,
        hand_index=hand_index,
        num_cards=len(hand.cards),
        from_split=hand.from_split,
    )


def _play_dealer(dealer_cards: list[str], deck: Shoe, rules: RuleSet) -> None:
    """Dealer draws to 17. Under S17 the dealer stands on soft 17; under H17 it hits."""
    while True:
        total, is_soft = hand_total(dealer_cards)
        if total < 17:
            dealer_cards.append(deck.draw())
        elif total == 17 and is_soft and rules.dealer_hits_soft_17:
            dealer_cards.append(deck.draw())
        else:
            return


def _settle(hand: PlayerHand, dealer_total: int, rules: RuleSet) -> float:
    """Units won (+) or lost (-) on one non-blackjack player hand."""
    bet = rules.bet * (2 if hand.doubled else 1)
    if hand.is_bust:
        return -bet
    if dealer_total > 21 or hand.total > dealer_total:
        return bet
    if hand.total < dealer_total:
        return -bet
    return 0


def _finish_record(record: HandRecord) -> None:
    record.dealer_total = hand_total(record.dealer_cards)[0]
    record.payout = sum(hand.payout for hand in record.player_hands)
