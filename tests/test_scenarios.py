"""Tests for the scenario set: the list of chart cells and the forced deal (agent/scenarios.py)."""

from collections import Counter

from agent.scenarios import build_scenarios, forced_shoe, scenario_shoe_seed
from blackjack.cards import RANKS, card_value, hand_total, is_blackjack
from blackjack.engine import play_hand
from blackjack.strategy import DEALER_UPCARDS, BasicStrategyPlayer

FULL_SIX_DECK_COUNTS = Counter(RANKS * 4 * 6)


# --- The scenario list --------------------------------------------------------


def test_there_are_330_scenarios_33_rows_times_10_upcards():
    scenarios = build_scenarios()
    assert len(scenarios) == 330
    assert Counter(s.kind for s in scenarios) == {"hard": 150, "soft": 80, "pair": 100}


def test_every_chart_cell_is_covered_exactly_once():
    cells = Counter((s.kind, s.row, s.dealer_upcard) for s in build_scenarios())
    expected = set()
    for upcard in DEALER_UPCARDS:
        expected |= {("hard", total, upcard) for total in range(5, 20)}
        expected |= {("soft", total, upcard) for total in range(13, 21)}
        expected |= {("pair", rank, upcard) for rank in ["2", "3", "4", "5", "6", "7", "8", "9", "10", "A"]}
    assert set(cells) == expected
    assert all(count == 1 for count in cells.values())


def test_scenario_ids_are_unique_and_readable():
    scenarios = build_scenarios()
    ids = [s.scenario_id for s in scenarios]
    assert len(set(ids)) == len(ids)
    assert "hard16_vs_10" in ids
    assert "soft18_vs_9" in ids
    assert "pair8_vs_A" in ids
    assert "pairA_vs_6" in ids


def test_hard_hands_are_never_pairs_and_have_the_right_total():
    for s in build_scenarios():
        if s.kind != "hard":
            continue
        first, second = s.player_cards
        assert card_value(first) != card_value(second), s.scenario_id
        assert "A" not in s.player_cards
        assert hand_total(list(s.player_cards)) == (s.row, False)


def test_hard_compositions_follow_the_documented_rule():
    by_total = {s.row: s.player_cards for s in build_scenarios() if s.kind == "hard"}
    # A 10 whenever the total allows it (12-19), otherwise 2 plus the rest (5-11).
    assert by_total[16] == ("10", "6")
    assert by_total[12] == ("10", "2")
    assert by_total[19] == ("10", "9")
    assert by_total[11] == ("2", "9")
    assert by_total[9] == ("2", "7")
    assert by_total[5] == ("2", "3")


def test_soft_and_pair_hands_have_the_right_cards():
    scenarios = {s.scenario_id: s for s in build_scenarios()}
    assert scenarios["soft13_vs_2"].player_cards == ("A", "2")
    assert scenarios["soft20_vs_A"].player_cards == ("A", "9")
    assert scenarios["pair10_vs_5"].player_cards == ("10", "10")
    assert scenarios["pairA_vs_A"].player_cards == ("A", "A")
    for s in scenarios.values():
        if s.kind == "soft":
            assert hand_total(list(s.player_cards)) == (s.row, True)


def test_scenario_list_is_deterministic():
    assert build_scenarios() == build_scenarios()


# --- The forced deal ----------------------------------------------------------


def test_forced_shoe_deals_the_scenario_cards_and_upcard():
    for s in build_scenarios():
        shoe = forced_shoe(s, run_seed=2026)
        # Deal order: player, dealer upcard, player, dealer hole.
        assert (shoe[0], shoe[2]) == s.player_cards
        assert shoe[1] == s.dealer_upcard


def test_dealer_never_has_blackjack_in_any_scenario():
    for s in build_scenarios():
        for run_seed in (1, 2026):
            shoe = forced_shoe(s, run_seed)
            assert not is_blackjack([shoe[1], shoe[3]]), s.scenario_id


def test_forced_shoe_keeps_realistic_six_deck_card_counts():
    for s in build_scenarios():
        assert Counter(forced_shoe(s, 2026)) == FULL_SIX_DECK_COUNTS


def test_forced_shoe_is_reproducible_and_depends_on_seed_and_scenario():
    s = build_scenarios()[0]
    other = build_scenarios()[1]
    assert forced_shoe(s, 2026) == forced_shoe(s, 2026)
    assert forced_shoe(s, 2026)[4:] != forced_shoe(s, 7)[4:]
    assert forced_shoe(s, 2026)[4:] != forced_shoe(other, 2026)[4:]
    assert scenario_shoe_seed(2026, "hard16_vs_10") == "scenario-2026-hard16_vs_10"


def test_every_scenario_asks_for_a_first_decision_on_its_own_cell():
    player = BasicStrategyPlayer()
    for s in build_scenarios():
        record = play_hand(player, 2026, 1, shoe=forced_shoe(s, 2026))
        assert not record.dealer_blackjack and not record.player_blackjack
        first = record.decisions[0].state
        assert first.player_cards == s.player_cards
        assert first.dealer_upcard == s.dealer_upcard
        assert first.is_pair == (s.kind == "pair")
        assert first.is_soft == (s.kind == "soft" or s.player_cards == ("A", "A"))
