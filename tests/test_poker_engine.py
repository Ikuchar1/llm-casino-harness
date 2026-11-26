"""Tests for the poker hand engine: seeded deals, stacks, duplicate dealing, the action menu, fallbacks.

Some tests pass a stacked deck so the cards are known. Deal order from the deck is:
button hole cards, big blind hole cards, burn, flop (3), burn, turn, burn, river.
"""

from poker.cards import make_deck
from poker.engine import play_hand


class ScriptedPlayer:
    """Test player that returns a fixed list of choices and remembers every state it saw.

    Once the list runs out it checks if it can, else calls.
    """

    def __init__(self, choices=()):
        self.choices = list(choices)
        self.states = []

    def decide(self, state):
        self.states.append(state)
        if self.choices:
            return self.choices.pop(0)
        names = [item.action for item in state.menu]
        return "check" if "check" in names else "call"


def stacked(button_cards, big_blind_cards, board, burns=("2d", "3d", "4d")):
    """A deck that deals the given hole cards and board (burns fill the burn slots)."""
    flop, turn, river = board[:3], board[3], board[4]
    order = [*button_cards, *big_blind_cards, burns[0], *flop, burns[1], turn, burns[2], river]
    rest = [card for card in _all_cards() if card not in order]
    return order + rest


def _all_cards():
    return [rank + suit for rank in "23456789TJQKA" for suit in "cdhs"]


def heads_up(button=None, big_blind=None):
    return {"hero": button or ScriptedPlayer(), "villain": big_blind or ScriptedPlayer()}


# ---------- A whole hand ----------


def test_a_hand_where_both_players_check_and_call_reaches_showdown_and_the_better_hand_wins():
    deck = stacked(["As", "Ah"], ["Kc", "Kd"], ["2c", "7h", "9s", "Jd", "3s"])
    record = play_hand(seed=0, players=heads_up(), button="hero", deck=deck)

    assert record.board == ["2c", "7h", "9s", "Jd", "3s"]
    assert record.showdown is True
    assert record.chip_delta == {"hero": 2, "villain": -2}


def test_a_button_that_folds_preflop_loses_its_small_blind_and_the_hand_has_no_showdown():
    deck = stacked(["7c", "2d"], ["Kc", "Kd"], ["2c", "7h", "9s", "Jd", "3s"])
    record = play_hand(seed=0, players=heads_up(button=ScriptedPlayer(["fold"])), button="hero", deck=deck)

    assert record.showdown is False
    assert record.board == []
    assert record.chip_delta == {"hero": -1, "villain": 1}


# ---------- Seeded deck ----------


def test_the_seeded_deck_is_a_full_52_card_deck_in_the_same_order_for_the_same_seed():
    deck = make_deck(7)

    assert sorted(deck) == sorted(_all_cards())
    assert make_deck(7) == deck
    assert make_deck(8) != deck


def test_the_same_seed_and_the_same_actions_give_the_same_hole_cards_board_and_outcome():
    first = play_hand(seed=42, players=heads_up(), button="hero")
    second = play_hand(seed=42, players=heads_up(), button="hero")
    other = play_hand(seed=43, players=heads_up(), button="hero")

    assert first.hole_cards == second.hole_cards
    assert first.board == second.board
    assert first.chip_delta == second.chip_delta
    assert (other.hole_cards, other.board) != (first.hole_cards, first.board)
