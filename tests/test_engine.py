"""Tests for the hand engine: legal actions, dealer play, peek, payouts, seeding, invalid actions.

Most tests use a stacked shoe so the cards are known. Deal order is:
player, dealer upcard, player, dealer hole card, then every later draw in order.
"""

import pytest

from blackjack.engine import DecisionState, play_hand
from blackjack.rules import RuleSet


class ScriptedPlayer:
    """Test player that returns a fixed list of actions and remembers every state it saw."""

    def __init__(self, actions: list):
        self.actions = list(actions)
        self.states: list[DecisionState] = []

    def decide(self, state: DecisionState):
        self.states.append(state)
        return self.actions.pop(0)


class AlwaysStand:
    def decide(self, state: DecisionState) -> str:
        return "stand"


class AlwaysHit:
    def decide(self, state: DecisionState) -> str:
        return "hit"


def stacked(player_cards, dealer_cards, draws=()):
    """Build a shoe that deals the given player cards, dealer cards, then the draws in order."""
    p1, p2 = player_cards
    d_up, d_hole = dealer_cards
    # Padding at the end so a dealer that keeps hitting never runs out.
    return [p1, d_up, p2, d_hole, *draws] + ["2"] * 20


def play(player, player_cards, dealer_cards, draws=(), rules=None):
    shoe = stacked(player_cards, dealer_cards, draws)
    return play_hand(player, run_seed=0, hand_number=0, rules=rules or RuleSet(), shoe=shoe)


# ---------- Rule set ----------


def test_default_rule_set_matches_the_locked_rules():
    rules = RuleSet()
    assert rules.num_decks == 6
    assert rules.dealer_hits_soft_17 is False
    assert rules.double_after_split is True
    assert rules.max_splits == 1
    assert rules.split_aces_one_card is True
    assert rules.surrender_allowed is False
    assert rules.insurance_offered is False
    assert rules.dealer_peeks is True
    assert rules.blackjack_payout == 1.5
    assert rules.bet == 1


def test_rule_set_rejects_rules_the_engine_does_not_implement():
    with pytest.raises(ValueError):
        RuleSet(surrender_allowed=True)


# ---------- Decision state and legal actions ----------


def test_first_decision_state_describes_the_hand():
    player = ScriptedPlayer(["stand"])
    play(player, ["10", "6"], ["9", "8"])
    state = player.states[0]
    assert state.player_cards == ("10", "6")
    assert state.total == 16
    assert state.is_soft is False
    assert state.is_pair is False
    assert state.dealer_upcard == "9"
    assert state.legal_actions == ("hit", "stand", "double")
    assert state.hand_index == 0
    assert state.num_cards == 2
    assert state.from_split is False


def test_soft_hand_is_marked_soft():
    player = ScriptedPlayer(["stand"])
    play(player, ["A", "7"], ["9", "8"])
    assert player.states[0].total == 18
    assert player.states[0].is_soft is True


def test_double_is_only_legal_on_two_cards():
    player = ScriptedPlayer(["hit", "stand"])
    play(player, ["5", "4"], ["9", "8"], draws=["3"])
    assert "double" in player.states[0].legal_actions
    assert player.states[1].num_cards == 3
    assert player.states[1].legal_actions == ("hit", "stand")


def test_split_is_legal_on_two_cards_of_equal_value():
    player = ScriptedPlayer(["stand"])
    play(player, ["K", "Q"], ["9", "8"])
    assert player.states[0].is_pair is True
    assert "split" in player.states[0].legal_actions


def test_split_is_not_legal_on_unequal_cards():
    player = ScriptedPlayer(["stand"])
    play(player, ["9", "8"], ["9", "8"])
    assert player.states[0].is_pair is False
    assert "split" not in player.states[0].legal_actions


def test_split_hands_cannot_be_split_again():
    # 8,8 split; each hand draws another 8 but resplitting is not allowed.
    player = ScriptedPlayer(["split", "stand", "stand"])
    record = play(player, ["8", "8"], ["9", "8"], draws=["8", "8"])
    first_hand_state, second_hand_state = player.states[1], player.states[2]
    for state in (first_hand_state, second_hand_state):
        assert state.player_cards == ("8", "8")
        assert state.is_pair is False
        assert "split" not in state.legal_actions
        assert state.from_split is True
    assert first_hand_state.hand_index == 0
    assert second_hand_state.hand_index == 1
    assert len(record.player_hands) == 2


def test_double_after_split_is_legal():
    player = ScriptedPlayer(["split", "stand", "stand"])
    play(player, ["8", "8"], ["9", "8"], draws=["3", "2"])
    assert "double" in player.states[1].legal_actions


def test_double_after_split_can_be_turned_off():
    player = ScriptedPlayer(["split", "stand", "stand"])
    play(player, ["8", "8"], ["9", "8"], draws=["3", "2"], rules=RuleSet(double_after_split=False))
    assert "double" not in player.states[1].legal_actions


def test_split_aces_get_one_card_each_and_no_decisions():
    player = ScriptedPlayer(["split"])
    record = play(player, ["A", "A"], ["9", "8"], draws=["5", "9"])
    assert len(player.states) == 1  # only the split decision itself
    assert len(record.decisions) == 1
    assert [hand.cards for hand in record.player_hands] == [["A", "5"], ["A", "9"]]


def test_hand_that_reaches_21_stops_without_a_decision():
    player = ScriptedPlayer(["hit"])
    record = play(player, ["5", "6"], ["9", "8"], draws=["K"])
    assert len(record.decisions) == 1
    assert record.player_hands[0].total == 21


def test_doubled_hand_gets_exactly_one_card():
    player = ScriptedPlayer(["double"])
    record = play(player, ["5", "4"], ["9", "8"], draws=["2"])
    assert len(record.decisions) == 1
    assert record.player_hands[0].cards == ["5", "4", "2"]
    assert record.player_hands[0].doubled is True


# ---------- Dealer play (S17) ----------


def test_dealer_stands_on_soft_17():
    record = play(AlwaysStand(), ["10", "7"], ["A", "6"], draws=["5"])
    assert record.dealer_cards == ["A", "6"]
    assert record.dealer_total == 17


def test_dealer_hits_soft_16():
    record = play(AlwaysStand(), ["10", "7"], ["A", "5"], draws=["2"])
    assert record.dealer_cards == ["A", "5", "2"]
    assert record.dealer_total == 18


def test_dealer_hits_hard_16_and_stands_on_hard_17():
    record = play(AlwaysStand(), ["10", "8"], ["10", "6"], draws=["A"])
    assert record.dealer_cards == ["10", "6", "A"]
    assert record.dealer_total == 17


def test_dealer_hits_soft_17_under_h17_rules():
    rules = RuleSet(dealer_hits_soft_17=True)
    record = play(AlwaysStand(), ["10", "7"], ["A", "6"], draws=["2"], rules=rules)
    assert record.dealer_cards == ["A", "6", "2"]


def test_dealer_does_not_draw_when_every_player_hand_busted():
    record = play(AlwaysHit(), ["10", "6"], ["5", "6"], draws=["K", "9"])
    assert record.player_hands[0].is_bust
    assert record.dealer_cards == ["5", "6"]


# ---------- Dealer peek and blackjacks ----------


def test_dealer_blackjack_under_ace_ends_hand_with_no_decisions():
    player = ScriptedPlayer([])
    record = play(player, ["10", "9"], ["A", "K"])
    assert player.states == []
    assert record.decisions == []
    assert record.dealer_blackjack is True
    assert record.payout == -1


def test_dealer_blackjack_under_ten_ends_hand():
    record = play(ScriptedPlayer([]), ["10", "9"], ["Q", "A"])
    assert record.payout == -1


def test_player_and_dealer_blackjack_push():
    record = play(ScriptedPlayer([]), ["A", "K"], ["A", "Q"])
    assert record.player_blackjack is True
    assert record.payout == 0


def test_player_blackjack_pays_three_to_two_with_no_decisions():
    player = ScriptedPlayer([])
    record = play(player, ["A", "K"], ["9", "8"])
    assert record.decisions == []
    assert record.payout == 1.5


# ---------- Payouts ----------


def test_win_pays_one():
    assert play(AlwaysStand(), ["10", "9"], ["10", "8"]).payout == 1


def test_loss_costs_one():
    assert play(AlwaysStand(), ["10", "7"], ["10", "8"]).payout == -1


def test_push_pays_zero():
    assert play(AlwaysStand(), ["10", "8"], ["10", "8"]).payout == 0


def test_player_bust_loses_even_if_dealer_would_bust():
    record = play(AlwaysHit(), ["10", "6"], ["10", "6"], draws=["K", "K"])
    assert record.payout == -1


def test_dealer_bust_pays_one():
    record = play(AlwaysStand(), ["10", "2"], ["10", "6"], draws=["K"])
    assert record.dealer_total == 26
    assert record.payout == 1


def test_doubled_win_pays_two():
    record = play(ScriptedPlayer(["double"]), ["6", "5"], ["10", "7"], draws=["K"])
    assert record.payout == 2


def test_doubled_loss_costs_two():
    record = play(ScriptedPlayer(["double"]), ["6", "5"], ["10", "8"], draws=["2"])
    assert record.payout == -2


def test_split_hand_payouts_are_summed():
    # 8,8 vs dealer 10,8 (18). Hand 1: 8,K = 18 (push). Hand 2: 8,3 doubled + 10 = 21 (win 2).
    player = ScriptedPlayer(["split", "stand", "double"])
    record = play(player, ["8", "8"], ["10", "8"], draws=["K", "3", "10"])
    assert [hand.payout for hand in record.player_hands] == [0, 2]
    assert record.payout == 2


def test_21_after_split_is_not_blackjack():
    # Split aces; first hand gets a K (21), dealer has 20. Pays +1, not +1.5.
    player = ScriptedPlayer(["split"])
    record = play(player, ["A", "A"], ["10", "Q"], draws=["K", "2"])
    first_hand = record.player_hands[0]
    assert first_hand.total == 21
    assert first_hand.is_blackjack is False
    assert first_hand.payout == 1
    assert record.payout == 1 + -1


def test_21_after_split_loses_nothing_to_dealer_21_push():
    # Split 10s; first hand 10,A = 21 vs dealer three-card 21: push.
    player = ScriptedPlayer(["split", "stand"])
    record = play(player, ["10", "10"], ["9", "7"], draws=["A", "9", "5"])
    assert record.dealer_total == 21
    assert record.player_hands[0].payout == 0


# ---------- Seeding (ADR 0001) ----------


def test_hand_number_gives_same_start_across_runs():
    first = play_hand(AlwaysStand(), run_seed=123, hand_number=5)
    second = play_hand(AlwaysHit(), run_seed=123, hand_number=5)
    assert first.initial_player_cards == second.initial_player_cards
    assert first.dealer_upcard == second.dealer_upcard


def test_hand_start_does_not_depend_on_earlier_hands():
    # Play hands 0-9 with two very different players, then compare hand 10.
    for hand_number in range(10):
        play_hand(AlwaysHit(), run_seed=7, hand_number=hand_number)
    after_hitting = play_hand(AlwaysStand(), run_seed=7, hand_number=10)

    for hand_number in range(10):
        play_hand(AlwaysStand(), run_seed=7, hand_number=hand_number)
    after_standing = play_hand(AlwaysStand(), run_seed=7, hand_number=10)

    assert after_hitting.initial_player_cards == after_standing.initial_player_cards
    assert after_hitting.dealer_upcard == after_standing.dealer_upcard


def test_record_carries_seed_info():
    record = play_hand(AlwaysStand(), run_seed=123, hand_number=5)
    assert record.hand_number == 5
    assert record.run_seed == 123
    assert record.shoe_seed == "123-5"


# ---------- Invalid actions ----------


@pytest.mark.parametrize("bad_action", [None, "fold", "HIT", ""])
def test_invalid_action_falls_back_to_stand_and_is_marked_invalid(bad_action):
    record = play(ScriptedPlayer([bad_action]), ["10", "6"], ["10", "8"])
    decision = record.decisions[0]
    assert decision.action_requested == bad_action
    assert decision.action_taken == "stand"
    assert decision.is_valid is False
    assert record.player_hands[0].cards == ["10", "6"]


def test_illegal_double_on_three_cards_is_invalid():
    record = play(ScriptedPlayer(["hit", "double"]), ["5", "4"], ["10", "8"], draws=["2"])
    assert record.decisions[1].is_valid is False
    assert record.decisions[1].action_taken == "stand"
    assert record.player_hands[0].doubled is False


def test_valid_action_is_marked_valid():
    record = play(ScriptedPlayer(["stand"]), ["10", "6"], ["10", "8"])
    assert record.decisions[0].is_valid is True
    assert record.decisions[0].action_taken == "stand"


def test_decision_records_state_snapshot():
    record = play(ScriptedPlayer(["hit", "stand"]), ["5", "4"], ["10", "8"], draws=["2"])
    assert record.decisions[0].state.player_cards == ("5", "4")
    assert record.decisions[1].state.player_cards == ("5", "4", "2")
