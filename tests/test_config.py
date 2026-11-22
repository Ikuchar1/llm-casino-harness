"""Tests for the named ablation configs in agent/config.py."""

import pytest

from agent.config import BASELINE, CONFIG_NAMES, CONFIGS, get_config


def test_the_six_plan_configs_exist_in_order():
    assert CONFIG_NAMES == ["baseline", "prob", "prob_strat", "prob_strat_self", "strat", "self"]


@pytest.mark.parametrize(
    "name, prob, strat, self_eval",
    [
        ("baseline", False, False, False),
        ("prob", True, False, False),
        ("prob_strat", True, True, False),
        ("prob_strat_self", True, True, True),
        ("strat", False, True, False),
        ("self", False, False, True),
    ],
)
def test_each_config_switches_on_the_planned_components(name, prob, strat, self_eval):
    config = get_config(name)
    assert config.name == name
    assert (config.probability_tool, config.strategy_info, config.self_evaluation) == (prob, strat, self_eval)
    assert config.memory is False  # memory is poker-only


def test_baseline_name_gives_the_baseline_constant():
    assert get_config("baseline") is BASELINE
    assert CONFIGS["baseline"] is BASELINE


def test_unknown_config_name_is_rejected():
    with pytest.raises(ValueError, match="unknown harness config"):
        get_config("memory")
