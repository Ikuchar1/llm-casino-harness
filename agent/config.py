"""Harness configurations: which harness components are switched on for a run.

The baseline has every component off. Later ablation configs (probability tool,
strategy information, memory, self-evaluation) will be added here as more
HarnessConfig constants; the LLM player reads the flags.
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
