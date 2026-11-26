"""Poker memory (docs/poker-plan.md, "Memory" and decisions 2 and 14).

The harness keeps the ground truth, an OpponentTally of the opponent's actions per
opportunity, and the model writes the interpretation: Notes of at most 3 hypotheses,
rewritten in full every 5 hands. The harness, not the model, checks each cited count
against the tally and sets each hypothesis's status.
"""

import dataclasses
from collections import Counter
from dataclasses import dataclass
import re
from typing import Any, Optional

from poker.engine import CALL, CHECK, FOLD, STREETS, DecisionState, HandRecord

POSTFLOP_STREETS = STREETS[1:]
FACED_BET_OUTCOMES = ("fold", "call", "raise", "continue", "no_raise")
CHECKED_TO_OUTCOMES = ("bet", "check")
MAX_HYPOTHESES = 3
WORD_BUDGET = 100  # words of hypothesis text across all notes; counts and status are extra
SHOWN_HANDS = 5  # showdown cards listed in the tally text, most recent first


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
        vpip = any(d.action not in (FOLD, CHECK) for d in preflop)
        raised = any(d.action not in (FOLD, CHECK, CALL) for d in preflop)
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

    def _of(self, key: str) -> str:
        happened, against = self.counts(key)
        return f"{key} {happened} of {happened + against}"

    def render(self) -> str:
        """Short text for the rewrite prompt. 'key X of N' means for X, against N - X."""
        lines = [
            f"hands dealt: {self.hands}",
            f"put money in voluntarily preflop: {self._of('preflop.vpip')} hands, {self._of('preflop.no_vpip')}",
            f"raised preflop: {self._of('preflop.raise')} hands, {self._of('preflop.no_raise')}",
        ]
        faced = self._opportunities["faced_bet.fold"]
        fold, call, raised = (self._yes[f"faced_bet.{name}"] for name in ("fold", "call", "raise"))
        lines.append(f"faced a bet {faced} times: folded {fold}, called {call}, raised {raised}")
        lines.append("  " + ", ".join(self._of(f"faced_bet.{name}") for name in FACED_BET_OUTCOMES))
        by_street = [
            f"{street} {self._opportunities[f'faced_bet.fold.{street}']} (folded {self._yes[f'faced_bet.fold.{street}']},"
            f" called {self._yes[f'faced_bet.call.{street}']}, raised {self._yes[f'faced_bet.raise.{street}']})"
            for street in STREETS
            if self._opportunities[f"faced_bet.fold.{street}"]
        ]
        if by_street:
            lines.append("  by street (keys like faced_bet.fold.flop): " + "; ".join(by_street))
        chances = self._opportunities["checked_to.bet"]
        lines.append(
            f"no bet to face after the flop {chances} times: bet {self._yes['checked_to.bet']},"
            f" checked {self._yes['checked_to.check']}"
        )
        lines.append("  " + ", ".join(self._of(f"checked_to.{name}") for name in CHECKED_TO_OUTCOMES))
        by_street = [
            f"{street} {self._opportunities[f'checked_to.bet.{street}']} (bet {self._yes[f'checked_to.bet.{street}']})"
            for street in POSTFLOP_STREETS
            if self._opportunities[f"checked_to.bet.{street}"]
        ]
        if by_street:
            lines.append("  by street (keys like checked_to.bet.flop): " + "; ".join(by_street))
        lines.append(f"went to showdown: {self._of('showdown.reached')} hands that saw a flop")
        if self.showdowns:
            shown = [f"hand {s.hand_number} {' '.join(s.cards)} on {' '.join(s.board)}" for s in self.showdowns[-SHOWN_HANDS:]]
            lines.append("showed at showdown: " + "; ".join(shown))
        return "\n".join(lines)

    def snapshot(self) -> dict[str, Any]:
        """JSON-ready copy of every count, for MemoryEvent logs."""
        return {
            "hands": self.hands,
            "counts": {key: list(self.counts(key)) for key in sorted(self._opportunities)},
            "showdowns": [dataclasses.asdict(shown) for shown in self.showdowns],
        }


RAISE = "raise"  # any bet or raise size, all-in included


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
    dropped: list[str]  # hypothesis lines past MAX_HYPOTHESES
    truncated: bool  # hypothesis text was cut to fit WORD_BUDGET
    parse_failed: bool  # no hypothesis parsed, so the previous notes were kept


def parse_rewrite(response: str, previous: Notes) -> ParseResult:
    """The model's rewrite as Notes; junk lines skipped, the previous notes kept if nothing parses."""
    hypotheses: list[Hypothesis] = []
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
    if not hypotheses:
        return ParseResult(previous, junk, dropped, False, True)
    kept, truncated = _fit_word_budget(hypotheses)
    return ParseResult(Notes(tuple(kept)), junk, dropped, truncated, False)


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
    notes: Notes  # with the tally's true counts and the harness-set status
    count_mismatches: list[dict[str, Any]]  # cited counts the harness replaced
    unverifiable: list[str]  # texts of hypotheses whose key is not in OPPORTUNITY_KEYS


def verify(notes: Notes, tally: OpponentTally) -> VerifyResult:
    """Check every cited count against the tally, correcting mismatches, and set each status."""
    checked: list[Hypothesis] = []
    mismatches: list[dict[str, Any]] = []
    unverifiable: list[str] = []
    for hypothesis in notes.hypotheses:
        if hypothesis.opportunity_key not in OPPORTUNITY_KEYS:
            unverifiable.append(hypothesis.text)
            checked.append(dataclasses.replace(hypothesis, status=TENTATIVE))
            continue
        true_for, true_against = tally.counts(hypothesis.opportunity_key)
        if (hypothesis.for_count, hypothesis.against_count) != (true_for, true_against):
            mismatches.append({
                "text": hypothesis.text, "opportunity_key": hypothesis.opportunity_key,
                "cited": [hypothesis.for_count, hypothesis.against_count], "tally": [true_for, true_against],
            })
        checked.append(dataclasses.replace(
            hypothesis, for_count=true_for, against_count=true_against,
            status=status_for(hypothesis.opportunity_key, true_for, true_against),
        ))
    return VerifyResult(Notes(tuple(checked)), mismatches, unverifiable)


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


def build_rewrite_prompt(
    previous: Notes, tally: OpponentTally, recent_hands: list[HandRecord], model_name: str
) -> str:
    """The every-5-hands prompt: rewrite the notes in full from the tally and the last hands."""
    old = "\n".join(h.cited_line() for h in previous.hypotheses) or "(none yet)"
    hands = "\n".join(render_hand(record, model_name) for record in recent_hands) or "(none)"
    return f"""You are playing heads-up no-limit Hold'em and keep short notes about your opponent's habits.
Rewrite your notes in full from the evidence below. Do not just add to the old notes: keep a line only if the counts still support it.

Previous notes; revise or discard based on the counts below:
{old}

Opponent tally after {tally.hands} hands (counted by the harness from what you could see; "key X of N" means for X, against N - X):
{tally.render()}

Last {len(recent_hands)} hands ("opp" is your opponent):
{hands}

Write at most {MAX_HYPOTHESES} hypotheses about how the opponent plays, one per line, in exactly this format:
<what the opponent does> | key <tally key> | for <N> | against <M>
Each line must cite one tally key from above (for example faced_bet.fold or preflop.vpip) and copy its for and against counts: for counts the times it happened, against the other opportunities.
Keep all the lines under {WORD_BUDGET} words in total. Output only the hypothesis lines, nothing else."""


# ---------- Decision-time notes block ----------

NOTES_BLOCK_CHAR_CAP = 900  # fixed budget, so memory-on prompts differ from memory-off only by this block
_NOTES_HEADER = "Your notes on the opponent (counts checked by the harness):"
_NUDGE = (
    "CONFIRMED reads rest on enough opportunities to act on; "
    "TENTATIVE reads should only nudge your play, not override it."
)


def render_notes_block(notes: Notes) -> str:
    """The capped notes block for the decision prompt; empty while there are no notes."""
    if not notes.hypotheses:
        return ""
    room = NOTES_BLOCK_CHAR_CAP - len(_NOTES_HEADER) - len(_NUDGE) - 1  # newline after the header
    lines: list[str] = []
    for hypothesis in notes.hypotheses:
        line = "- " + hypothesis.line()
        if len(line) + 1 > room:  # cut the text, never the counts and status
            tail = line[len("- " + hypothesis.text):]
            text_room = room - 1 - len("- ") - len(tail)
            if text_room <= 0:
                break
            line = "- " + hypothesis.text[:text_room] + tail
        lines.append(line)
        room -= len(line) + 1
    return "\n".join([_NOTES_HEADER, *lines, _NUDGE])
