"""Poker memory (docs/poker-plan.md, "Memory" and decisions 2 and 14).

The harness keeps the ground truth, an OpponentTally of the opponent's actions per
opportunity, and the model writes the interpretation: Notes of at most 3 hypotheses,
rewritten in full every 5 hands. The harness, not the model, checks each cited count
against the tally and sets each hypothesis's status. MemoryState ties it together and
only takes in hands from completed duplicate pairs.
"""

import dataclasses
import json
import re
from collections import Counter, deque
from dataclasses import dataclass
from typing import Any, Optional

from poker.engine import CALL, CHECK, FOLD, STREETS, DecisionState, HandRecord
from poker.prompt import NOTES_HEADER

POSTFLOP_STREETS = STREETS[1:]
FACED_BET_OUTCOMES = ("fold", "call", "raise", "continue", "no_raise")
CHECKED_TO_OUTCOMES = ("bet", "check")
MAX_HYPOTHESES = 3
WORD_BUDGET = 100  # words of hypothesis text across all notes; counts and status are extra
SHOWN_HANDS = 5  # most recent showdowns whose cards the tally text lists
RAISE = "raise"  # any bet or raise size, all-in included


@dataclass(frozen=True)
class ShownHand:
    """Cards the opponent showed at a showdown (never a folded hand)."""

    hand_number: int
    cards: tuple[str, ...]
    board: tuple[str, ...]


class OpponentTally:
    """Counts the opponent's actions per opportunity, from the model's point of view."""

    def __init__(self, model_name: str):
        self.model_name = model_name
        self._yes: Counter[str] = Counter()
        self._opportunities: Counter[str] = Counter()
        self.hands = 0
        self.showdowns: list[ShownHand] = []

    def observe(self, record: HandRecord) -> None:
        opponent = next(name for name in record.seats.values() if name != self.model_name)
        self.hands += 1
        preflop = [d for d in record.decisions if d.player == opponent and d.state.street == "preflop"]
        if preflop:  # a walk (the model folded the button) gave the opponent no preflop choice
            vpip = any(d.action not in (FOLD, CHECK) for d in preflop)
            raised = any(_outcome(d.action) == RAISE for d in preflop)
            self._count("preflop.vpip", vpip)
            self._count("preflop.no_vpip", not vpip)
            self._count("preflop.raise", raised)
            self._count("preflop.no_raise", not raised)
        if len(record.board) >= 3:  # heads-up, both players see any flop that is dealt
            self._count("showdown.reached", record.showdown)
        if record.showdown:  # the only hands whose opponent hole cards the model ever sees
            self.showdowns.append(ShownHand(record.hand_number, tuple(record.hole_cards[opponent]), tuple(record.board)))
        for decision in record.decisions:
            if decision.player != opponent:
                continue
            street = decision.state.street
            if _faced_a_bet(decision.state):
                outcome = _outcome(decision.action)
                for name, happened in (
                    ("fold", outcome == FOLD),
                    ("call", outcome == CALL),
                    ("raise", outcome == RAISE),
                    ("continue", outcome != FOLD),
                    ("no_raise", outcome != RAISE),
                ):
                    self._count(f"faced_bet.{name}", happened)
                    self._count(f"faced_bet.{name}.{street}", happened)
            elif street != "preflop":
                outcome = _outcome(decision.action)
                for name, happened in (("bet", outcome == RAISE), ("check", outcome == CHECK)):
                    self._count(f"checked_to.{name}", happened)
                    self._count(f"checked_to.{name}.{street}", happened)

    def _count(self, key: str, happened: bool) -> None:
        self._opportunities[key] += 1
        self._yes[key] += happened

    def counts(self, key: str) -> tuple[int, int]:
        """(for, against): times the outcome happened, and the other opportunities."""
        return self._yes[key], self._opportunities[key] - self._yes[key]

    def citation(self, key: str) -> str:
        """The key and its true counts exactly as a rewrite line cites them: `key K | for N | against M`."""
        happened, against = self.counts(key)
        return f"key {key} | for {happened} | against {against}"

    def _dominant(self, *pairs: tuple[str, str], suffix: str = "") -> list[str]:
        """The keys to list for these outcome pairs: each pair's more frequent side, both if tied.

        Lists only keys a read can be CONFIRMED on, so a model can't cite the low-count side
        for a "rarely X" read.
        """
        shown: list[str] = []
        for first, second in pairs:
            a, b = first + suffix, second + suffix
            yes_a, yes_b = self._yes[a], self._yes[b]
            shown += [a, b] if yes_a == yes_b else [a if yes_a > yes_b else b]
        return shown

    def _faced_bet(self, suffix: str = "") -> list[str]:
        """The faced-bet keys to list: fold/continue and raise/no_raise by _dominant, then
        faced_bet.call only when calling was the most common answer (ties included)."""
        keys = self._dominant(("faced_bet.fold", "faced_bet.continue"), ("faced_bet.raise", "faced_bet.no_raise"), suffix=suffix)
        call, fold, raised = (self._yes[f"faced_bet.{name}{suffix}"] for name in ("call", "fold", "raise"))
        return keys + [f"faced_bet.call{suffix}"] if call >= max(fold, raised) else keys

    def _sections(self) -> list[tuple[str, list[str], str]]:
        """(heading, listed keys, key indent) in render order: the one place that decides which keys are listed."""
        sections = [
            ("preflop, put money in voluntarily or not (per hand):", self._dominant(("preflop.vpip", "preflop.no_vpip")), "  "),
            ("preflop, raised or not (per hand):", self._dominant(("preflop.raise", "preflop.no_raise")), "  "),
        ]
        faced = self._opportunities["faced_bet.fold"]
        fold, call, raised = (self._yes[f"faced_bet.{name}"] for name in ("fold", "call", "raise"))
        sections.append((f"faced a bet {faced} times: folded {fold}, called {call}, raised {raised}", self._faced_bet(), "  "))
        for street in STREETS:
            if self._opportunities[f"faced_bet.fold.{street}"]:
                sections.append((
                    f"  {street}, faced a bet {self._opportunities[f'faced_bet.fold.{street}']} times:",
                    self._faced_bet(f".{street}"), "    ",
                ))
        chances = self._opportunities["checked_to.bet"]
        checked_pair = ("checked_to.bet", "checked_to.check")
        sections.append((
            f"no bet to face after the flop {chances} times: bet {self._yes['checked_to.bet']},"
            f" checked {self._yes['checked_to.check']}",
            self._dominant(checked_pair), "  ",
        ))
        for street in POSTFLOP_STREETS:
            if self._opportunities[f"checked_to.bet.{street}"]:
                sections.append((
                    f"  {street}, no bet to face {self._opportunities[f'checked_to.bet.{street}']} times:",
                    self._dominant(checked_pair, suffix=f".{street}"), "    ",
                ))
        sections.append(("went to showdown, of hands that saw a flop:", ["showdown.reached"], "  "))
        # A 0/0 key has nothing to back a read with, so it is never listed.
        return [(heading, [k for k in keys if self._opportunities[k]], indent) for heading, keys, indent in sections]

    def listed_keys(self) -> set[str]:
        """The keys render() lists, the only ones a rewrite may cite (verify drops any other)."""
        return {key for _, keys, _ in self._sections() for key in keys}

    def render(self) -> str:
        """Short text for the rewrite prompt: labelled sections, each key on its own line as a citation.

        Every key line is `key K | for N | against M`, the exact tail of a rewrite line, so
        the model copies it rather than looking counts up. Of each complementary pair of
        keys (vpip/no_vpip, fold/continue, raise/no_raise, bet/check) only the side that
        happened more often is listed, both when tied; faced_bet.call only when calling was
        the most common answer to a bet; and no key with zero opportunities.
        """
        lines = [f"hands dealt: {self.hands}"]
        for heading, keys, indent in self._sections():
            lines.append(heading)
            lines += [indent + self.citation(key) for key in keys]
        if self.showdowns:
            shown = [f"hand {s.hand_number} {' '.join(s.cards)} on {' '.join(s.board)}" for s in self.showdowns[-SHOWN_HANDS:]]
            lines.append("showed at showdown: " + "; ".join(shown))
        return "\n".join(lines)

    def snapshot(self) -> dict[str, Any]:
        """JSON-ready copy of every count, for MemoryEvent logs."""
        return {
            "hands": self.hands,
            "counts": {key: list(self.counts(key)) for key in sorted(self._opportunities)},
            "showdowns": [
                {"hand_number": s.hand_number, "cards": list(s.cards), "board": list(s.board)} for s in self.showdowns
            ],
        }


def _outcome(action: str) -> str:
    return action if action in (FOLD, CHECK, CALL) else RAISE


def _faced_a_bet(state: DecisionState) -> bool:
    """Chips to call, except the button's first preflop action, which faces only the blinds."""
    if state.to_call == 0:
        return False
    if state.street != "preflop":
        return True
    return any(_outcome(action.action) == RAISE for action in state.history if action.street == "preflop")


# ---------- Hypotheses and notes ----------

TENTATIVE = "TENTATIVE"
CONFIRMED = "CONFIRMED"
STATUSES = (TENTATIVE, CONFIRMED)

_FOR = re.compile(r"^for\s*[:=]?\s*(\d+)$", re.IGNORECASE)
_AGAINST = re.compile(r"^against\s*[:=]?\s*(\d+)$", re.IGNORECASE)
_KEY = re.compile(r"^key\s*[:=]?\s*([a-z_.]+)$", re.IGNORECASE)
_LEAD = re.compile(r"^\s*(?:[-*\u2022]\s*)?(?:\d+[.)]|H\d+\s*[:.)])?\s*")  # bullets, "1.", "H1:"


@dataclass(frozen=True)
class Hypothesis:
    """One read on the opponent. `opportunity_key` names the tally count it cites (None if uncited)."""

    text: str
    for_count: int
    against_count: int
    opportunity_key: Optional[str]
    status: str = TENTATIVE

    def line(self) -> str:
        """The notes line format: `never folds to bets | for 9 | against 0 | TENTATIVE`."""
        return f"{self.text} | for {self.for_count} | against {self.against_count} | {self.status}"

    def cited_line(self) -> str:
        """The line format with the cited tally key, as the model writes it in a rewrite."""
        return (
            f"{self.text} | key {self.opportunity_key} | for {self.for_count} | against {self.against_count}"
            f" | {self.status}"
        )


def parse_line(line: str) -> Optional[Hypothesis]:
    """One hypothesis from a `text | [key K |] for N | against M [| STATUS]` line, else None."""
    fields = [field.strip() for field in _LEAD.sub("", line, count=1).split("|")]
    text, rest = fields[0], fields[1:]
    for_count = against = key = None
    status = TENTATIVE
    for field in rest:
        if (match := _FOR.match(field)) and for_count is None:
            for_count = int(match.group(1))
        elif (match := _AGAINST.match(field)) and against is None:
            against = int(match.group(1))
        elif match := _KEY.match(field):
            key = match.group(1).lower()
        elif field.upper() in STATUSES:
            status = field.upper()
    if not text or for_count is None or against is None:
        return None
    return Hypothesis(text, for_count, against, key, status)


@dataclass(frozen=True)
class Notes:
    """The model's notes on the opponent: at most MAX_HYPOTHESES hypotheses."""

    hypotheses: tuple[Hypothesis, ...] = ()

    def lines(self) -> list[str]:
        return [hypothesis.line() for hypothesis in self.hypotheses]


@dataclass
class ParseResult:
    """What the rewrite parser kept, and which of its tolerances it used."""

    notes: Notes
    junk_lines: list[str]  # non-blank lines that were not a hypothesis
    dropped: list[str]  # hypothesis lines past MAX_HYPOTHESES, or left with no words by WORD_BUDGET
    truncated: bool  # hypothesis text was cut to fit WORD_BUDGET
    parse_failed: bool  # no hypothesis parsed, so the previous notes were kept


def parse_rewrite(response: str, previous: Notes) -> ParseResult:
    """The model's rewrite as Notes; junk lines skipped, the previous notes kept if nothing parses."""
    hypotheses: list[Hypothesis] = []
    lines: list[str] = []  # the line each hypothesis came from
    junk: list[str] = []
    dropped: list[str] = []
    for raw in (response or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        hypothesis = parse_line(line)
        if hypothesis is None:
            junk.append(line)
        elif len(hypotheses) == MAX_HYPOTHESES:
            dropped.append(line)
        else:
            hypotheses.append(hypothesis)
            lines.append(line)
    if not hypotheses:
        return ParseResult(previous, junk, dropped, False, True)
    kept, truncated = _fit_word_budget(hypotheses)
    return ParseResult(Notes(tuple(kept)), junk, lines[len(kept):] + dropped, truncated, False)


def _fit_word_budget(hypotheses: list[Hypothesis]) -> tuple[list[Hypothesis], bool]:
    """Cut hypothesis text to WORD_BUDGET words in total; a hypothesis left with no words is dropped."""
    kept: list[Hypothesis] = []
    left = WORD_BUDGET
    for hypothesis in hypotheses:
        words = hypothesis.text.split()
        if len(words) > left:
            if left:
                kept.append(dataclasses.replace(hypothesis, text=" ".join(words[:left])))
            return kept, True
        kept.append(hypothesis)
        left -= len(words)
    return kept, False


# ---------- Harness-side verification and status ----------

OPPORTUNITY_KEYS = (
    "preflop.vpip",
    "preflop.no_vpip",
    "preflop.raise",
    "preflop.no_raise",
    *(f"faced_bet.{outcome}" for outcome in FACED_BET_OUTCOMES),
    *(f"faced_bet.{outcome}.{street}" for outcome in FACED_BET_OUTCOMES for street in STREETS),
    *(f"checked_to.{outcome}" for outcome in CHECKED_TO_OUTCOMES),
    *(f"checked_to.{outcome}.{street}" for outcome in CHECKED_TO_OUTCOMES for street in POSTFLOP_STREETS),
    "showdown.reached",
)


# Status gates (docs/poker-plan.md, "Memory"). A hypothesis is CONFIRMED when its supporting
# count is at least the threshold for its kind of opportunity AND against <= MAX_AGAINST_SHARE x for;
# otherwise TENTATIVE. Facing-a-bet and no-bet-to-face reads use LEAK_THRESHOLD opportunities
# (the extreme leak bots); preflop and showdown reads are per hand and use HAND_FREQUENCY_THRESHOLD.
LEAK_THRESHOLD = 8
HAND_FREQUENCY_THRESHOLD = 20
MAX_AGAINST_SHARE = 0.2
_HAND_FREQUENCY_FAMILIES = ("preflop", "showdown")


def status_for(opportunity_key: str, for_count: int, against_count: int) -> str:
    """CONFIRMED or TENTATIVE for a hypothesis citing this key with these true counts."""
    family = opportunity_key.split(".")[0]
    threshold = HAND_FREQUENCY_THRESHOLD if family in _HAND_FREQUENCY_FAMILIES else LEAK_THRESHOLD
    if for_count >= threshold and against_count <= MAX_AGAINST_SHARE * for_count:
        return CONFIRMED
    return TENTATIVE


@dataclass
class VerifyResult:
    notes: Notes  # with the tally's true counts and the harness-set status; unverifiable ones left out
    count_mismatches: list[dict[str, Any]]  # cited counts the harness replaced
    unverifiable: list[str]  # texts of hypotheses whose key is missing or not in OPPORTUNITY_KEYS (dropped)
    unlisted_keys: list[dict[str, Any]]  # text and key of hypotheses citing a key the tally text doesn't list (dropped)
    duplicate_keys: list[dict[str, Any]]  # text and key of hypotheses citing a key an earlier kept read cites (dropped)


def verify(notes: Notes, tally: OpponentTally) -> VerifyResult:
    """Check every cited count against the tally and set each status.

    A mismatched count is replaced by the true one, and that read is TENTATIVE for this
    version whatever the true counts say. Reads with no known key are dropped, and so are
    reads citing a known key the tally text doesn't list (the prompt allows only listed keys)
    and reads citing a key an earlier kept read already cites (the harness would show the
    same sentence twice).
    """
    checked: list[Hypothesis] = []
    mismatches: list[dict[str, Any]] = []
    unverifiable: list[str] = []
    unlisted: list[dict[str, Any]] = []
    duplicates: list[dict[str, Any]] = []
    listed = tally.listed_keys()
    for hypothesis in notes.hypotheses:
        if hypothesis.opportunity_key not in OPPORTUNITY_KEYS:  # nothing to check it against: not shown
            unverifiable.append(hypothesis.text)
            continue
        if hypothesis.opportunity_key not in listed:
            unlisted.append({"text": hypothesis.text, "opportunity_key": hypothesis.opportunity_key})
            continue
        if any(kept.opportunity_key == hypothesis.opportunity_key for kept in checked):
            duplicates.append({"text": hypothesis.text, "opportunity_key": hypothesis.opportunity_key})
            continue
        true_for, true_against = tally.counts(hypothesis.opportunity_key)
        status = status_for(hypothesis.opportunity_key, true_for, true_against)
        if (hypothesis.for_count, hypothesis.against_count) != (true_for, true_against):
            mismatches.append({
                "text": hypothesis.text, "opportunity_key": hypothesis.opportunity_key,
                "cited": [hypothesis.for_count, hypothesis.against_count], "tally": [true_for, true_against],
            })
            status = TENTATIVE  # the plan's downgrade: a model that misreads the tally loses CONFIRMED
        checked.append(dataclasses.replace(
            hypothesis, for_count=true_for, against_count=true_against, status=status,
        ))
    return VerifyResult(Notes(tuple(checked)), mismatches, unverifiable, unlisted, duplicates)


def refresh(notes: Notes, tally: OpponentTally) -> VerifyResult:
    """Re-verify reads with the tally's current counts for their keys, so no count or status is stale."""
    return verify(Notes(tuple(
        dataclasses.replace(h, for_count=f, against_count=a)
        for h in notes.hypotheses
        for f, a in [tally.counts(h.opportunity_key)]
    )), tally)


# ---------- Rewrite prompt ----------


def render_hand(record: HandRecord, model_name: str) -> str:
    """One hand on one line, as the model saw it: the opponent's cards appear only at showdown."""
    opponent = next(name for name in record.seats.values() if name != model_name)
    who = {seat: ("you" if name == model_name else "opp") for seat, name in record.seats.items()}
    seat = "the button" if record.button == model_name else "the big blind"
    parts = [f"hand {record.hand_number}: you on {seat} with {' '.join(record.hole_cards[model_name])}"]
    board_by_street = {"preflop": [], "flop": record.board[:3], "turn": record.board[3:4], "river": record.board[4:5]}
    for street in STREETS:
        actions = [action for action in record.actions if action.street == street]
        if not actions:
            continue
        moves = ", ".join(
            f"{who[action.seat]} {action.action}" + (f" {action.amount}" if action.amount else "") for action in actions
        )
        cards = " ".join(board_by_street[street])
        parts.append(f"{street}{' ' + cards if cards else ''}: {moves}")
    if record.showdown:
        if len(record.board) == 5 and not any(a.street == "river" for a in record.actions):
            parts.append(f"board run out {' '.join(record.board)}")
        parts.append(f"showdown: opp showed {' '.join(record.hole_cards[opponent])}")
    parts.append(f"result: you {record.chip_delta[model_name]:+d}")
    return " | ".join(parts)


# The system message of every rewrite call (the decision system prompt is about playing, not notes).
REWRITE_SYSTEM_PROMPT = (
    "You keep short, evidence-based notes about a poker opponent. "
    "Answer only with hypothesis lines in the exact format the user asks for."
)


def build_rewrite_prompt(
    previous: Notes, tally: OpponentTally, recent_hands: list[HandRecord], model_name: str
) -> str:
    """The every-5-hands prompt: rewrite the notes in full from the tally and the last hands.

    The previous reads are shown harness-written (previous_line): the evidence sentence for
    each key, then the key, the tally's current counts and the status those give. Never the
    model's own text, nor the counts the read was written with.
    """
    old = "\n".join(previous_line(h) for h in refresh(previous, tally).notes.hypotheses) or "(none yet)"
    hands = "\n".join(render_hand(record, model_name) for record in recent_hands) or "(none)"
    return f"""You are playing heads-up no-limit Hold'em and keep short notes about your opponent's habits.
Rewrite your notes in full from the evidence below. Do not just add to the old notes: keep a line only if the counts still support it.

Previous notes; revise or discard based on the counts below:
{old}

Opponent tally after {tally.hands} hands (counted by the harness from what you could see; each key line gives that key's for count, the times its outcome happened, and its against count, the times it didn't; of each pair of opposite keys, like faced_bet.fold and faced_bet.continue, only the one that happened more often is listed, both when tied; faced_bet.call is listed only when calling was the opponent's most common answer to a bet, and keys with no opportunities yet are not listed):
{tally.render()}

Last {len(recent_hands)} hands ("opp" is your opponent):
{hands}

Write at most {MAX_HYPOTHESES} hypotheses about how the opponent plays, one per line, in exactly this format:
<what the opponent does> | key <tally key> | for <N> | against <M>
Each line cites one tally key: after your text, copy one key line from the tally exactly as written, with its for and against counts.
Cite only a key line listed in the tally above; a line citing any other key is dropped. Always cite the listed key whose outcome supports your line, so a high for count backs it up; a "rarely" or "never" line must cite the listed opposite key. For example:
- "never folds to bets" cites faced_bet.continue, not faced_bet.fold
- "folds to most bets" cites faced_bet.fold
- "always bets when checked to" cites checked_to.bet
- "plays very few hands" cites preflop.no_vpip
Keep all the lines under {WORD_BUDGET} words in total. Output only the hypothesis lines, nothing else."""


# ---------- Decision-time notes block ----------

# What each key's `for` count measures, in plain English: "<what> <for> of <for + against> <unit>".
_FACED_BET_WORDS = {
    "fold": "folded",
    "call": "called",
    "raise": "raised",
    "continue": "continued (called or raised)",
    "no_raise": "did not raise (folded or called)",
}
_CHECKED_TO_WORDS = {"bet": "bet", "check": "checked"}
_PREFLOP_WORDS = {
    "vpip": "put money in voluntarily preflop",
    "no_vpip": "did not put money in voluntarily preflop",
    "raise": "raised preflop",
    "no_raise": "did not raise preflop",
}


def evidence(opportunity_key: str, for_count: int, against_count: int) -> str:
    """What the key's counts measure, e.g. 'folded when facing a bet on the flop 0 of 12 times'."""
    family, outcome, *street = opportunity_key.split(".")
    on_street = f" on the {street[0]}" if street else ""
    of = f"{for_count} of {for_count + against_count}"
    if family == "faced_bet":
        return f"{_FACED_BET_WORDS[outcome]} when facing a bet{on_street} {of} times"
    if family == "checked_to":
        return f"{_CHECKED_TO_WORDS[outcome]} with no bet to face{on_street} {of} times"
    if family == "preflop":
        return f"{_PREFLOP_WORDS[outcome]} {of} hands"
    return f"went to showdown {of} hands that saw a flop"


def shown_line(hypothesis: Hypothesis) -> str:
    """A verified read as the decision prompt shows it, all harness-written: its key's evidence and status.

    The model's text never reaches the decision prompt (it is logged only), so a read whose
    words contradict its key can't put the contradiction in front of the model.
    """
    counts = evidence(hypothesis.opportunity_key, hypothesis.for_count, hypothesis.against_count)
    return f"{counts} — {hypothesis.status}"


def previous_line(hypothesis: Hypothesis) -> str:
    """A kept read as the next rewrite prompt shows it: the harness's evidence sentence in place of
    the model's text, then `key K | for N | against M | STATUS`, so an echoed line still parses."""
    counts = evidence(hypothesis.opportunity_key, hypothesis.for_count, hypothesis.against_count)
    return dataclasses.replace(hypothesis, text=counts).cited_line()


# Fixed budget for the whole block in the prompt (poker.prompt's header included), so
# memory-on prompts differ from memory-off only by this block.
NOTES_BLOCK_CHAR_CAP = 1200  # far more than 3 harness sentences need
_NUDGE = (
    "CONFIRMED reads rest on enough opportunities to act on; "
    "TENTATIVE reads should only nudge your play, not override it."
)


def render_notes_block(notes: Notes) -> str:
    """The notes lines and nudge for the decision prompt; empty while there are no notes.

    poker.prompt.notes_block puts NOTES_HEADER above it; the cap counts that header too.
    """
    if not notes.hypotheses:
        return ""
    room = NOTES_BLOCK_CHAR_CAP - len(NOTES_HEADER) - len(_NUDGE) - 1  # newline after the header
    lines: list[str] = []
    for hypothesis in notes.hypotheses:
        line = "- " + shown_line(hypothesis)
        if len(line) + 1 > room:
            break
        lines.append(line)
        room -= len(line) + 1
    return "\n".join([*lines, _NUDGE])


# ---------- Logging ----------


@dataclass
class MemoryEvent:
    """One notes rewrite, logged in full so lock-in can be measured later.

    Notes are lists of Hypothesis dicts. `flags` says which tolerances and corrections
    fired; the lists after it say exactly what each one touched.
    """

    hand_number: Optional[int]  # the last committed hand before this rewrite
    hands_seen: int  # committed hands in the tally
    old_notes: list[dict[str, Any]]
    raw_response: Optional[str]
    parsed_notes: list[dict[str, Any]]  # as the parser read them (the old notes on parse_failed)
    # True counts and harness-set status: the notes now in use. Each keeps the model's `text`
    # (logged only) beside `shown_text`, the harness sentence the decision prompt shows instead.
    verified_notes: list[dict[str, Any]]
    tally: dict[str, Any]  # OpponentTally.snapshot() at this rewrite
    # count_mismatch, unverifiable, unlisted_key, duplicate_key, parse_failed, truncated, junk_lines, dropped_lines
    flags: dict[str, bool]
    count_mismatches: list[dict[str, Any]]
    unverifiable: list[str]
    unlisted_keys: list[dict[str, Any]]
    duplicate_keys: list[dict[str, Any]]
    junk_lines: list[str]
    dropped_lines: list[str]

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict())


def _as_dicts(notes: Notes) -> list[dict[str, Any]]:
    return [dataclasses.asdict(hypothesis) for hypothesis in notes.hypotheses]


def _shown_dicts(notes: Notes) -> list[dict[str, Any]]:
    """Hypothesis dicts plus `shown_text`, the harness sentence the decision prompt shows in place of `text`."""
    return [{**dataclasses.asdict(h), "shown_text": shown_line(h)} for h in notes.hypotheses]


# ---------- MemoryState ----------

REWRITE_EVERY = 5  # hands between rewrites
RECENT_HANDS = 5  # raw hands shown in a rewrite prompt


class MemoryState:
    """One match's memory: the tally, the notes, and the hands they came from.

    The caller makes the model call: when due(), send rewrite_prompt() and pass the reply
    to apply_rewrite(). Make a new MemoryState per match, so every match starts empty.

    Duplicate dealing deals each seed twice (decision 5), so a hand from the first deal
    would show the model the board, and maybe its own cards, of the deal still to come.
    observe() therefore holds the first deal of a pair as pending and commits both hands
    to the tally and the recent hands only once the second deal (same seed) arrives.
    """

    def __init__(self, model_name: str):
        self.model_name = model_name
        self.tally = OpponentTally(model_name)
        self.notes = Notes()
        self.recent: deque[HandRecord] = deque(maxlen=RECENT_HANDS)
        self._pending: dict[int, HandRecord] = {}  # seed -> first deal of its pair
        self._rewritten_through = 0  # committed hands // REWRITE_EVERY at the last rewrite

    def observe(self, record: HandRecord) -> None:
        first = self._pending.pop(record.seed, None)
        if first is None:
            self._pending[record.seed] = record
            return
        for committed in (first, record):
            self.tally.observe(committed)
            self.recent.append(committed)

    def is_pending(self, hand_number: int) -> bool:
        """True while this hand is held back waiting for the second deal of its pair."""
        return any(record.hand_number == hand_number for record in self._pending.values())

    def due(self) -> bool:
        """True once the committed hands pass another multiple of REWRITE_EVERY since the last rewrite.

        Pairs commit two hands at a time, so with REWRITE_EVERY = 5 rewrites come after
        6, 10, 16, 20, ... committed hands.
        """
        return self.tally.hands // REWRITE_EVERY > self._rewritten_through

    def apply_rewrite(self, response: Optional[str]) -> MemoryEvent:
        """Parse the model's rewrite, verify it against the tally, make it the notes, and log it.

        If nothing parses, the old reads are kept but re-verified against the current tally,
        so their counts and statuses never go stale.
        """
        old = self.notes
        parsed = parse_rewrite(response, old)
        if parsed.parse_failed:  # the model cited nothing new: refresh the old reads' counts, then re-gate
            checked = refresh(old, self.tally)
        else:
            checked = verify(parsed.notes, self.tally)
        self.notes = checked.notes
        self._rewritten_through = self.tally.hands // REWRITE_EVERY
        return MemoryEvent(
            hand_number=self.recent[-1].hand_number if self.recent else None,
            hands_seen=self.tally.hands,
            old_notes=_as_dicts(old),
            raw_response=response,
            parsed_notes=_as_dicts(parsed.notes),
            verified_notes=_shown_dicts(checked.notes),
            tally=self.tally.snapshot(),
            flags={
                "count_mismatch": bool(checked.count_mismatches),
                "unverifiable": bool(checked.unverifiable),
                "unlisted_key": bool(checked.unlisted_keys),
                "duplicate_key": bool(checked.duplicate_keys),
                "parse_failed": parsed.parse_failed,
                "truncated": parsed.truncated,
                "junk_lines": bool(parsed.junk_lines),
                "dropped_lines": bool(parsed.dropped),
            },
            count_mismatches=checked.count_mismatches,
            unverifiable=checked.unverifiable,
            unlisted_keys=checked.unlisted_keys,
            duplicate_keys=checked.duplicate_keys,
            junk_lines=parsed.junk_lines,
            dropped_lines=parsed.dropped,
        )

    def restore(self, event: dict[str, Any]) -> None:
        """Take a logged MemoryEvent's notes as if its rewrite were just applied (resume, no model call).

        The event must come from this same point in the match: its hands_seen must equal the
        committed hands re-observed so far (ValueError otherwise).
        """
        if event["hands_seen"] != self.tally.hands:
            raise ValueError(
                f"memory event logged at {event['hands_seen']} committed hands, but {self.tally.hands} are committed"
            )
        fields = {field.name for field in dataclasses.fields(Hypothesis)}  # not the logged-only shown_text
        self.notes = Notes(tuple(
            Hypothesis(**{k: v for k, v in hypothesis.items() if k in fields}) for hypothesis in event["verified_notes"]
        ))
        self._rewritten_through = self.tally.hands // REWRITE_EVERY

    def rewrite_prompt(self) -> str:
        return build_rewrite_prompt(self.notes, self.tally, list(self.recent), self.model_name)

    def notes_block(self) -> str:
        return render_notes_block(self.notes)


# Bump this on any change to the memory prompts (rewrite system or user prompt, tally text),
# the notes header, the nudge, the evidence wording or the verify/gate rules: a resume refuses
# a run logged under another version, so one match never mixes two memory setups.
# v2: the tally lists only the dominant side of each complementary key pair.
# v3: each tally key is its own ready-to-copy `key K | for N | against M` line, and the
#     previous notes show each read with the tally's current counts.
# v4: a read citing a key the tally text doesn't list is dropped (unlisted_key); 0/0 keys
#     aren't listed, nor faced_bet.call unless calling was the most common answer to a bet.
# v5: the harness writes every notes line the model sees: the decision prompt shows each read's
#     evidence sentence and status, the rewrite prompt's previous notes show the evidence, key,
#     current counts and status; the model's text is logged only. A read citing a key an
#     earlier read cites is dropped (duplicate_key).
MEMORY_VERSION = "memory-v5"


def memory_settings() -> dict[str, Any]:
    """Every constant that shapes the memory setup, for metadata.json (a resume must match them)."""
    return {
        "memory_version": MEMORY_VERSION,
        "rewrite_every": REWRITE_EVERY,
        "recent_hands": RECENT_HANDS,
        "max_hypotheses": MAX_HYPOTHESES,
        "word_budget": WORD_BUDGET,
        "notes_block_char_cap": NOTES_BLOCK_CHAR_CAP,
        "leak_threshold": LEAK_THRESHOLD,
        "hand_frequency_threshold": HAND_FREQUENCY_THRESHOLD,
        "max_against_share": MAX_AGAINST_SHARE,
        "shown_hands": SHOWN_HANDS,
        "rewrite_system_prompt": REWRITE_SYSTEM_PROMPT,
    }
