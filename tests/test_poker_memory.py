"""Tests for poker memory: the opponent tally, notes and hypotheses, the rewrite prompt and parser,
harness-side count checks and status gates, the decision-time notes block, and MemoryEvent logging.

Hands are played with scripted players through poker.engine.play_hand, so every HandRecord
is real engine output. The model is always "hero"; the opponent is "villain".
"""

from poker.bots import make_bot
from poker.engine import play_hand, play_match
from poker.runner import match_seeds
from poker.memory import (
    CONFIRMED,
    HAND_FREQUENCY_THRESHOLD,
    LEAK_THRESHOLD,
    MAX_AGAINST_SHARE,
    TENTATIVE,
    WORD_BUDGET, Hypothesis, Notes, OpponentTally, parse_line, parse_rewrite, status_for, verify,
)


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


# ---------- Hypotheses and notes ----------


def test_a_hypothesis_renders_in_the_line_format_and_parses_back_to_the_same_hypothesis():
    hypothesis = Hypothesis("never folds to bets", 9, 0, "faced_bet.continue", TENTATIVE)

    assert hypothesis.line() == "never folds to bets | for 9 | against 0 | TENTATIVE"
    assert parse_line(hypothesis.cited_line()) == hypothesis
    assert parse_line(hypothesis.line()) == Hypothesis("never folds to bets", 9, 0, None, TENTATIVE)


# ---------- Rewrite parser ----------

PREVIOUS = Notes((Hypothesis("plays every hand", 4, 1, "preflop.vpip", TENTATIVE),))


def test_the_rewrite_parser_skips_junk_lines_keeps_the_hypotheses_and_logs_the_junk():
    response = (
        "Sure! Here are my updated notes:\n"
        "\n"
        "1. never folds to bets | key faced_bet.continue | for 9 | against 0\n"
        "This opponent seems loose.\n"
        "- H2: never raises | key: faced_bet.no_raise | for: 9 | against: 0 | CONFIRMED\n"
    )

    result = parse_rewrite(response, PREVIOUS)

    assert result.notes == Notes((
        Hypothesis("never folds to bets", 9, 0, "faced_bet.continue", TENTATIVE),
        Hypothesis("never raises", 9, 0, "faced_bet.no_raise", CONFIRMED),
    ))
    assert result.junk_lines == ["Sure! Here are my updated notes:", "This opponent seems loose."]
    assert not result.parse_failed and not result.dropped and not result.truncated


def test_the_rewrite_parser_keeps_the_first_three_hypotheses_and_logs_the_dropped_lines():
    lines = [f"read {n} | key faced_bet.call | for {n} | against 0" for n in range(1, 6)]

    result = parse_rewrite("\n".join(lines), PREVIOUS)

    assert [h.text for h in result.notes.hypotheses] == ["read 1", "read 2", "read 3"]
    assert result.dropped == lines[3:]


def test_an_empty_or_unreadable_rewrite_keeps_the_previous_notes_and_logs_a_parse_failure():
    for response in ("", None, "I think they are loose.\nNo counts here."):
        result = parse_rewrite(response, PREVIOUS)

        assert result.notes == PREVIOUS
        assert result.parse_failed


def test_hypothesis_text_past_the_word_budget_is_cut_and_the_cut_is_logged():
    long_text = " ".join(f"word{n}" for n in range(60))
    response = "\n".join(f"{long_text} | key faced_bet.call | for 1 | against 0" for _ in range(3))

    result = parse_rewrite(response, PREVIOUS)

    words = [len(h.text.split()) for h in result.notes.hypotheses]
    assert words == [60, WORD_BUDGET - 60]
    assert result.truncated


def test_notes_within_the_word_budget_are_not_marked_truncated():
    result = parse_rewrite("never folds | key faced_bet.continue | for 9 | against 0", PREVIOUS)

    assert not result.truncated


# ---------- Harness-side verification and status ----------


def station_tally():
    """A tally where the calling station faced plenty of bets and never folded."""
    return tally_of(*play_match(match_seeds(7, 20), {"hero": Aggressor(), "villain": make_bot("calling_station")}))


def test_a_cited_count_that_does_not_match_the_tally_is_replaced_by_the_true_count_and_logged():
    tally = station_tally()
    true_for, true_against = tally.counts("faced_bet.continue")
    claimed = Notes((Hypothesis("never folds to bets", 3, 2, "faced_bet.continue"),))

    result = verify(claimed, tally)

    hypothesis = result.notes.hypotheses[0]
    assert (hypothesis.for_count, hypothesis.against_count) == (true_for, true_against)
    assert result.count_mismatches == [{
        "text": "never folds to bets", "opportunity_key": "faced_bet.continue",
        "cited": [3, 2], "tally": [true_for, true_against],
    }]


def test_a_cited_count_that_matches_the_tally_is_kept_and_not_logged_as_a_mismatch():
    tally = station_tally()
    true_for, true_against = tally.counts("faced_bet.continue")
    claimed = Notes((Hypothesis("never folds to bets", true_for, true_against, "faced_bet.continue"),))

    result = verify(claimed, tally)

    assert result.count_mismatches == []
    assert result.notes.hypotheses[0].for_count == true_for


def test_a_hypothesis_with_an_unknown_or_missing_key_is_kept_as_tentative_with_its_counts_and_logged_unverifiable():
    claimed = Notes((
        Hypothesis("bluffs rivers", 30, 0, "river.bluff", CONFIRMED),
        Hypothesis("tilts after losing", 25, 1, None, CONFIRMED),
    ))

    result = verify(claimed, station_tally())

    assert result.notes == Notes((
        Hypothesis("bluffs rivers", 30, 0, "river.bluff", TENTATIVE),
        Hypothesis("tilts after losing", 25, 1, None, TENTATIVE),
    ))
    assert result.unverifiable == ["bluffs rivers", "tilts after losing"]
    assert result.count_mismatches == []


def test_a_facing_a_bet_or_no_bet_to_face_read_is_confirmed_from_the_leak_threshold_of_opportunities():
    assert LEAK_THRESHOLD == 8
    assert status_for("faced_bet.continue", 7, 0) == TENTATIVE
    assert status_for("faced_bet.continue", 8, 0) == CONFIRMED
    assert status_for("faced_bet.fold.river", 8, 0) == CONFIRMED
    assert status_for("checked_to.bet", 7, 0) == TENTATIVE
    assert status_for("checked_to.bet.flop", 9, 0) == CONFIRMED


def test_a_hand_frequency_read_needs_the_hand_threshold_before_it_is_confirmed():
    assert HAND_FREQUENCY_THRESHOLD == 20
    assert status_for("preflop.vpip", 19, 0) == TENTATIVE
    assert status_for("preflop.vpip", 20, 0) == CONFIRMED
    assert status_for("preflop.no_raise", 8, 0) == TENTATIVE
    assert status_for("showdown.reached", 19, 0) == TENTATIVE


def test_a_read_is_confirmed_only_while_against_is_at_most_a_fifth_of_for():
    assert MAX_AGAINST_SHARE == 0.2
    assert status_for("faced_bet.continue", 10, 2) == CONFIRMED
    assert status_for("faced_bet.continue", 10, 3) == TENTATIVE
    assert status_for("preflop.vpip", 25, 5) == CONFIRMED
    assert status_for("preflop.vpip", 25, 6) == TENTATIVE


def test_the_harness_sets_status_from_the_tally_whatever_status_the_model_wrote():
    tally = station_tally()
    folds = tally.counts("faced_bet.fold")
    claimed = Notes((
        Hypothesis("never folds to bets", *tally.counts("faced_bet.continue"), "faced_bet.continue", TENTATIVE),
        Hypothesis("folds to bets", *folds, "faced_bet.fold", CONFIRMED),
    ))

    statuses = [h.status for h in verify(claimed, tally).notes.hypotheses]

    assert statuses == [CONFIRMED, TENTATIVE]
