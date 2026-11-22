"""Harness configurations: which harness components are switched on for a run.

The baseline has every component off. The six blackjack ablation configs from
docs/ablation-plan.md are named constants below; pick one by name with
get_config() (the run scripts' --config flag). The LLM player reads the flags.
Memory is poker-only, so it is off in every blackjack config.
"""

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class HarnessConfig:
    """One harness configuration. Frozen so a run's config can't change mid-run."""

    name: str
    probability_tool: bool = False
    strategy_info: bool = False
    memory: bool = False
    self_evaluation: bool = False

    def flags(self) -> dict[str, bool]:
        """The on/off state of each harness component (everything except the name)."""
        values = asdict(self)
        del values["name"]
        return values

    def enabled_components(self) -> list[str]:
        """Names of the components that are switched on."""
        return [name for name, on in self.flags().items() if on]


BASELINE = HarnessConfig(name="baseline")
PROB = HarnessConfig(name="prob", probability_tool=True)
PROB_STRAT = HarnessConfig(name="prob_strat", probability_tool=True, strategy_info=True)
PROB_STRAT_SELF = HarnessConfig(name="prob_strat_self", probability_tool=True, strategy_info=True, self_evaluation=True)
STRAT = HarnessConfig(name="strat", strategy_info=True)
SELF = HarnessConfig(name="self", self_evaluation=True)

CONFIGS: dict[str, HarnessConfig] = {
    config.name: config for config in (BASELINE, PROB, PROB_STRAT, PROB_STRAT_SELF, STRAT, SELF)
}
CONFIG_NAMES = list(CONFIGS)


def get_config(name: str) -> HarnessConfig:
    """The named config, e.g. get_config("prob"). Raises ValueError for an unknown name."""
    try:
        return CONFIGS[name]
    except KeyError:
        raise ValueError(f"unknown harness config {name!r} (choose from {', '.join(CONFIG_NAMES)})") from None
