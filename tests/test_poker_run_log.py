"""Tests for per-decision / per-hand poker JSONL logging (poker/run_log.py)."""

import json

from poker.engine import play_hand, play_match
from poker.run_log import DECISION_FIELDS, HAND_FIELDS, PokerRunWriter, decision_rows, hand_row, record_from_rows


class ScriptedPlayer:
    """Returns a fixed list of choices, then checks if it can, else calls."""

    def __init__(self, choices=()):
        self.choices = list(choices)

    def decide(self, state):
        if self.choices:
            return self.choices.pop(0)
        names = [item.action for item in state.menu]
        return "check" if "check" in names else "call"


def heads_up(button=None, big_blind=None):
    return {"hero": button or ScriptedPlayer(), "villain": big_blind or ScriptedPlayer()}


def test_a_hand_row_has_every_field_and_round_trips_through_json():
    record = play_hand(seed=3, players=heads_up(ScriptedPlayer(["raise_pot"])), button="hero", hand_number=4)
    row = json.loads(json.dumps(hand_row(record)))

    assert list(row) == HAND_FIELDS
    assert row["seed"] == 3 and row["hand_number"] == 4
    assert row["seats"] == {"button": "hero", "big_blind": "villain"}
    assert row["actions"][0] == {"street": "preflop", "seat": "button", "action": "raise_pot", "amount": 6}
    assert row["chip_delta"]["hero"] == -row["chip_delta"]["villain"]
    assert row["num_decisions"] == len(record.decisions)


def test_decision_rows_log_the_state_the_menu_the_choice_and_the_fallback_and_clamp_flags():
    # Pot raises to 6, 18, 54, 162; then the button's raises clamp to all-in, it answers with the
    # hidden raise_pot (applied as the all-in), and the big blind gives an answer not on the menu.
    button = ScriptedPlayer(["raise_pot", "raise_pot", "raise_pot"])
    big_blind = ScriptedPlayer(["raise_pot", "raise_pot", "shove"])
    record = play_hand(seed=1, players=heads_up(button, big_blind), button="hero", hand_number=2)
    rows = json.loads(json.dumps(decision_rows(record)))

    assert [list(row) for row in rows] == [DECISION_FIELDS] * len(rows)
    assert [row["decision_index"] for row in rows] == list(range(len(rows)))
    first = rows[0]
    assert (first["seed"], first["hand_number"], first["player"], first["seat"], first["street"]) == (1, 2, "hero", "button", "preflop")
    assert first["menu"][1] == {"action": "call", "amount": 1}
    assert (first["choice"], first["action"], first["amount"], first["fallback"], first["clamped"]) == ("raise_pot", "raise_pot", 6, False, False)

    shove = rows[4]
    assert (shove["choice"], shove["action"], shove["amount"], shove["fallback"], shove["clamped"]) == (
        "raise_pot", "all_in", 200, False, True,
    )
    assert shove["clamps"] == [
        {"action": "raise_half_pot", "requested": 324, "actual": 200},
        {"action": "raise_pot", "requested": 486, "actual": 200},
    ]
    bad = rows[5]
    assert (bad["choice"], bad["action"], bad["fallback"], bad["clamped"], bad["clamps"]) == ("shove", "fold", True, False, [])


def test_the_clamped_flag_and_count_mean_the_applied_action_was_clamped_not_just_that_the_menu_had_clamps():
    # Facing 162 the pot raises clamp to all-in, but the button just calls.
    button, big_blind = ScriptedPlayer(["raise_pot", "raise_pot", "call"]), ScriptedPlayer(["raise_pot", "raise_pot"])
    record = play_hand(seed=1, players=heads_up(button, big_blind), button="hero")

    call = decision_rows(record)[4]
    assert (call["action"], call["clamped"], len(call["clamps"])) == ("call", False, 2)
    assert hand_row(record)["num_clamped"] == 0


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_the_writer_appends_each_hands_decision_rows_then_its_hand_row(tmp_path):
    hands = play_match(seeds=[1, 2], players=heads_up())
    writer = PokerRunWriter(tmp_path / "run")
    for hand in hands:
        writer.write_hand(hand)

    hand_lines = read_jsonl(tmp_path / "run" / "hands.jsonl")
    decision_lines = read_jsonl(tmp_path / "run" / "decisions.jsonl")
    assert [row["hand_number"] for row in hand_lines] == [0, 1, 2, 3]
    assert len(decision_lines) == sum(len(hand.decisions) for hand in hands)
    assert writer.completed_hands() == {0, 1, 2, 3}


def test_reopening_a_run_drops_a_partial_line_and_decisions_of_a_hand_that_never_finished(tmp_path):
    hands = play_match(seeds=[1], players=heads_up())
    writer = PokerRunWriter(tmp_path)
    writer.write_hand(hands[0])
    with open(tmp_path / "decisions.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(decision_rows(hands[1])[0]) + "\n")
        f.write('{"seed": 1, "hand_nu')

    reopened = PokerRunWriter(tmp_path)

    assert reopened.completed_hands() == {0}
    assert {row["hand_number"] for row in read_jsonl(tmp_path / "decisions.jsonl")} == {0}


def test_a_hand_record_is_rebuilt_exactly_from_its_logged_hand_and_decision_rows():
    # Raises, a clamp and a fallback, so every nested field has something in it.
    record = play_hand(seed=3, players=heads_up(ScriptedPlayer(["raise_pot"] * 6), ScriptedPlayer(["raise_pot"] * 3 + ["bet"])),
                       button="hero", hand_number=4)
    hand = json.loads(json.dumps({"run_id": "r", **hand_row(record)}))
    decisions = json.loads(json.dumps([{"run_id": "r", **row, "prompt": None} for row in decision_rows(record)]))

    assert record_from_rows(hand, decisions) == record


def test_memory_events_are_appended_to_memory_jsonl_and_a_partial_last_line_is_dropped_on_reopen(tmp_path):
    writer = PokerRunWriter(tmp_path)
    assert writer.memory_rows() == [] and not (tmp_path / "memory.jsonl").exists()
    writer.write_memory({"notes_version": 0, "hand_number": 5})
    with open(tmp_path / "memory.jsonl", "a", encoding="utf-8") as f:
        f.write('{"notes_version": 1, "hand_nu')

    reopened = PokerRunWriter(tmp_path)

    assert reopened.memory_rows() == [{"notes_version": 0, "hand_number": 5}]
    assert read_jsonl(tmp_path / "memory.jsonl") == [{"notes_version": 0, "hand_number": 5}]
