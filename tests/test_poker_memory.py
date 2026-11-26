"""Tests for poker memory: the opponent tally, notes and hypotheses, the rewrite prompt and parser,
harness-side count checks and status gates, the decision-time notes block, and MemoryEvent logging.

Hands are played with scripted players through poker.engine.play_hand, so every HandRecord
is real engine output. The model is always "hero"; the opponent is "villain".
"""

from poker.bots import make_bot
from poker.engine import play_hand, play_match
from poker.runner import match_seeds
from poker.memory import OpponentTally


class ScriptedPlayer:
    """Returns a fixed list of choices, then checks if it can, else calls."""

    def __init__(self, choices=()):
        self.choices = list(choices)

    def decide(self, state):
        if self.choices:
            return self.choices.pop(0)
        names = [item.action for item in state.menu]
        return "check" if "check" in names else "call"


def hand(hero=(), villain=(), hero_on_button=True, seed=1, hand_number=0):
    players = {"hero": ScriptedPlayer(hero), "villain": ScriptedPlayer(villain)}
    return play_hand(seed, players, button="hero" if hero_on_button else "villain", hand_number=hand_number)


def tally_of(*records):
    tally = OpponentTally("hero")
    for record in records:
        tally.observe(record)
    return tally


# ---------- Opponent tally ----------


def test_an_opponent_who_calls_a_preflop_raise_put_money_in_voluntarily_but_did_not_raise():
    record = hand(hero=["raise_pot"], villain=["call"])

    tally = tally_of(record)

    assert tally.counts("preflop.vpip") == (1, 0)
    assert tally.counts("preflop.raise") == (0, 1)


def test_facing_bets_counts_each_fold_call_and_raise_per_street_and_over_all_streets():
    # Preflop: villain calls hero's raise. Flop: villain checks, hero bets, villain raises, hero
    # calls. Turn: villain checks, hero bets, villain folds.
    record = hand(hero=["raise_pot", "raise_half_pot", "call", "raise_half_pot"], villain=["call", "check", "raise_half_pot", "check", "fold"])

    tally = tally_of(record)

    assert tally.counts("faced_bet.call.preflop") == (1, 0)
    assert tally.counts("faced_bet.raise.flop") == (1, 0)
    assert tally.counts("faced_bet.fold.turn") == (1, 0)
    assert tally.counts("faced_bet.fold") == (1, 2)
    assert tally.counts("faced_bet.call") == (1, 2)
    assert tally.counts("faced_bet.raise") == (1, 2)
    assert tally.counts("faced_bet.continue") == (2, 1)
    assert tally.counts("faced_bet.no_raise") == (2, 1)


def test_a_postflop_chance_to_bet_with_no_bet_to_face_counts_bets_and_checks_per_street():
    # Villain is the big blind, so first to act postflop. Flop: villain bets, hero calls.
    # Turn and river: villain checks, hero checks.
    record = hand(hero=["call", "call"], villain=["check", "raise_half_pot"])

    tally = tally_of(record)

    assert tally.counts("checked_to.bet.flop") == (1, 0)
    assert tally.counts("checked_to.check.turn") == (1, 0)
    assert tally.counts("checked_to.bet") == (1, 2)
    assert tally.counts("checked_to.check") == (2, 1)


def test_the_big_blind_checking_its_preflop_option_is_not_a_chance_to_bet_when_checked_to():
    record = hand(hero=["call", "check", "check", "check"], villain=["check", "check", "check", "check"])

    assert tally_of(record).counts("checked_to.check.preflop") == (0, 0)
    assert tally_of(record).counts("checked_to.check") == (3, 0)


def test_a_showdown_counts_against_hands_that_saw_a_flop_and_records_the_cards_the_opponent_showed():
    to_showdown = hand(seed=1, hand_number=0)
    folded_on_flop = hand(seed=2, hand_number=1, hero=["call", "raise_pot"], villain=["check", "check", "fold"])
    folded_preflop = hand(seed=3, hand_number=2, villain=["fold"], hero_on_button=False)

    tally = tally_of(to_showdown, folded_on_flop, folded_preflop)

    assert tally.counts("showdown.reached") == (1, 1)
    assert [(shown.hand_number, shown.cards) for shown in tally.showdowns] == [(0, tuple(to_showdown.hole_cards["villain"]))]


def test_the_tally_never_holds_the_opponents_hole_cards_from_hands_without_a_showdown():
    folded = hand(seed=2, hero=["call", "raise_pot"], villain=["check", "check", "fold"])

    tally = tally_of(folded)

    hidden = folded.hole_cards["villain"]
    assert tally.showdowns == []
    assert not any(card in tally.render() for card in hidden)
    assert not any(card in str(tally.snapshot()) for card in hidden)


def test_the_button_completing_the_small_blind_has_not_faced_a_bet_only_the_big_blind():
    record = hand(hero=["check"], villain=["call"], hero_on_button=False)

    tally = tally_of(record)

    assert tally.counts("faced_bet.call") == (0, 0)
    assert tally.counts("preflop.vpip") == (1, 0)


class Aggressor(ScriptedPlayer):
    """Bets or raises pot whenever it can, else calls."""

    def decide(self, state):
        names = [item.action for item in state.menu]
        return "raise_pot" if "raise_pot" in names else "call"


def test_over_a_40_hand_match_against_the_calling_station_the_tally_shows_it_folded_to_no_bets():
    records = play_match(match_seeds(7, 20), {"hero": Aggressor(), "villain": make_bot("calling_station")})

    tally = tally_of(*records)

    folds, others = tally.counts("faced_bet.fold")
    assert tally.hands == 40
    assert folds == 0 and others > 20
    assert f"faced a bet {others} times: folded 0, called {others}, raised 0" in tally.render()
