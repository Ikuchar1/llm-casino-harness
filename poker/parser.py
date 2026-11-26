"""Turns a model's poker reply into one menu action, or says why it couldn't.

Tried in order (docs/research/poker-eval-methods.md, "LLM handling"):
1. JSON: the last {...} object in the reply with an "action" key.
2. The ACTION line: the last `ACTION: <answer>` marker (":", "-" or "：").
3. Loose: only when the last non-empty line is nothing but a full action name or a menu
   number. Action words anywhere else in the reply are never used as a guess.
Nothing found -> "unparseable". A reply cut off by the token limit (done_reason
"length") with no ACTION line -> "truncated_no_action", before any other step.

Markdown * and ` are ignored, and so is case; "_", "-" and spaces are interchangeable
("all-in", "raise pot"). The answer must start with an action phrase (PHRASES) or a
menu number (1 = the first item). A number counts only alone or followed by "." or ")";
a name after it must agree with the numbered item, else the answer is unparseable
("1/2 pot", "3-bet" and "2. fold" with call at 2 are all unparseable). A number past
the end of the menu is off-menu. Synonyms are mapped only onto an item that is
on the menu (SYNONYM_TARGETS), and the mapping is recorded.
"""

import json
import re
from dataclasses import dataclass
from typing import Optional

from poker.engine import MenuItem

# Bump when the parsing rules change; logged and checked on resume.
# v2: a number counts only alone or before "."/")"; loose only for a lone last line;
#     cut-off replies with no ACTION line = truncated_no_action.
PARSER_VERSION = "poker-parser-v2"

OK = "ok"
TRUNCATED = "truncated_no_action"

_JSON_OBJECT = re.compile(r"\{[^{}]*\}")
# "action" as a whole word, a separator, then the rest of that line.
_ACTION_LINE = re.compile(r"\baction[ \t]*[:\-\uff1a][ \t]*([^\n]*)", re.IGNORECASE)
_MARKDOWN = re.compile(r"[*`]")
# Loose step: the last non-empty line, when it is nothing but a full action name (never
# a bare "pot") or a menu number.
_LOOSE_LINE = re.compile(
    r"check\s*(?:/|or)\s*call|raise[ _-]half[ _-]pot|raise[ _-]pot|all[ _-]?in|fold|check|call|#?\d+"
)

# A menu number as an answer: the number alone, or followed by "." or ")" and the rest.
_MENU_NUMBER = re.compile(r"^\s*#?(\d+)\s*(?:[.)](.*))?$", re.DOTALL)

CHECK_OR_CALL = "check/call"

# Synonyms, and the menu actions each may be mapped onto (first one on the menu wins).
# A mapping is used only when the named action itself is not on the menu.
# "check" is never mapped onto "call": that would put chips in the model didn't offer.
SYNONYM_TARGETS: dict[str, tuple[str, ...]] = {
    CHECK_OR_CALL: ("check", "call"),
    "call": ("check",),
}

# Accepted phrases (as words) and the action they name. Longest phrases are tried first.
PHRASES: dict[tuple[str, ...], str] = {
    ("fold",): "fold",
    ("check",): "check",
    ("call",): "call",
    ("check", "call"): CHECK_OR_CALL,
    ("check", "or", "call"): CHECK_OR_CALL,
    ("raise", "half", "pot"): "raise_half_pot",
    ("half", "pot"): "raise_half_pot",
    ("raise", "pot"): "raise_pot",
    ("pot",): "raise_pot",
    ("all", "in"): "all_in",
    ("allin",): "all_in",
}


@dataclass(frozen=True)
class ParseResult:
    """What the parser made of one reply.

    action: the menu action, or None when parsing failed.
    status: "ok", "mapped" (a synonym was mapped onto a menu item), "off_menu" (a
        recognised action that isn't on the menu), "unparseable", or
        "truncated_no_action" (cut off by the token limit before an ACTION line).
    method: which step read the answer ("json", "action_line", "loose"), None if none did.
    named: the action the reply named, canonical, even when it is off the menu.
    mapping: for "mapped", what was mapped onto what, e.g. "check/call -> call".
    """

    action: Optional[str]
    status: str
    method: Optional[str] = None
    named: Optional[str] = None
    mapping: Optional[str] = None


def parse_choice(reply: str, menu: tuple[MenuItem, ...], done_reason: Optional[str] = None) -> ParseResult:
    """Parse a reply against the menu it answered.

    done_reason is Ollama's reason the reply ended ("stop" or "length"). A reply cut off
    by the token limit with no ACTION line is "truncated_no_action": whatever action
    words its unfinished reasoning mentioned are not the answer.
    """
    cleaned = _MARKDOWN.sub("", reply)
    lines = _ACTION_LINE.findall(cleaned)
    if done_reason == "length" and not lines:
        return ParseResult(None, TRUNCATED)
    for match in reversed(_JSON_OBJECT.findall(reply)):
        try:
            value = json.loads(match)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and "action" in value:
            return _resolve(str(value["action"]), menu, "json")
    if lines:
        return _resolve(lines[-1], menu, "action_line")
    loose = _last_loose_answer(cleaned.lower())
    if loose is not None:
        return _resolve(loose, menu, "loose")
    return ParseResult(None, "unparseable")


def _last_loose_answer(text: str) -> Optional[str]:
    """The last non-empty line, when it is only an action name or a menu number; else None.

    Action words anywhere else in the reply are never used as a guess.
    """
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return None
    last = lines[-1].rstrip(".!")
    return last if _LOOSE_LINE.fullmatch(last) else None


def _words(text: str) -> list[str]:
    """Lower-case words; "_", "-", "/" and punctuation all separate words ("all-in" -> all, in)."""
    return re.findall(r"[a-z0-9]+", text.lower())


def _phrase(words: list[str]) -> Optional[str]:
    """The action named by the longest phrase at the start of words, or None."""
    for phrase in sorted(PHRASES, key=len, reverse=True):
        if tuple(words[: len(phrase)]) == phrase:
            return PHRASES[phrase]
    return None


def _resolve(answer: str, menu: tuple[MenuItem, ...], method: str) -> ParseResult:
    actions = [item.action for item in menu]
    words = _words(answer)
    if words and words[0].isdigit():
        return _resolve_number(answer, actions, method)
    named = _phrase(words)
    if named is None:
        return ParseResult(None, "unparseable", method)
    if named in actions:
        return ParseResult(named, OK, method, named)
    target = next((action for action in SYNONYM_TARGETS.get(named, ()) if action in actions), None)
    if target is not None:
        return ParseResult(target, "mapped", method, named, f"{named} -> {target}")
    return ParseResult(None, "off_menu", method, named)


def _resolve_number(answer: str, actions: list[str], method: str) -> ParseResult:
    """A menu number: alone ("3"), or followed by "." / ")" and, optionally, a name that agrees.

    Anything else after the number ("1/2 pot", "3-bet") is unparseable, and so is a name
    that disagrees with the numbered item ("2. fold" when item 2 is call).
    """
    match = _MENU_NUMBER.match(answer)
    if match is None:
        return ParseResult(None, "unparseable", method)
    number, rest = int(match.group(1)), match.group(2) or ""
    if not 1 <= number <= len(actions):
        return ParseResult(None, "off_menu", method)
    action = actions[number - 1]
    named = _phrase(_words(rest))
    if named is not None and named != action and action not in SYNONYM_TARGETS.get(named, ()):
        return ParseResult(None, "unparseable", method)
    return ParseResult(action, OK, method, action)
