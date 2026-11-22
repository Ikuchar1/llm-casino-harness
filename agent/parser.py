"""Turns a model's free-text reply into one legal action, or marks it invalid.

The model is told to end its reply with `ACTION: <action>`. The parser is lenient
about formatting but strict about meaning:

- Markdown characters (*, _, `) are removed and case is ignored.
- A marker is the word ACTION followed by ":", "-" or a fullwidth colon "："
  (spaces allowed), then the action. A marker's text runs to the end of its line
  or to the next marker, whichever comes first, so two markers on one line are
  read separately. Markers count anywhere in the reply, not only on the last line.
- The marker's text must start with an action phrase. If that text names two or
  more DIFFERENT actions (synonyms count as the same action), it is invalid
  ("conflicting"). This means "ACTION: double (or hit if not allowed)" is
  invalid; that is an accepted trade-off.
- A fixed synonym list is accepted (see SYNONYMS). Trailing punctuation is ignored.
- A reply cut off by the token limit (done_reason "length") that has no marker,
  or whose markers name no recognised action, is "truncated_no_action".
- No marker at all means invalid. Bare action words elsewhere in the reply are
  never used as a guess.
- Several markers that name the same action are fine; markers that name
  different actions are invalid ("conflicting").
- An action that is not legal right now is invalid ("illegal").

Invalid reasons: no_action, truncated_no_action, empty_action, unknown_word,
conflicting, illegal.
"""

import re
from dataclasses import dataclass, field
from typing import Optional

# Bump when the parsing rules change; logged on every decision and checked on resume.
# v1: first marker on a line won; one marker could list several actions.
# v2: markers split at the next marker; several actions in one marker = conflicting;
#     fullwidth colon accepted; cut-off replies with no usable marker = truncated_no_action.
PARSER_VERSION = "parser-v2"

# Every accepted phrase and the engine action it means. Multi-word phrases are
# matched before single words, so "take a card" wins over "take".
SYNONYMS: dict[str, str] = {
    "hit": "hit",
    "hit me": "hit",
    "take a card": "hit",
    "stand": "stand",
    "stay": "stand",
    "stand pat": "stand",
    "double": "double",
    "double down": "double",
    "doubledown": "double",
    "split": "split",
}

# The longest phrase in SYNONYMS, in words. Used to know how far ahead to look.
_MAX_PHRASE_WORDS = max(len(phrase.split()) for phrase in SYNONYMS)

# "action" as a whole word, then a separator (":", "-", or fullwidth "："), then
# its text: everything up to the end of the line or the next marker.
# [ \t]* (not \s*) keeps the action on the same line as the marker.
_SEPARATOR = r"\baction[ \t]*[:\-\uff1a]"
_MARKER = re.compile(_SEPARATOR + r"[ \t]*((?:(?!" + _SEPARATOR + r")[^\n])*)")

# Returned by _read_marker when one marker names several different actions.
_CONFLICT = "<conflict>"

_MARKDOWN_CHARS = re.compile(r"[*_`]")


@dataclass
class ParseResult:
    """What the parser concluded about one reply.

    action is set only when the reply is valid; invalid_reason is set only when it isn't.
    marker_words holds the raw text that followed each marker, for debugging the parser.
    """

    action: Optional[str]
    invalid_reason: Optional[str]
    marker_words: list[str] = field(default_factory=list)


def parse_action(reply: str, legal_actions: tuple[str, ...], done_reason: Optional[str]) -> ParseResult:
    """Parse a reply into a legal action.

    done_reason is Ollama's reason the reply ended ("stop" or "length"). A reply cut
    off by the token limit with no marker gets the reason "truncated_no_action".
    """
    cleaned = _MARKDOWN_CHARS.sub("", reply).lower()
    marker_texts = [match.group(1).strip() for match in _MARKER.finditer(cleaned)]

    if not marker_texts:
        reason = "truncated_no_action" if done_reason == "length" else "no_action"
        return ParseResult(None, reason)

    named = [_read_marker(text) for text in marker_texts]
    if _CONFLICT in named:
        return ParseResult(None, "conflicting", marker_texts)
    actions = {action for action in named if action is not None}

    if not actions:
        # Every marker was followed by nothing, or by a word we don't recognise.
        if done_reason == "length":
            reason = "truncated_no_action"
        elif all(text == "" for text in marker_texts):
            reason = "empty_action"
        else:
            reason = "unknown_word"
        return ParseResult(None, reason, marker_texts)
    if len(actions) > 1:
        return ParseResult(None, "conflicting", marker_texts)

    action = actions.pop()
    if action not in legal_actions:
        return ParseResult(None, "illegal", marker_texts)
    return ParseResult(action, None, marker_texts)


def _read_marker(text: str) -> Optional[str]:
    """What one marker's text names: an action, _CONFLICT, or None (empty/unknown).

    The text must start with an action phrase. Every other action phrase in the
    text must name the same action, or the marker is a conflict.
    Only letters count as words, so brackets and punctuation are ignored ("[hit]." -> "hit").
    """
    words = re.findall(r"[a-z]+", text)
    first_action, _ = _phrase_at(words, 0)
    if first_action is None:
        return None

    named = set()
    position = 0
    while position < len(words):
        action, length = _phrase_at(words, position)
        if action is None:
            position += 1
        else:
            named.add(action)
            position += length
    return first_action if len(named) == 1 else _CONFLICT


def _phrase_at(words: list[str], start: int) -> tuple[Optional[str], int]:
    """The action phrase starting at words[start] and its length in words, or (None, 0).

    Longer phrases are tried first, so "take a card" wins over "take".
    """
    for length in range(min(_MAX_PHRASE_WORDS, len(words) - start), 0, -1):
        phrase = " ".join(words[start : start + length])
        if phrase in SYNONYMS:
            return SYNONYMS[phrase], length
    return None, 0
