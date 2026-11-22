"""The LLM player: asks a model for each decision and parses its reply.

It plugs into blackjack.engine.play_hand like any other Player. For an invalid
reply it returns None; the engine rejects None, stands for the player, and marks
the decision invalid. The player keeps a DecisionDetail for every decision
(prompts, raw reply, parse result, timing) so the run log can record them.
"""

from dataclasses import dataclass
from typing import Optional

from agent.config import BASELINE, HarnessConfig
from agent.ollama_client import ChatClient
from agent.parser import parse_action
from agent.prompt import build_system_prompt, build_user_prompt
from blackjack.engine import DecisionState
from blackjack.rules import DEFAULT_RULES, RuleSet


@dataclass
class DecisionDetail:
    """What the LLM side of one decision looked like."""

    system_prompt: str
    user_prompt: str
    raw_response: str
    parsed_action: Optional[str]  # None when the reply was invalid
    invalid_reason: Optional[str]
    marker_words: list[str]
    done_reason: Optional[str]
    eval_count: Optional[int]
    latency_s: float


class LLMPlayer:
    """A blackjack Player backed by a chat model."""

    def __init__(self, client: ChatClient, config: HarnessConfig = BASELINE, rules: RuleSet = DEFAULT_RULES):
        enabled = config.enabled_components()
        if enabled:
            raise NotImplementedError(f"Harness components not built yet: {', '.join(enabled)}")
        self.client = client
        self.config = config
        self.system_prompt = build_system_prompt(rules)
        self._details: list[DecisionDetail] = []

    def decide(self, state: DecisionState) -> Optional[str]:
        """Ask the model, parse the reply, and return a legal action or None (invalid)."""
        user_prompt = build_user_prompt(state)
        # Errors from the client (e.g. Ollama down) propagate and stop the run.
        reply = self.client.chat(self.system_prompt, user_prompt)
        result = parse_action(reply.content, state.legal_actions, reply.done_reason)
        self._details.append(
            DecisionDetail(
                system_prompt=self.system_prompt,
                user_prompt=user_prompt,
                raw_response=reply.content,
                parsed_action=result.action,
                invalid_reason=result.invalid_reason,
                marker_words=result.marker_words,
                done_reason=reply.done_reason,
                eval_count=reply.eval_count,
                latency_s=reply.latency_s,
            )
        )
        return result.action

    def take_hand_details(self) -> list[DecisionDetail]:
        """Return the details collected since the last call, and clear them.

        Call once after each hand; the list lines up one-to-one with record.decisions.
        """
        details, self._details = self._details, []
        return details
