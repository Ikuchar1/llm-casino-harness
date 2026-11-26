"""The poker LLM player: asks a model for each decision and parses its reply.

It plugs into poker.engine.play_hand like any other Player. The client is the shared
Ollama client (agent/ollama_client.py), whose locked options decode at temperature 0.
The player keeps a PokerDecisionDetail for every decision (prompt, raw reply, parse
result, timing); the runner merges them into the decision log rows.

When the reply names a real action that is off the menu, decide() still returns that
name: the engine then applies its fallback (check, or fold if check is illegal), or the
item a dropped pot raise collapsed into. An unparseable or cut-off reply returns None (fallback).
"""

from dataclasses import dataclass
from typing import Any, Optional

from agent.config import HarnessConfig
from agent.ollama_client import ChatClient
from poker.engine import DecisionState
from poker.parser import PARSER_VERSION, parse_choice
from poker.prompt import PROMPT_VERSION, build_system_prompt, build_user_prompt

# The poker setups (docs/poker-plan.md, decision 7), as harness configs. Full tools
# (equity, hand chart, self-check) are not built yet, so they have no setup here.
PLAIN = HarnessConfig(name="plain")
MEMORY = HarnessConfig(name="memory", memory=True)
SETUPS: dict[str, HarnessConfig] = {setup.name: setup for setup in (PLAIN, MEMORY)}

# Harness components this player can run; anything else raises NotImplementedError.
BUILT_COMPONENTS: set[str] = set()


@dataclass
class PokerDecisionDetail:
    """What the LLM side of one decision looked like."""

    user_prompt: str
    raw_response: str
    parsed_action: Optional[str]  # the menu action, None when parsing failed
    parse_status: str  # "ok", "mapped", "off_menu", "unparseable" or "truncated_no_action"
    parse_method: Optional[str]  # "json", "action_line", "loose", None
    named_action: Optional[str]  # what the reply named, even off the menu
    mapping: Optional[str]  # e.g. "check/call -> call"
    done_reason: Optional[str]
    eval_count: Optional[int]
    latency_s: float


class PokerLLMPlayer:
    """A poker Player backed by a chat model."""

    def __init__(self, client: ChatClient, config: HarnessConfig = PLAIN):
        unbuilt = [name for name in config.enabled_components() if name not in BUILT_COMPONENTS]
        if unbuilt:
            raise NotImplementedError(f"Harness components not built yet: {', '.join(unbuilt)}")
        self.client = client
        self.config = config
        self.system_prompt = build_system_prompt()
        # MEMORY HOOK: the opponent notes block for the next decisions (unused until memory is built).
        self.notes: Optional[str] = None
        self._details: list[PokerDecisionDetail] = []

    def decide(self, state: DecisionState) -> Optional[str]:
        """Ask the model and return its menu action, the off-menu action it named, or None."""
        user_prompt = build_user_prompt(state, notes=self.notes)
        # Errors from the client (e.g. Ollama down) propagate and stop the run.
        reply = self.client.chat(self.system_prompt, user_prompt)
        result = parse_choice(reply.content, state.menu, reply.done_reason)
        self._details.append(PokerDecisionDetail(
            user_prompt=user_prompt,
            raw_response=reply.content,
            parsed_action=result.action,
            parse_status=result.status,
            parse_method=result.method,
            named_action=result.named,
            mapping=result.mapping,
            done_reason=reply.done_reason,
            eval_count=reply.eval_count,
            latency_s=reply.latency_s,
        ))
        return result.action if result.action is not None else result.named

    def run_metadata(self) -> dict[str, Any]:
        """Run-level facts about this player's prompts, for metadata.json."""
        return {"system_prompt": self.system_prompt, "prompt_version": PROMPT_VERSION, "parser_version": PARSER_VERSION}

    def take_hand_details(self) -> list[PokerDecisionDetail]:
        """Return the details collected since the last call, and clear them."""
        details, self._details = self._details, []
        return details
