"""Turns a model's poker reply into one menu action, or says why it couldn't.

Tried in order (docs/research/poker-eval-methods.md, "LLM handling"):
1. JSON: the last {...} object in the reply with an "action" key.
2. The ACTION line: the last `ACTION: <answer>` marker (":", "-" or "：").
3. Loose: the last full action name anywhere in the reply, or a menu number written as
   "option 2" / "choice 2" or alone on its line.
Nothing found -> "unparseable".

Markdown * and ` are ignored, and so is case; "_", "-" and spaces are interchangeable
("all-in", "raise pot"). The answer must start with an action phrase (PHRASES) or a
menu number (1 = the first item; a number wins over any name after it). A number
past the end of the menu is off-menu. Synonyms are mapped only onto an item that is
on the menu (SYNONYM_TARGETS), and the mapping is recorded.
"""

import json
import re
from dataclasses import dataclass
from typing import Optional

from poker.engine import MenuItem

# Bump when the parsing rules change; logged and checked on resume.
PARSER_VERSION = "poker-parser-v1"

OK = "ok"

_JSON_OBJECT = re.compile(r"\{[^{}]*\}")
# "action" as a whole word, a separator, then the rest of that line.
_ACTION_LINE = re.compile(r"\baction[ \t]*[:\-\uff1a][ \t]*([^\n]*)", re.IGNORECASE)
_MARKDOWN = re.compile(r"[*`]")
# Loose step: full action names only (never a bare "pot"), and menu numbers only as
# "option 2" / "choice 2" or a number alone on its line, so chip counts are not read.
_LOOSE_NAME = re.compile(
    r"\b(check\s*(?:/|or)\s*call|raise[ _-]half[ _-]pot|raise[ _-]pot|all[ _-]?in|fold|check|call)\b"
)
_LOOSE_NUMBER = re.compile(r"\b(?:option|choice|number)\s*#?\s*(\d+)\b|^[ \t]*#?(\d+)\.?[ \t]*$", re.MULTILINE)

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
        recognised action that isn't on the menu) or "unparseable".
    method: which step read the answer ("json", "action_line", "loose"), None if none did.
    named: the action the reply named, canonical, even when it is off the menu.
    mapping: for "mapped", what was mapped onto what, e.g. "check/call -> call".
    """

    action: Optional[str]
    status: str
    method: Optional[str] = None
    named: Optional[str] = None
    mapping: Optional[str] = None


def parse_choice(reply: str, menu: tuple[MenuItem, ...]) -> ParseResult:
    """Parse a reply against the menu it answered."""
    for match in reversed(_JSON_OBJECT.findall(reply)):
        try:
            value = json.loads(match)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and "action" in value:
            return _resolve(str(value["action"]), menu, "json")
    cleaned = _MARKDOWN.sub("", reply)
    lines = _ACTION_LINE.findall(cleaned)
    if lines:
        return _resolve(lines[-1], menu, "action_line")
    loose = _last_loose_answer(cleaned.lower())
    if loose is not None:
        return _resolve(loose, menu, "loose")
    return ParseResult(None, "unparseable")


def _last_loose_answer(text: str) -> Optional[str]:
    """The last action name or menu number in free text, or None."""
    matches = [(m.start(), m.group(1)) for m in _LOOSE_NAME.finditer(text)]
    matches += [(m.start(), m.group(1) or m.group(2)) for m in _LOOSE_NUMBER.finditer(text)]
    return max(matches)[1] if matches else None


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
        number = int(words[0])
        if 1 <= number <= len(menu):
            return ParseResult(actions[number - 1], OK, method, actions[number - 1])
        return ParseResult(None, "off_menu", method)
    named = _phrase(words)
    if named is None:
        return ParseResult(None, "unparseable", method)
    if named in actions:
        return ParseResult(named, OK, method, named)
    target = next((action for action in SYNONYM_TARGETS.get(named, ()) if action in actions), None)
    if target is not None:
        return ParseResult(target, "mapped", method, named, f"{named} -> {target}")
    return ParseResult(None, "off_menu", method, named)
