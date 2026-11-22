"""Reads one run directory (decisions.jsonl, hands.jsonl, metadata.json) into a Run."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

NOT_LOGGED = "not logged"


@dataclass
class Run:
    """Everything logged for one run."""

    name: str  # the run directory's name, e.g. "smoke_seed2026_v2"
    metadata: dict[str, Any]
    decisions: list[dict[str, Any]]
    hands: list[dict[str, Any]]

    @property
    def run_id(self) -> str:
        return self.metadata.get("run_id", self.name)

    @property
    def prompt_version(self) -> str:
        """The prompt version, or "not logged" for runs from before it was recorded (v1)."""
        return self.metadata.get("prompt_version") or NOT_LOGGED


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    """One dict per non-blank line."""
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def load_run(run_dir: Path | str) -> Run:
    """Load a run and check that its decisions all used one prompt version.

    Runs made with different prompt versions, or scenario and natural decisions,
    must never be combined, so a run directory that mixes them is refused.
    """
    run_dir = Path(run_dir)
    metadata = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
    decisions = read_jsonl(run_dir / "decisions.jsonl")
    hands = read_jsonl(run_dir / "hands.jsonl")

    versions = {row.get("prompt_version") for row in decisions}
    if len(versions) > 1:
        raise ValueError(f"{run_dir} mixes prompt versions {sorted(map(str, versions))}; analyze them separately")

    run_types = {row.get("run_type") or "natural" for row in decisions}
    if len(run_types) > 1:
        raise ValueError(f"{run_dir} mixes scenario and natural decisions; analyze them separately")

    return Run(name=run_dir.name, metadata=metadata, decisions=decisions, hands=hands)
