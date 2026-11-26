"""Builds the poker decision prompt: a system message with the rules and reply format,
and a user message with the current hand only (docs/poker-plan.md, decision 12).

The user message shows the cards, the street, the pot and stacks, this hand's actions
(as "you" and "opponent"), and a numbered menu of only the legal actions with exact
chip amounts. Nothing from earlier hands goes in, except the optional opponent
notes block (the memory hook, docs/poker-plan.md "Memory"): memory-on and memory-off
prompts differ only by that block.
"""

from typing import Optional

from poker.engine import (
    ALL_IN, BIG_BLIND, CALL, CHECK, FOLD, RAISE_HALF_POT, RAISE_POT, SMALL_BLIND, STARTING_STACK, STREETS,
    Action, DecisionState, MenuItem,
)

# Bump this whenever any prompt text changes; it is logged and checked on resume.
# v2: the answer format asks for the exact menu name, says bets use the raise_* names, gives an example.
PROMPT_VERSION = "poker-v2"

# The memory hook's block heading, the only one (poker.memory.render_notes_block writes the
# lines under it). Prompts without notes never contain it.
NOTES_HEADER = (
    "Your notes on this opponent from earlier hands (the quoted reads are yours; "
    "the evidence is counted by the harness):"
)

_RANK_WORDS = {
    "2": "two", "3": "three", "4": "four", "5": "five", "6": "six", "7": "seven", "8": "eight",
    "9": "nine", "T": "ten", "J": "jack", "Q": "queen", "K": "king", "A": "ace",
}
_SUIT_WORDS = {"c": "clubs", "d": "diamonds", "h": "hearts", "s": "spades"}
_SIZE_WORDS = {RAISE_HALF_POT: "half pot", RAISE_POT: "pot", ALL_IN: "all-in"}

FORMAT_INSTRUCTION = (
    "First explain your reasoning in two or three sentences. Then end your reply with a final line "
    "of exactly the form `ACTION: <action name>`, using the exact action name of one item in the "
    "numbered list. To bet or raise, answer with raise_half_pot, raise_pot or all_in, never \"bet\". "
    "For example: ACTION: raise_half_pot"
)


def build_system_prompt() -> str:
    """The game, the rules in plain words, and the reply format."""
    lines = [
        "You are playing heads-up no-limit Texas Hold'em against one opponent.",
        "",
        "Rules:",
        f"- Blinds are {SMALL_BLIND}/{BIG_BLIND}: the button posts the small blind of {SMALL_BLIND} chip, "
        f"the other player posts the big blind of {BIG_BLIND} chips.",
        f"- Both players start every hand with 100 big blinds ({STARTING_STACK} chips). Stacks are reset "
        "each hand, so every hand is scored on its own.",
        "- The button alternates every hand. The button acts first before the flop and last after it.",
        "- You get two hole cards; five board cards are dealt (flop 3, turn 1, river 1). The best "
        "five-card hand from your two cards and the board wins at showdown.",
        "- Cards are written rank then suit: A K Q J T(=10) 9-2, and c d h s for clubs, diamonds, hearts, spades.",
        "- \"Raise to X\" (or \"bet X\") means your total bet on this street becomes X chips.",
        "",
        FORMAT_INSTRUCTION,
    ]
    return "\n".join(lines)


def notes_block(notes: str) -> str:
    """The opponent notes block exactly as it sits in the prompt (just before the legal actions)."""
    return f"{NOTES_HEADER}\n{notes}\n\n"


def build_user_prompt(state: DecisionState, notes: Optional[str] = None) -> str:
    """The decision prompt for one state: the current hand only.

    `notes` is the memory setup's opponent notes block (docs/poker-plan.md, "Memory"):
    when given, notes_block(notes) is the only difference from the prompt without notes.
    None or "" means no block.
    """
    seat = (
        "You are on the button (small blind): you act first before the flop and last after it."
        if state.is_button
        else "You are in the big blind: you act last before the flop and first after it."
    )
    board = f"{' '.join(state.board)} ({_card_words(state.board)})" if state.board else "none yet"
    lines = [
        seat,
        f"Your hole cards: {' '.join(state.hole_cards)} ({_card_words(state.hole_cards)})",
        f"Board: {board}",
        f"Street: {state.street}",
        f"Pot: {state.pot} chips",
        f"Your stack: {state.stack} chips",
        f"Opponent's stack: {state.opponent_stack} chips",
        f"To call: {state.to_call} chips",
        "",
        "Actions this hand:",
        *history_lines(state),
        "",
    ]
    prompt = "\n".join(lines) + "\n"
    if notes:
        prompt += notes_block(notes)
    return prompt + "\n".join(["Legal actions:", *menu_lines(state)])


def history_lines(state: DecisionState) -> list[str]:
    """The blinds, then one line per street so far, with "you" and "opponent" for the seats."""
    def who(seat: str) -> str:
        return "you" if seat == state.seat else "opponent"

    small, big = (("you", "opponent") if state.is_button else ("opponent", "you"))
    lines = [f"Blinds posted: {small} {SMALL_BLIND} (small blind), {big} {BIG_BLIND} (big blind)."]
    for street in STREETS[: STREETS.index(state.street) + 1]:
        actions = [action for action in state.history if action.street == street]
        if not actions:
            lines.append(f"{street.capitalize()}: no actions yet.")
            continue
        words = []
        bet_made = street == "preflop"  # the big blind counts as the bet preflop
        for action in actions:
            words.append(f"{who(action.seat)} {_action_words(action, who(action.seat) == 'you', bet_made)}")
            bet_made = bet_made or action.action not in (FOLD, CHECK, CALL)
        lines.append(f"{street.capitalize()}: {'; '.join(words)}.")
    return lines


def _action_words(action: Action, is_you: bool, bet_made: bool) -> str:
    """e.g. "raise to 6" / "raises to 6", "bet 6" / "bets 6", "call 4" / "calls 4"."""
    if action.action in (FOLD, CHECK, CALL):
        verb, amount = action.action, (f" {action.amount}" if action.action == CALL else "")
    else:
        verb, amount = ("raise", f" to {action.amount}") if bet_made else ("bet", f" {action.amount}")
    return (verb if is_you else verb + "s") + amount


def menu_lines(state: DecisionState) -> list[str]:
    """The numbered menu, e.g. "4. raise_pot - raise to 30 (pot)". Numbers start at 1."""
    # With nothing to face after the flop a raise is an opening bet; preflop the big blind counts as one.
    verb = "bet" if state.to_call == 0 and state.street != "preflop" else "raise to"
    return [f"{number}. {item.action} - {_describe(item, verb)}" for number, item in enumerate(state.menu, start=1)]


def _describe(item: MenuItem, verb: str) -> str:
    if item.action == FOLD:
        return "give up the hand"
    if item.action == CHECK:
        return "bet nothing"
    if item.action == CALL:
        return f"call {item.amount}"
    return f"{verb} {item.amount} ({_SIZE_WORDS.get(item.action, item.action)})"


def _card_words(cards) -> str:
    return ", ".join(f"{_RANK_WORDS[card[0]]} of {_SUIT_WORDS[card[1]]}" for card in cards)
