"""Tests for the lenient reply parser (agent/parser.py).

The parser turns a model reply into one legal action, or marks it invalid with a reason.
"""

import pytest

from agent.parser import parse_action

ALL = ("hit", "stand", "double", "split")
NO_SPLIT = ("hit", "stand", "double")
HIT_STAND = ("hit", "stand")


def ok(reply, legal=ALL, done_reason="stop"):
    result = parse_action(reply, legal, done_reason)
    assert result.invalid_reason is None, result
    return result.action


def bad(reply, legal=ALL, done_reason="stop"):
    result = parse_action(reply, legal, done_reason)
    assert result.action is None, result
    return result.invalid_reason


# --- Real replies seen in the timing test -------------------------------------------


def test_real_quirk_bold_inline_with_trailing_period():
    reply = "Given the options and the risk involved, **ACTION: stand**."
    assert ok(reply) == "stand"


def test_real_clean_last_line():
    assert ok("The dealer shows a 6, so I will not risk busting.\n\nACTION: stand") == "stand"


# --- Formatting leniency ---------------------------------------------------------------


@pytest.mark.parametrize(
    "reply, expected",
    [
        ("ACTION: hit", "hit"),
        ("action: HIT", "hit"),
        ("Action: Double", "double"),
        ("ACTION:stand", "stand"),
        ("ACTION : stand", "stand"),
        ("ACTION - split", "split"),
        ("ACTION-split", "split"),
        ("**ACTION:** hit", "hit"),
        ("`ACTION: hit`", "hit"),
        ("__ACTION: double__", "double"),
        ("### ACTION: stand", "stand"),
        ("ACTION: stand!", "stand"),
        ("ACTION: hit.", "hit"),
        ("ACTION: [hit]", "hit"),
        ("ACTION: <stand>", "stand"),
        ("ACTION: hit (the dealer is strong)", "hit"),
        ("ACTION: stand\n\nI stand because the dealer will likely bust.", "stand"),
    ],
)
def test_formatting_variants(reply, expected):
    assert ok(reply) == expected


def test_marker_not_on_last_line_still_counts():
    assert ok("Reasoning...\nACTION: hit\nGood luck to me!") == "hit"


# --- Synonyms ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "reply, expected",
    [
        ("ACTION: stay", "stand"),
        ("ACTION: stand pat", "stand"),
        ("ACTION: hit me", "hit"),
        ("ACTION: take a card", "hit"),
        ("ACTION: double down", "double"),
        ("ACTION: doubledown", "double"),
        ("ACTION: Double Down.", "double"),
        ("ACTION: split", "split"),
    ],
)
def test_synonyms(reply, expected):
    assert ok(reply) == expected


# --- Multiple markers ---------------------------------------------------------------------


def test_multiple_markers_that_agree_are_fine():
    assert ok("ACTION: hit\nOn reflection, yes.\nACTION: hit") == "hit"


def test_multiple_markers_that_agree_via_synonym_are_fine():
    assert ok("ACTION: stay\nACTION: stand") == "stand"


def test_multiple_markers_that_disagree_are_conflicting():
    assert bad("ACTION: hit\nActually no.\nACTION: stand") == "conflicting"


# --- Invalid replies ----------------------------------------------------------------------


def test_no_marker_is_invalid_even_if_an_action_word_appears():
    assert bad("I think the best play is to stand here.") == "no_action"


def test_empty_reply_is_no_action():
    assert bad("") == "no_action"


def test_unknown_word_after_marker():
    assert bad("ACTION: surrender") == "unknown_word"


def test_take_alone_is_unknown():
    assert bad("ACTION: take") == "unknown_word"


def test_marker_with_nothing_after_it():
    assert bad("I will choose wisely.\nACTION:") == "empty_action"


def test_illegal_action_double_on_three_cards():
    assert bad("ACTION: double", legal=HIT_STAND) == "illegal"


def test_illegal_split_when_not_a_pair():
    assert bad("ACTION: split", legal=NO_SPLIT) == "illegal"


def test_truncated_reply_with_no_marker():
    assert bad("Let me think about this carefully. The dealer", done_reason="length") == (
        "truncated_no_action"
    )


def test_truncated_reply_that_already_gave_an_action_is_still_parsed():
    assert ok("ACTION: hit\nNow let me explain at great length why", done_reason="length") == "hit"


def test_unknown_marker_is_ignored_when_another_marker_names_an_action():
    # "action: I" is prose, not a choice; the real marker below it still counts.
    result = parse_action("The best action: I think hitting.\nACTION: hit", ALL, "stop")
    assert result.action == "hit"


def test_result_records_every_word_the_markers_named():
    result = parse_action("ACTION: hit\nACTION: stand", ALL, "stop")
    assert result.marker_words == ["hit", "stand"]


def test_action_inside_a_longer_word_is_not_a_marker():
    assert bad("This transaction: hit or miss.") == "no_action"


# --- Reviewer findings (parser-v2) -----------------------------------------------------


def test_reviewer_same_line_second_marker_recommended_action_dash():
    assert bad("In this situation the recommended action - stand. ACTION: hit") == "conflicting"


def test_reviewer_same_line_second_marker_double_then_hit():
    assert bad("You could double. ACTION: double is risky, so ACTION: hit") == "conflicting"


def test_reviewer_one_marker_hit_or_stand():
    assert bad("ACTION: hit or stand") == "conflicting"


def test_reviewer_one_marker_listing_three_actions():
    assert bad("ACTION: hit, stand, double") == "conflicting"


def test_one_marker_with_fallback_wording_is_conflicting():
    # Accepted trade-off: "double (or hit if not allowed)" names two actions, so it is invalid.
    assert bad("ACTION: double (or hit if not allowed)") == "conflicting"


def test_one_marker_naming_the_same_action_twice_via_synonym_is_fine():
    assert ok("ACTION: stand (stay put, stand pat)") == "stand"


@pytest.mark.parametrize("separator", [" ", "\n", "\n\n"])
def test_result_does_not_depend_on_line_breaks(separator):
    assert bad(f"ACTION: hit{separator}ACTION: stand") == "conflicting"
    assert ok(f"ACTION: hit{separator}ACTION: hit") == "hit"


def test_same_line_markers_each_get_their_own_text():
    result = parse_action("ACTION: hit ACTION: hit", ALL, "stop")
    assert result.marker_words == ["hit", "hit"]


@pytest.mark.parametrize("reply", ["ACTION：stand", "ACTION： stand", "**ACTION：** stand"])
def test_fullwidth_colon_is_a_separator(reply):
    assert ok(reply) == "stand"


def test_truncated_reply_with_partial_marker_word():
    assert bad("Let me reason it out.\nACTION: sta", done_reason="length") == "truncated_no_action"


def test_truncated_reply_with_empty_marker():
    assert bad("Let me reason it out.\nACTION:", done_reason="length") == "truncated_no_action"


def test_untruncated_unknown_word_is_still_unknown_word():
    assert bad("ACTION: sta", done_reason="stop") == "unknown_word"


def test_parser_version_constant():
    from agent.parser import PARSER_VERSION

    assert PARSER_VERSION == "parser-v2"
