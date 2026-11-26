"""Tests for poker memory: the opponent tally, notes and hypotheses, the rewrite prompt and parser,
harness-side count checks and status gates, the decision-time notes block, and MemoryEvent logging.

Hands are played with scripted players through poker.engine.play_hand, so every HandRecord
is real engine output. The model is always "hero"; the opponent is "villain".
"""

import dataclasses
import json
import re

from poker.bots import make_bot
from poker.engine import play_duplicate, play_hand, play_match
from poker.memory import (
    CONFIRMED,
    HAND_FREQUENCY_THRESHOLD,
    LEAK_THRESHOLD,
    MAX_AGAINST_SHARE,
    NOTES_BLOCK_CHAR_CAP,
    TENTATIVE,
    WORD_BUDGET,
    Hypothesis,
    MemoryState,
    Notes,
    OpponentTally,
    build_rewrite_prompt,
    parse_line,
    parse_rewrite,
    render_hand,
    render_notes_block,
    status_for,
    verify,
)
from poker.runner import match_seeds


class ScriptedPlayer:
    """Returns a fixed list of choices, then checks if it can, else calls."""

    def __init__(self, choices=()):
        self.choices = list(choices)

    def decide(self, state):
        if self.choices:
            return self.choices.pop(0)
        names = [item.action for item in state.menu]
        return "check" if "check" in names else "call"


class Aggressor(ScriptedPlayer):
    """Bets or raises pot whenever it can, else calls."""

    def decide(self, state):
        names = [item.action for item in state.menu]
        return "raise_pot" if "raise_pot" in names else "call"


def station_match():
    """40 hands (20 duplicate pairs) of an always-raising hero against the calling station."""
    return play_match(match_seeds(7, 20), {"hero": Aggressor(), "villain": make_bot("calling_station")})

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


def test_over_a_40_hand_match_against_the_calling_station_the_tally_shows_it_folded_to_no_bets():
    records = station_match()

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
    return tally_of(*station_match())


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


# ---------- Rewrite prompt ----------


def test_a_raw_hand_renders_compactly_from_the_models_view_with_the_opponents_cards_only_at_showdown():
    folded = hand(seed=2, hand_number=4, hero=["call", "raise_pot"], villain=["check", "check", "fold"])
    shown = hand(seed=1, hand_number=5)

    folded_text = render_hand(folded, "hero")
    shown_text = render_hand(shown, "hero")

    assert folded_text.startswith("hand 4: you on the button with " + " ".join(folded.hole_cards["hero"]))
    assert "opp check, you raise_pot 4, opp fold" in folded_text
    assert not any(card in folded_text for card in folded.hole_cards["villain"])
    assert f"result: you {folded.chip_delta['hero']:+d}" in folded_text
    assert "opp showed " + " ".join(shown.hole_cards["villain"]) in shown_text


def test_the_rewrite_prompt_shows_the_labelled_old_notes_the_tally_the_last_hands_and_the_output_format():
    records = [hand(seed=s, hand_number=s) for s in range(7)]
    tally = tally_of(*records)

    prompt = build_rewrite_prompt(PREVIOUS, tally, records[-5:], "hero")

    assert "previous notes; revise or discard based on the counts below" in prompt.lower()
    assert PREVIOUS.hypotheses[0].cited_line() in prompt
    assert tally.render() in prompt
    for record in records[-5:]:
        assert render_hand(record, "hero") in prompt
    assert render_hand(records[0], "hero") not in prompt
    assert "at most 3" in prompt
    assert "<what the opponent does> | key <tally key> | for <N> | against <M>" in prompt
    assert "rewrite" in prompt.lower() and "in full" in prompt.lower()


def test_the_first_rewrite_prompt_says_there_are_no_previous_notes():
    prompt = build_rewrite_prompt(Notes(), tally_of(hand()), [hand()], "hero")

    assert "(none yet)" in prompt


# ---------- Decision-time notes block ----------


def test_the_notes_block_lists_each_hypothesis_line_and_says_tentative_reads_only_nudge_play():
    notes = Notes((
        Hypothesis("never folds to bets", 9, 0, "faced_bet.continue", CONFIRMED),
        Hypothesis("plays every hand", 6, 0, "preflop.vpip", TENTATIVE),
    ))

    block = render_notes_block(notes)

    assert "never folds to bets | for 9 | against 0 | CONFIRMED" in block
    assert "plays every hand | for 6 | against 0 | TENTATIVE" in block
    assert "TENTATIVE reads should only nudge your play" in block


def test_the_notes_block_never_exceeds_its_character_cap_and_keeps_the_nudge_line():
    long_text = "x" * 400
    notes = Notes(tuple(Hypothesis(long_text, 9, 0, "faced_bet.call", TENTATIVE) for _ in range(3)))

    block = render_notes_block(notes)

    assert len(block) <= NOTES_BLOCK_CHAR_CAP
    assert "TENTATIVE reads should only nudge your play" in block


def test_with_no_notes_yet_the_notes_block_is_empty():
    assert render_notes_block(Notes()) == ""


# ---------- MemoryState ----------


def duplicate_pair(seed=1, first=0):
    """Both deals of one seeded deck, seats swapped, hero on the button first."""
    players = {"hero": ScriptedPlayer(), "villain": ScriptedPlayer()}
    return play_duplicate(seed, players, first_button="hero", first_hand_number=first)


def shows_any_card(text, cards):
    return any(re.search(rf"\b{card}\b", text) for card in cards)


def test_the_first_deal_of_a_duplicate_pair_stays_pending_and_leaks_nothing_into_memory():
    first, _ = duplicate_pair()
    assert first.showdown  # so it has showdown cards that could leak
    memory = MemoryState("hero")

    memory.observe(first)

    assert memory.is_pending(first.hand_number)
    assert memory.tally.hands == 0 and memory.tally.snapshot()["counts"] == {}
    prompt = memory.rewrite_prompt()
    assert not shows_any_card(prompt, first.board + first.hole_cards["villain"] + first.hole_cards["hero"])
    assert memory.notes_block() == ""


def test_once_the_second_deal_of_the_pair_is_observed_both_hands_are_committed():
    first, second = duplicate_pair()
    memory = MemoryState("hero")

    memory.observe(first)
    memory.observe(second)

    assert not memory.is_pending(first.hand_number) and not memory.is_pending(second.hand_number)
    assert memory.tally.hands == 2
    prompt = memory.rewrite_prompt()
    assert render_hand(first, "hero") in prompt and render_hand(second, "hero") in prompt


def test_a_rewrite_is_due_each_time_the_committed_hands_pass_another_five_and_not_again_until_it_is_applied():
    records = play_match(match_seeds(3, 10), {"hero": ScriptedPlayer(), "villain": ScriptedPlayer()})
    memory = MemoryState("hero")
    due_after = []

    for record in records:
        memory.observe(record)
        if memory.due():
            due_after.append(record.hand_number)
            assert memory.due()  # stays due until the rewrite is applied
            memory.apply_rewrite("")

    # Pairs commit two hands at a time: 6 committed passes 5, 10 reaches 10, 16 passes 15, 20.
    assert due_after == [5, 9, 15, 19]


def test_a_new_memory_state_starts_empty():
    memory = MemoryState("hero")

    assert memory.tally.hands == 0
    assert memory.notes == Notes()
    assert not memory.due()
    assert memory.notes_block() == ""


# ---------- MemoryEvent logging ----------


def station_memory():
    """MemoryState after a 40-hand match where the calling station never folded."""
    memory = MemoryState("hero")
    for record in station_match():
        memory.observe(record)
    return memory


def test_applying_a_rewrite_logs_old_raw_parsed_and_verified_notes_the_tally_and_the_flags_as_json():
    memory = station_memory()
    true_counts = memory.tally.counts("faced_bet.continue")
    response = "Notes:\nnever folds to bets | key faced_bet.continue | for 3 | against 0 | TENTATIVE\nbluffs a lot | for 5 | against 1"

    event = memory.apply_rewrite(response)

    logged = json.loads(event.to_json())
    assert logged["hand_number"] == 39 and logged["hands_seen"] == 40
    assert logged["old_notes"] == []
    assert logged["raw_response"] == response
    assert [h["for_count"] for h in logged["parsed_notes"]] == [3, 5]
    assert logged["verified_notes"][0] == {
        "text": "never folds to bets", "for_count": true_counts[0], "against_count": true_counts[1],
        "opportunity_key": "faced_bet.continue", "status": CONFIRMED,
    }
    assert logged["verified_notes"][1]["status"] == TENTATIVE
    assert logged["tally"] == memory.tally.snapshot()
    assert logged["flags"] == {
        "count_mismatch": True, "unverifiable": True, "parse_failed": False, "truncated": False,
        "junk_lines": True, "dropped_lines": False,
    }
    assert logged["count_mismatches"][0]["cited"] == [3, 0]
    assert logged["unverifiable"] == ["bluffs a lot"]
    assert logged["junk_lines"] == ["Notes:"]
    assert memory.notes == Notes(tuple(Hypothesis(**h) for h in logged["verified_notes"]))
    assert "never folds to bets | for" in memory.notes_block()


def test_a_rewrite_that_does_not_parse_keeps_the_old_notes_unchanged_and_logs_parse_failed():
    memory = station_memory()
    memory.apply_rewrite("never folds to bets | key faced_bet.continue | for 1 | against 0")
    kept = memory.notes

    event = memory.apply_rewrite("I have no idea.")

    assert memory.notes == kept
    assert event.flags["parse_failed"] and not event.flags["count_mismatch"]
    assert event.old_notes == event.verified_notes == [dataclasses.asdict(h) for h in kept.hypotheses]
