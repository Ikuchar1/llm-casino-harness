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


# ---------- Action menu ----------


def menu_of(state):
    """The menu as (action, amount) pairs; amounts are chips to call or the raise-to total."""
    return [(item.action, item.amount) for item in state.menu]


def first_states(button_choices=(), big_blind_choices=(), seed=1):
    button, big_blind = ScriptedPlayer(button_choices), ScriptedPlayer(big_blind_choices)
    record = play_hand(seed=seed, players=heads_up(button, big_blind), button="hero")
    return button.states, big_blind.states, record


def test_the_button_facing_the_big_blind_preflop_gets_fold_call_both_pot_raises_and_all_in():
    button_states, _, _ = first_states()

    assert menu_of(button_states[0]) == [
        ("fold", 0), ("call", 1), ("raise_half_pot", 4), ("raise_pot", 6), ("all_in", 200),
    ]


def test_the_big_blind_after_a_limp_can_check_or_raise_but_is_not_offered_fold():
    _, big_blind_states, _ = first_states(button_choices=["call"])

    assert menu_of(big_blind_states[0]) == [("check", 0), ("raise_half_pot", 4), ("raise_pot", 6), ("all_in", 200)]


def test_a_player_facing_a_bet_is_offered_call_and_fold_but_never_check():
    _, big_blind_states, _ = first_states(button_choices=["raise_pot"])

    actions = [action for action, _ in menu_of(big_blind_states[0])]
    assert "check" not in actions
    assert menu_of(big_blind_states[0])[:2] == [("fold", 0), ("call", 4)]


def test_a_player_facing_an_all_in_can_only_fold_or_call_and_is_offered_no_raise():
    _, big_blind_states, _ = first_states(button_choices=["all_in"])

    assert menu_of(big_blind_states[0]) == [("fold", 0), ("call", 198)]


def test_pot_raises_that_would_go_past_the_stack_clamp_to_all_in_are_dropped_and_recorded():
    # Pot raises: button to 6, big blind to 18, button to 54, big blind to 162.
    _, _, record = first_states(button_choices=["raise_pot", "raise_pot", "fold"], big_blind_choices=["raise_pot", "raise_pot"])

    facing_162 = record.decisions[4]
    assert menu_of(facing_162.state) == [("fold", 0), ("call", 108), ("all_in", 200)]
    assert [(c.action, c.requested, c.actual) for c in facing_162.clamps] == [
        ("raise_half_pot", 324, 200), ("raise_pot", 486, 200),
    ]
    assert all(not decision.clamps for decision in record.decisions[:4])


# ---------- Fallback ----------


def test_a_choice_not_on_the_menu_checks_when_check_is_legal_and_records_the_fallback():
    _, big_blind_states, record = first_states(button_choices=["call"], big_blind_choices=["shove it all"])

    limp_answer = record.decisions[1]
    assert limp_answer.choice == "shove it all"
    assert limp_answer.action == "check"
    assert limp_answer.fallback is True
    assert record.decisions[0].fallback is False


def test_a_choice_not_on_the_menu_folds_when_facing_a_bet():
    _, _, record = first_states(button_choices=["check"])

    assert record.decisions[0].choice == "check"
    assert record.decisions[0].action == "fold"
    assert record.decisions[0].fallback is True
    assert record.showdown is False


def test_no_answer_at_all_is_also_a_fallback():
    _, _, record = first_states(button_choices=[None])

    assert (record.decisions[0].choice, record.decisions[0].action, record.decisions[0].fallback) == (None, "fold", True)
