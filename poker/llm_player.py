"""The poker LLM player: asks a model for each decision and parses its reply.

It plugs into poker.engine.play_hand like any other Player. The client is the shared
Ollama client (agent/ollama_client.py), whose locked options decode at temperature 0.
The player keeps a PokerDecisionDetail for every decision (prompt, raw reply, parse
result, timing); the runner merges them into the decision log rows.

In the full-tools setups every decision gets one more turn in the same conversation,
the generic re-check (poker.self_check); its choice is played if the engine applies it
(a menu action, or an off-menu name like all_in when only fold and call are legal), else
the first answer. The same rule decides whether the first answer counts as usable. With self-evaluation the parse fields describe the answer played,
while raw_response and the call stats are the first call's (the second is in self_check).

When the reply names a real action that is off the menu, decide() still returns that
name: the engine then applies its fallback (check, or fold if check is illegal), or the
item a dropped pot raise collapsed into. An unparseable or cut-off reply returns None (fallback).
"""

from dataclasses import dataclass
from typing import Any, Optional

from agent.config import HarnessConfig
from agent.ollama_client import ChatClient, ChatReply
from poker.engine import DecisionState
from poker.equity_info import EQUITY_SAMPLES, EQUITY_VERSION, EquityInfo, equity_info
from poker.memory import REWRITE_SYSTEM_PROMPT
from poker.parser import PARSER_VERSION, ParseResult, parse_choice
from poker.self_check import SELF_CHECK_VERSION, final_choice, flags, recheck_prompt
from poker.preflop_chart import PREFLOP_CHART_VERSION, chart_lines, chart_play, hand_class, spot
from poker.prompt import PROMPT_VERSION, build_system_prompt, build_user_prompt

# The poker setups (docs/poker-plan.md, decision 7), as harness configs. Full tools are
# equity and pot odds (poker.equity_info), the preflop chart (poker.preflop_chart) and
# the self-check (poker.self_check).
PLAIN = HarnessConfig(name="plain")
MEMORY = HarnessConfig(name="memory", memory=True)
TOOLS = HarnessConfig(name="tools", probability_tool=True, strategy_info=True, self_evaluation=True)
TOOLS_MEMORY = HarnessConfig(name="tools_memory", probability_tool=True, strategy_info=True, memory=True,
                             self_evaluation=True)
SETUPS: dict[str, HarnessConfig] = {setup.name: setup for setup in (PLAIN, MEMORY, TOOLS, TOOLS_MEMORY)}

# Harness components this player can run; anything else raises NotImplementedError.
BUILT_COMPONENTS: set[str] = {"memory", "probability_tool", "strategy_info", "self_evaluation"}


def tools_settings(config: HarnessConfig) -> Optional[dict[str, Any]]:
    """The tool versions a run records and a resume must match (None = no tool on; a key per tool on)."""
    settings = {}
    if config.probability_tool:
        settings["equity_version"] = EQUITY_VERSION
        settings["equity_samples"] = EQUITY_SAMPLES
    if config.strategy_info:
        settings["preflop_chart_version"] = PREFLOP_CHART_VERSION
    if config.self_evaluation:
        settings["self_check_version"] = SELF_CHECK_VERSION
    return settings or None


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
    eval_count: Optional[int]  # tokens generated
    prompt_tokens: Optional[int]  # Ollama's prompt_eval_count (None when not reported)
    latency_s: float
    # The full-tools setups only (None otherwise). tools: what the equity and chart lines
    # showed (_tools). self_check: the first answer, the re-check and its reply (_re_check).
    # flags: poker.self_check.flags() on the first answer, logged only, never shown to the model.
    tools: Optional[dict[str, Any]] = None
    self_check: Optional[dict[str, Any]] = None
    flags: Optional[list[str]] = None


class PokerLLMPlayer:
    """A poker Player backed by a chat model."""

    def __init__(self, client: ChatClient, config: HarnessConfig = PLAIN):
        unbuilt = [name for name in config.enabled_components() if name not in BUILT_COMPONENTS]
        if unbuilt:
            raise NotImplementedError(f"Harness components not built yet: {', '.join(unbuilt)}")
        self.client = client
        self.config = config
        self.system_prompt = build_system_prompt()
        # The opponent notes block for the next decisions; the runner sets it in the memory setup.
        self.notes: Optional[str] = None
        self._details: list[PokerDecisionDetail] = []

    def decide(self, state: DecisionState) -> Optional[str]:
        """Ask the model and return its menu action, the off-menu action it named, or None."""
        info = equity_info(state) if self.config.probability_tool or self.config.self_evaluation else None
        tool_lines, tools_log = self._tools(state, info)
        user_prompt = build_user_prompt(state, notes=self.notes, tools=tool_lines)
        # Errors from the client (e.g. Ollama down) propagate and stop the run.
        reply = self.client.chat(self.system_prompt, user_prompt)
        result = parse_choice(reply.content, state.menu, reply.done_reason)
        choice = result.action if result.action is not None else result.named
        self_check, warnings = None, None
        if self.config.self_evaluation:
            # flags() is a logged-only diagnostic: the re-check stays generic (CONTEXT.md).
            warnings = flags(state, state.applied_action(choice), info)
            self_check, second = self._re_check(state, user_prompt, reply.content, result, choice)
            second_choice = _usable(second, state)
            if second_choice is not None:
                result, choice = second, second_choice
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
            prompt_tokens=reply.prompt_eval_count,
            latency_s=reply.latency_s,
            tools=tools_log,
            self_check=self_check,
            flags=warnings,
        ))
        return choice

    def _re_check(self, state: DecisionState, user_prompt: str, first_raw: str, first: ParseResult,
                  first_choice: Optional[str]) -> tuple[dict[str, Any], ParseResult]:
        """Continue the conversation with the generic re-check; return its log and the second parse."""
        first_usable = _usable(first, state)
        prompt = recheck_prompt(first_usable)
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_prompt},
            {"role": "assistant", "content": first_raw},
            {"role": "user", "content": prompt},
        ]
        reply = self.client.chat_messages(messages)
        second = parse_choice(reply.content, state.menu, reply.done_reason)
        final = final_choice(first_choice, _usable(second, state))
        log = {
            "first_action": first_usable,
            "first_parse_status": first.status,
            "recheck_prompt": prompt,
            "second_raw": reply.content,
            "second_action": second.action,
            "second_parse_status": second.status,
            "final_action": final,
            # The action played changed, not just its name (all_in then call facing a shove both apply as the call).
            "flipped": state.applied_action(final) != state.applied_action(first_choice),
            "done_reason": reply.done_reason,
            "eval_count": reply.eval_count,
            "prompt_tokens": reply.prompt_eval_count,
            "latency_s": round(reply.latency_s, 3),
        }
        return log, second

    def _tools(self, state: DecisionState, info: Optional[EquityInfo]) -> tuple[list[str], Optional[dict[str, Any]]]:
        """The tool lines for the prompt, and what they showed for the log (None when no tool is on)."""
        if not (self.config.probability_tool or self.config.strategy_info):
            return [], None
        lines: list[str] = []
        log: dict[str, Any] = {}
        if self.config.probability_tool:
            lines += info.lines()
            log.update(equity=round(info.equity, 4),
                       pot_odds=round(info.pot_odds, 4) if info.pot_odds is not None else None,
                       equity_seed=info.seed, equity_samples=info.samples)
        if self.config.strategy_info:
            lines += chart_lines(state)
            play = chart_play(state)
            log.update(hand_class=hand_class(state.hole_cards) if play is not None else None,
                       spot=spot(state), chart_play=play)
        return lines, log

    def rewrite_notes(self, prompt: str) -> ChatReply:
        """The memory setup's notes rewrite: same client and options as the decisions."""
        return self.client.chat(REWRITE_SYSTEM_PROMPT, prompt)

    def run_metadata(self) -> dict[str, Any]:
        """Run-level facts about this player's prompts, for metadata.json.

        The tools setups add the tool versions (tools_settings) and the re-check texts.
        """
        metadata: dict[str, Any] = {"system_prompt": self.system_prompt, "prompt_version": PROMPT_VERSION,
                                    "parser_version": PARSER_VERSION}
        tools = tools_settings(self.config)
        if tools is not None:
            metadata["tools"] = tools
        if self.config.self_evaluation:
            metadata["recheck_prompts"] = {"valid": recheck_prompt("<first action>"), "invalid": recheck_prompt(None)}
        return metadata

    def take_hand_details(self) -> list[PokerDecisionDetail]:
        """Return the details collected since the last call, and clear them."""
        details, self._details = self._details, []
        return details


def _usable(result: ParseResult, state: DecisionState) -> Optional[str]:
    """The reply's choice if the engine would apply it without a fallback (DecisionState.applied_action), else None.

    That is its menu action, or an off-menu name the engine still applies, such as a raise
    when no raise is legal (applied as the clamped call).
    """
    choice = result.action if result.action is not None else result.named
    return choice if state.applied_action(choice) is not None else None
