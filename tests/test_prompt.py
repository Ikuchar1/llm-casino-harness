"""Tests for the baseline prompt builder (agent/prompt.py) and HarnessConfig."""

import dataclasses

import pytest

from agent.config import BASELINE, HarnessConfig, get_config
from agent.prompt import FORMAT_INSTRUCTION, PROMPT_VERSION, build_system_prompt, build_user_prompt
from blackjack.engine import DecisionState
from blackjack.odds import compute_odds
from blackjack.rules import DEFAULT_RULES


def make_state(**overrides) -> DecisionState:
    values = dict(
        player_cards=("10", "6"),
        total=16,
        is_soft=False,
        is_pair=False,
        dealer_upcard="10",
        legal_actions=("hit", "stand", "double"),
        hand_index=0,
        num_cards=2,
        from_split=False,
    )
    values.update(overrides)
    return DecisionState(**values)


# --- HarnessConfig ---------------------------------------------------------------------


def test_baseline_has_every_component_off():
    assert BASELINE.name == "baseline"
    assert not any([BASELINE.probability_tool, BASELINE.strategy_info, BASELINE.memory, BASELINE.self_evaluation])


def test_config_is_frozen():
    with pytest.raises(dataclasses.FrozenInstanceError):
        BASELINE.memory = True  # type: ignore[misc]


def test_config_flags_lists_every_component():
    assert HarnessConfig("x", memory=True).flags() == {
        "probability_tool": False,
        "strategy_info": False,
        "memory": True,
        "self_evaluation": False,
    }


# --- System prompt ---------------------------------------------------------------------


def test_system_prompt_states_the_rule_set():
    text = build_system_prompt(DEFAULT_RULES)
    for phrase in ["6 decks", "stands on soft 17", "after a split", "once", "one card", "surrender",
                   "insurance", "3 to 2", "1 unit"]:
        assert phrase in text, phrase


def test_system_prompt_ends_with_the_format_instruction():
    text = build_system_prompt(DEFAULT_RULES)
    assert text.rstrip().endswith(FORMAT_INSTRUCTION)
    assert "ACTION: <one of the legal actions>" in FORMAT_INSTRUCTION


def test_format_instruction_asks_for_reasoning_before_the_action():
    # v1's "Think briefly..." produced bare ACTION lines; v2 must ask for reasoning first.
    assert FORMAT_INSTRUCTION.startswith("First explain your reasoning in two or three sentences.")


def test_prompt_version_is_v3():
    # v3 adds the "Dealer checked for blackjack" state line for 10-value and ace upcards.
    assert PROMPT_VERSION == "baseline-v3"


def test_system_prompt_says_the_dealer_peeks():
    text = build_system_prompt(DEFAULT_RULES)
    assert ("When the dealer's upcard is an ace or a 10-value card, the dealer checks for blackjack "
            "before you act; if the dealer has blackjack the hand ends immediately.") in text


def test_system_prompt_for_h17_says_hits_soft_17():
    rules = dataclasses.replace(DEFAULT_RULES, dealer_hits_soft_17=True)
    assert "hits soft 17" in build_system_prompt(rules)


# --- User prompt -----------------------------------------------------------------------


def test_user_prompt_contains_the_state():
    text = build_user_prompt(make_state())
    assert "Your cards: 10, 6" in text
    assert "Your total: hard 16" in text
    assert "Pair: no" in text
    assert "Dealer upcard: 10" in text
    assert "Legal actions: hit, stand, double" in text
    assert "from a split" not in text.lower()


def test_user_prompt_soft_total():
    text = build_user_prompt(make_state(player_cards=("A", "6"), total=17, is_soft=True))
    assert "Your total: soft 17" in text


def test_user_prompt_pair():
    state = make_state(player_cards=("8", "8"), is_pair=True, legal_actions=("hit", "stand", "double", "split"))
    text = build_user_prompt(state)
    assert "Pair: yes" in text
    assert "Legal actions: hit, stand, double, split" in text


def test_user_prompt_split_hand_mentions_the_split():
    state = make_state(player_cards=("8", "3"), total=11, from_split=True, hand_index=1)
    text = build_user_prompt(state)
    assert "This hand came from a split (hand 2 of 2)." in text


def test_user_prompt_unsplittable_pair_is_still_called_a_pair():
    # After the one allowed split, 8,8 can't be split again, but the cards are still a pair.
    state = make_state(player_cards=("8", "8"), from_split=True, is_pair=False)
    assert "Pair: yes" in build_user_prompt(state)


PEEK_LINE = "Dealer checked for blackjack: no blackjack."


@pytest.mark.parametrize("upcard", ["10", "J", "Q", "K", "A"])
def test_user_prompt_says_dealer_has_no_blackjack_under_ten_or_ace(upcard):
    lines = build_user_prompt(make_state(dealer_upcard=upcard)).splitlines()
    assert lines.count(PEEK_LINE) == 1
    assert lines[lines.index(f"Dealer upcard: {upcard}") + 1] == PEEK_LINE


@pytest.mark.parametrize("upcard", ["2", "3", "4", "5", "6", "7", "8", "9"])
def test_user_prompt_has_no_peek_line_under_two_to_nine(upcard):
    text = build_user_prompt(make_state(dealer_upcard=upcard))
    assert "Dealer upcard: " + upcard in text
    assert "checked" not in text.lower()


def test_user_prompt_peek_line_on_a_split_hand():
    state = make_state(player_cards=("8", "3"), total=11, from_split=True, hand_index=1, dealer_upcard="A")
    lines = build_user_prompt(state).splitlines()
    assert lines[-3:] == ["Dealer upcard: A", PEEK_LINE, "Legal actions: hit, stand, double"]


def test_user_prompt_full_text_for_16_vs_k():
    assert build_user_prompt(make_state(dealer_upcard="K")) == (
        "Your cards: 10, 6\n"
        "Your total: hard 16\n"
        "Pair: no\n"
        "Dealer upcard: K\n"
        "Dealer checked for blackjack: no blackjack.\n"
        "Legal actions: hit, stand, double"
    )


@pytest.mark.parametrize("word", ["basic strategy", "probability", "odds", "bust", "recommend", "should", "chart"])
def test_prompts_contain_no_strategy_hints(word):
    text = (build_system_prompt(DEFAULT_RULES) + build_user_prompt(make_state())).lower()
    assert word not in text


# --- Probability tool (prob on/off) ----------------------------------------------------

PROB = get_config("prob")
ODDS_HEADER = "Odds (worked out from the cards left in the shoe):"


@pytest.mark.parametrize("upcard", ["6", "K", "A"])
def test_baseline_config_prompt_is_unchanged(upcard):
    state = make_state(dealer_upcard=upcard)
    assert build_user_prompt(state, BASELINE) == build_user_prompt(state)
    assert ODDS_HEADER not in build_user_prompt(state, BASELINE)


def test_prob_prompt_full_text_for_16_vs_6():
    odds = compute_odds(["10", "6"], "6")
    d = {k: f"{100 * v:.1f}%" for k, v in odds.dealer.items()}
    assert build_user_prompt(make_state(dealer_upcard="6"), PROB) == (
        "Your cards: 10, 6\n"
        "Your total: hard 16\n"
        "Pair: no\n"
        "Dealer upcard: 6\n"
        "\n"
        f"{ODDS_HEADER}\n"
        f"- If you hit once: {100 * odds.bust_if_hit:.1f}% chance to bust.\n"
        f"- Dealer final total: 17: {d[17]}, 18: {d[18]}, 19: {d[19]}, 20: {d[20]}, 21: {d[21]}, "
        f"bust: {d['bust']}.\n"
        f"- If you stand now: win {100 * odds.stand_win:.1f}%, push {100 * odds.stand_push:.1f}%, "
        f"lose {100 * odds.stand_lose:.1f}%.\n"
        "\n"
        "Legal actions: hit, stand, double"
    )


def test_prob_prompt_uses_one_decimal_percentages():
    text = build_user_prompt(make_state(dealer_upcard="6"), PROB)
    assert "- If you hit once: 61.2% chance to bust." in text
    assert "bust: 42.1%." in text


def test_prob_prompt_under_a_ten_says_the_dealer_has_no_blackjack():
    lines = build_user_prompt(make_state(dealer_upcard="K"), PROB).splitlines()
    assert lines[3:5] == ["Dealer upcard: K", PEEK_LINE]
    assert any(line.startswith("- Dealer final total (no blackjack): 17: ") for line in lines)


def test_prob_prompt_soft_hand_cannot_bust():
    state = make_state(player_cards=("A", "6"), total=17, is_soft=True, dealer_upcard="9")
    assert "- If you hit once: 0.0% chance to bust." in build_user_prompt(state, PROB)


def test_prob_prompt_split_hand_keeps_the_split_line_before_the_odds():
    state = make_state(player_cards=("8", "3"), total=11, from_split=True, hand_index=1, dealer_upcard="5")
    lines = build_user_prompt(state, PROB).splitlines()
    assert lines.index("This hand came from a split (hand 2 of 2).") < lines.index(ODDS_HEADER)
    assert lines[-1] == "Legal actions: hit, stand, double"


@pytest.mark.parametrize("phrase", ["basic strategy", "recommend", "should", "chart", "expected value", " ev "])
def test_prob_prompt_gives_odds_but_no_advice_or_ev(phrase):
    text = build_user_prompt(make_state(dealer_upcard="6"), PROB).lower()
    assert phrase not in text
