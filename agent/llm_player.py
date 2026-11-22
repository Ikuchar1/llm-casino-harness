"""The LLM player: asks a model for each decision and parses its reply.

It plugs into blackjack.engine.play_hand like any other Player. For an invalid
reply it returns None; the engine rejects None, stands for the player, and marks
the decision invalid. The player keeps a DecisionDetail for every decision
(prompts, raw reply, parse result, timing) so the run log can record them.

Harness components (agent/config.py):
- probability tool: an odds block in the user prompt (agent/prompt.py);
- strategy information: the principles (agent/strategy_info.py) appended to the
  system prompt after one blank line;
- self-evaluation: after the first reply, the same conversation continues with a
  generic re-check (agent/prompt.recheck_prompt). The final answer is returned and
  graded. If the second reply is invalid the first answer is kept, so the decision
  is invalid only when both replies are.
"""

from dataclasses import dataclass
from typing import Any, Optional

from agent.config import BASELINE, HarnessConfig
from agent.ollama_client import ChatClient
from agent.parser import parse_action
from agent.prompt import SELF_EVAL_VERSION, build_system_prompt, build_user_prompt, recheck_prompt
from agent.strategy_info import STRATEGY_INFO_VERSION, principles_block
from blackjack.engine import DecisionState
from blackjack.rules import DEFAULT_RULES, RuleSet

# Harness components the player can run. A config that switches on anything else
# raises NotImplementedError (memory is poker-only).
BUILT_COMPONENTS = {"probability_tool", "strategy_info", "self_evaluation"}


@dataclass
class SelfEvalDetail:
    """Both answers of a self-evaluation decision (the run log adds first_correct and flipped)."""

    first_raw: str
    first_action: Optional[str]  # None when the first reply was invalid
    first_invalid_reason: Optional[str]
    recheck_prompt: str
    second_raw: str
    second_action: Optional[str]  # None when the second reply was invalid
    second_invalid_reason: Optional[str]
    final_action: Optional[str]  # second if valid, else first; None only if both were invalid
    done_reason: Optional[str]  # second call
    eval_count: Optional[int]  # second call
    latency_s: float  # second call


@dataclass
class DecisionDetail:
    """What the LLM side of one decision looked like.

    With self-evaluation, parsed_action and invalid_reason describe the final (graded)
    answer; raw_response, marker_words, done_reason, eval_count and latency_s are the
    first call's, and the second call is in self_eval.
    """

    system_prompt: str
    user_prompt: str
    raw_response: str
    parsed_action: Optional[str]  # None when the reply was invalid
    invalid_reason: Optional[str]
    marker_words: list[str]
    done_reason: Optional[str]
    eval_count: Optional[int]
    latency_s: float
    self_eval: Optional[SelfEvalDetail] = None  # only for self-evaluation configs


def component_versions(config: HarnessConfig) -> dict[str, Any]:
    """The component text versions a resumed run must match (None = component off, key absent).

    Used by the run scripts' resume check, so a run started under older strategy
    information or re-check texts is never silently continued under newer ones.
    """
    return {
        "strategy_info_version": STRATEGY_INFO_VERSION if config.strategy_info else None,
        "self_eval_version": SELF_EVAL_VERSION if config.self_evaluation else None,
    }


class LLMPlayer:
    """A blackjack Player backed by a chat model."""

    def __init__(self, client: ChatClient, config: HarnessConfig = BASELINE, rules: RuleSet = DEFAULT_RULES):
        unbuilt = [name for name in config.enabled_components() if name not in BUILT_COMPONENTS]
        if unbuilt:
            raise NotImplementedError(f"Harness components not built yet: {', '.join(unbuilt)}")
        self.client = client
        self.config = config
        self.rules = rules
        system_prompt = build_system_prompt(rules)
        if config.strategy_info:
            system_prompt += "\n\n" + principles_block()
        self.system_prompt = system_prompt
        self._details: list[DecisionDetail] = []

    def decide(self, state: DecisionState) -> Optional[str]:
        """Ask the model, parse the reply, and return a legal action or None (invalid)."""
        user_prompt = build_user_prompt(state, self.config, self.rules)
        # Errors from the client (e.g. Ollama down) propagate and stop the run.
        reply = self.client.chat(self.system_prompt, user_prompt)
        result = parse_action(reply.content, state.legal_actions, reply.done_reason)
        final_action, final_reason = result.action, result.invalid_reason
        self_eval = None
        if self.config.self_evaluation:
            self_eval = self._re_check(state, user_prompt, reply.content, result.action, result.invalid_reason)
            final_action = self_eval.final_action
            final_reason = None if final_action is not None else result.invalid_reason
        self._details.append(
            DecisionDetail(
                system_prompt=self.system_prompt,
                user_prompt=user_prompt,
                raw_response=reply.content,
                parsed_action=final_action,
                invalid_reason=final_reason,
                marker_words=result.marker_words,
                done_reason=reply.done_reason,
                eval_count=reply.eval_count,
                latency_s=reply.latency_s,
                self_eval=self_eval,
            )
        )
        return final_action

    def _re_check(
        self, state: DecisionState, user_prompt: str, first_raw: str, first_action: Optional[str],
        first_reason: Optional[str],
    ) -> SelfEvalDetail:
        """Continue the conversation with the re-check prompt and pick the final answer."""
        prompt = recheck_prompt(first_action)
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_prompt},
            {"role": "assistant", "content": first_raw},
            {"role": "user", "content": prompt},
        ]
        reply = self.client.chat_messages(messages)
        second = parse_action(reply.content, state.legal_actions, reply.done_reason)
        return SelfEvalDetail(
            first_raw=first_raw,
            first_action=first_action,
            first_invalid_reason=first_reason,
            recheck_prompt=prompt,
            second_raw=reply.content,
            second_action=second.action,
            second_invalid_reason=second.invalid_reason,
            final_action=second.action if second.action is not None else first_action,
            done_reason=reply.done_reason,
            eval_count=reply.eval_count,
            latency_s=reply.latency_s,
        )

    def run_metadata(self) -> dict[str, Any]:
        """Run-level facts about this player's prompts, for metadata.json.

        The system prompt always; the strategy information and self-evaluation versions
        (and the re-check texts) only when those components are on.
        """
        metadata: dict[str, Any] = {"system_prompt": self.system_prompt}
        if self.config.strategy_info:
            metadata["strategy_info_version"] = STRATEGY_INFO_VERSION
        if self.config.self_evaluation:
            metadata["self_eval_version"] = SELF_EVAL_VERSION
            metadata["recheck_prompts"] = {"valid": recheck_prompt("<first action>"), "invalid": recheck_prompt(None)}
        return metadata

    def take_hand_details(self) -> list[DecisionDetail]:
        """Return the details collected since the last call, and clear them.

        Call once after each hand; the list lines up one-to-one with record.decisions.
        """
        details, self._details = self._details, []
        return details
