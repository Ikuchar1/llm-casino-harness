"""Runs one poker match: one model, one setup, one bot, N duplicate seed pairs.

The match is laid out as a deal schedule (engine-independent): seed i is dealt as
hands 2i (model on the button) and 2i+1 (bot on the button), the same order as
poker.engine.play_match. The runner plays each deal with play_hand, so a resumed
match replays only the deals missing from hands.jsonl, even halfway through a pair.

In the memory setup (docs/poker-plan.md, "Memory") the runner keeps one MemoryState per
match: it observes every hand, makes the notes rewrite call when one is due, logs each
rewrite to memory.jsonl, and shows the notes block in every decision prompt after the
first rewrite. A resume rebuilds the memory from the logged hands and the logged
rewrites, without calling the model, except for a rewrite the interruption cut off.
"""

import importlib.metadata
import json
import random
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

from agent.config import HarnessConfig
from poker.engine import Player, play_hand
from poker.llm_player import tools_settings
from poker.parser import PARSER_VERSION
from poker.memory import MemoryState, memory_settings
from poker.prompt import PROMPT_VERSION
from poker.run_log import PokerRunWriter, decision_rows, hand_row, record_from_rows

REPO_ROOT = Path(__file__).resolve().parent.parent

# The LLM detail merged into every decision row, after the engine's fields. Bot rows
# (and rows of scripted stand-ins for the model) have None for each.
LLM_FIELDS = {
    "prompt": "user_prompt",
    "raw_response": "raw_response",
    "parsed_action": "parsed_action",
    "parse_status": "parse_status",
    "parse_method": "parse_method",
    "named_action": "named_action",
    "mapping": "mapping",
    "done_reason": "done_reason",
    "eval_count": "eval_count",
    "prompt_tokens": "prompt_tokens",
    "latency_s": "latency_s",  # the first call only
    "total_latency_s": "total_latency_s",  # every call of the decision: the first plus the tools setups' re-check
    "tools": "tools",  # the tools setups only: what the equity and chart lines showed
    "self_check": "self_check",  # the tools setups only: the first answer and the re-check
    "flags": "flags",  # the tools setups only: poker.self_check.flags() on the first answer, never shown
}
# After those, every decision row has "notes_version": the index in memory.jsonl of the
# rewrite whose notes the model's prompt showed; None before the first rewrite, for bot
# rows, and in every setup without memory.

# Run facts a resume never overwrites: the weights and server the run started with.
KEPT_ON_RESUME = ("model_digest", "ollama_version")

# Player names in the logs (seats swap every hand; these names don't).
MODEL = "model"
BOT = "bot"


@dataclass(frozen=True)
class MatchSpec:
    """What makes a match this match: one model, one setup, one bot, the seeds."""

    model: str
    setup: HarnessConfig
    bot: str
    base_seed: int
    n_pairs: int


@dataclass(frozen=True)
class Deal:
    """One hand of the match: which seed, and who is on the button."""

    hand_number: int
    seed: int
    button: str


def match_seeds(base_seed: int, n_pairs: int) -> list[int]:
    """The match's deck seeds. Same base seed -> same list, in every setup and model.

    Drawn one after another from random.Random(base_seed), so a longer list starts with
    the shorter one. Duplicates are skipped, so every pair has its own deck.
    """
    rng = random.Random(base_seed)
    seeds: list[int] = []
    while len(seeds) < n_pairs:
        seed = rng.getrandbits(31)
        if seed not in seeds:
            seeds.append(seed)
    return seeds


def deal_schedule(seeds: list[int]) -> list[Deal]:
    """Every deal of the match in order: each seed twice, model on the button first."""
    return [
        Deal(hand_number=2 * index + offset, seed=seed, button=button)
        for index, seed in enumerate(seeds)
        for offset, button in enumerate((MODEL, BOT))
    ]


def resolve_bot(name: str, registry: Optional[Mapping[str, Callable[[], Player]]] = None) -> Player:
    """A fresh bot by name. The registry defaults to poker.bots.BOTS, imported only here
    so tests (and runs) can pass their own name -> factory map instead."""
    if registry is None:
        from poker.bots import BOTS

        registry = BOTS
    try:
        factory = registry[name]
    except KeyError:
        raise ValueError(f"unknown bot {name!r} (choose from {', '.join(registry)})") from None
    return factory()


@dataclass
class Progress:
    """Running totals after each hand, for the progress line."""

    hand_number: int
    hands_done: int  # in this run directory, including resumed ones
    hands_total: int
    model_chips: int  # the model's chip result so far
    decisions: int  # the model's decisions so far
    fallbacks: int  # the model's decisions that fell back to check or fold
    seconds_per_hand: float  # this session only


def run_match(
    out_dir: Path | str,
    spec: MatchSpec,
    player: Player,
    bots: Optional[Mapping[str, Callable[[], Player]]] = None,
    extra_metadata: Optional[dict[str, Any]] = None,
    on_hand: Optional[Callable[[Progress], None]] = None,
    session_metadata: Optional[dict[str, Any]] = None,
) -> Optional[Progress]:
    """Play every deal of the match that isn't in out_dir's hands.jsonl yet, logging each hand.

    metadata.json is created on the first call; a later call on the same directory
    resumes the same run (same run_id) and adds a session, which records its git_commit and
    session_metadata (e.g. platform_info(): a resumed job may land on another node). A resume keeps the
    run's first model_digest and ollama_version (KEPT_ON_RESUME). Errors from the player (e.g.
    Ollama down) propagate after the session is marked; the interrupted hand is not
    written, so the next call replays just that deal, even halfway through a pair.
    """
    out_dir = Path(out_dir)
    bot = resolve_bot(spec.bot, bots)
    seeds = match_seeds(spec.base_seed, spec.n_pairs)
    extra_metadata = extra_metadata or {}
    metadata = _load_or_new_metadata(out_dir, spec, seeds, extra_metadata)
    writer = PokerRunWriter(out_dir)
    metadata.update(getattr(player, "run_metadata", dict)())
    metadata.update({key: value for key, value in extra_metadata.items()
                     if not (key in KEPT_ON_RESUME and key in metadata)})
    session: dict[str, Any] = {"started_at": _now_iso(), "ended_at": None, "status": "running",
                               "git_commit": metadata["git_commit"], **(session_metadata or {})}
    metadata["sessions"].append(session)
    _save(out_dir, metadata)
    identity = {key: metadata[key] for key in ("run_id", "model", "setup", "bot")}
    schedule = deal_schedule(seeds)
    wanted = {deal.hand_number for deal in schedule}
    previous = [row for row in writer.hand_rows() if row["hand_number"] in wanted]
    done = {row["hand_number"] for row in previous}
    memory = MemoryState(MODEL) if spec.setup.memory else None
    events: list[dict[str, Any]] = []  # memory.jsonl rows, in order; an index is a notes_version
    progress = None
    totals = {
        "chips": sum(row["chip_delta"][MODEL] for row in previous),
        "decisions": sum(row.get("num_model_decisions", 0) for row in previous),
        "fallbacks": sum(row.get("num_model_fallbacks", 0) for row in previous),
    }
    start, session_hands = time.perf_counter(), 0
    try:
        if memory is not None:
            _rebuild_memory(out_dir, memory, previous, writer, player, identity, events)
        for deal in schedule:
            if deal.hand_number in done:
                continue
            take_details = getattr(player, "take_hand_details", list)
            take_details()  # start the hand with an empty buffer
            notes_version = len(events) - 1 if events else None
            if memory is not None and hasattr(player, "notes"):
                player.notes = memory.notes_block() or None
            record = play_hand(deal.seed, {MODEL: player, BOT: bot}, button=deal.button, hand_number=deal.hand_number)
            hand = {**identity, **hand_row(record), **_model_counts(record)}
            writer.write_rows(_decision_rows(record, take_details(), identity, notes_version), hand)
            if memory is not None:
                memory.observe(record)
                if memory.due():
                    _rewrite_notes(memory, player, writer, identity, events)
            done.add(deal.hand_number)
            session_hands += 1
            totals["chips"] += record.chip_delta[MODEL]
            totals["decisions"] += hand["num_model_decisions"]
            totals["fallbacks"] += hand["num_model_fallbacks"]
            progress = Progress(
                hand_number=deal.hand_number,
                hands_done=len(done),
                hands_total=len(schedule),
                model_chips=totals["chips"],
                decisions=totals["decisions"],
                fallbacks=totals["fallbacks"],
                seconds_per_hand=(time.perf_counter() - start) / session_hands,
            )
            if on_hand is not None:
                on_hand(progress)
        session["status"] = "completed"
    except KeyboardInterrupt:
        session["status"] = "interrupted"
        raise
    except Exception as error:
        session["status"] = "error"
        session["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        session["ended_at"] = _now_iso()
        metadata["ended_at"] = session["ended_at"]
        _save(out_dir, metadata)
    return progress


def _rebuild_memory(out_dir: Path, memory: MemoryState, previous: list[dict[str, Any]], writer: PokerRunWriter,
                    player: Player, identity: dict[str, Any], events: list[dict[str, Any]]) -> None:
    """On a resume, bring the match's memory back to where the logs stop, without the model.

    The completed hands are re-observed in order; each rewrite that falls due is restored
    from memory.jsonl. Only a rewrite due after the last logged hand may be missing (the
    run stopped between that hand and its rewrite), and that one is made now. Any other
    gap, or a rewrite logged with no hand that made it due, raises ValueError.
    """
    logged = writer.memory_rows()
    rows_by_hand: dict[int, list[dict[str, Any]]] = {}
    for row in writer.decision_rows():
        rows_by_hand.setdefault(row["hand_number"], []).append(row)
    for position, hand in enumerate(previous):
        memory.observe(record_from_rows(hand, rows_by_hand.get(hand["hand_number"], [])))
        if not memory.due():
            continue
        if len(events) < len(logged):
            memory.restore(logged[len(events)])
            events.append(logged[len(events)])
        elif position == len(previous) - 1:
            _rewrite_notes(memory, player, writer, identity, events)
        else:
            raise ValueError(f"cannot resume {out_dir}: memory.jsonl has no logged rewrite after hand {hand['hand_number']}")
    if len(events) < len(logged):
        raise ValueError(f"cannot resume {out_dir}: memory.jsonl has {len(logged)} rewrites, the hands make {len(events)} due")


def _rewrite_notes(memory: MemoryState, player: Player, writer: PokerRunWriter, identity: dict[str, Any],
                   events: list[dict[str, Any]]) -> None:
    """Make the due rewrite with the player's model and log it to memory.jsonl.

    A scripted stand-in has no rewrite_notes, so its rewrites get no reply: they are
    logged as parse failures that keep the (empty) notes.
    """
    prompt = memory.rewrite_prompt()
    rewrite = getattr(player, "rewrite_notes", None)
    reply = rewrite(prompt) if rewrite is not None else None
    event = memory.apply_rewrite(reply.content if reply is not None else None)
    row = {
        **identity,
        "notes_version": len(events),
        "rewrite_prompt": prompt,
        **event.to_dict(),
        "notes_block": memory.notes_block(),
        "done_reason": reply.done_reason if reply is not None else None,
        "eval_count": reply.eval_count if reply is not None else None,
        "prompt_tokens": reply.prompt_eval_count if reply is not None else None,
        "latency_s": round(reply.latency_s, 3) if reply is not None else None,
    }
    writer.write_memory(row)
    events.append(row)


def _model_counts(record) -> dict[str, int]:
    """The model's decision and fallback counts for one hand (on the hand row)."""
    mine = [decision for decision in record.decisions if decision.player == MODEL]
    return {"num_model_decisions": len(mine), "num_model_fallbacks": sum(decision.fallback for decision in mine)}


def _load_or_new_metadata(out_dir: Path, spec: MatchSpec, seeds: list[int], extra: dict[str, Any]) -> dict[str, Any]:
    """The existing run's metadata (same run_id) when resuming, else a new run's.

    A resume must match the run's model, setup, bot, base seed, prompt/parser
    versions, memory settings and tool versions, and its model_digest when both runs have one (ValueError otherwise, as
    scripts/run_baseline.py refuses). The pair count may grow: the seed list only appends.
    """
    path = out_dir / "metadata.json"
    if not path.exists():
        return _new_metadata(spec, seeds)
    metadata = json.loads(path.read_text())
    expected = {
        "model": spec.model, "setup": spec.setup.name, "setup_flags": spec.setup.flags(), "bot": spec.bot,
        "base_seed": spec.base_seed, "prompt_version": PROMPT_VERSION, "parser_version": PARSER_VERSION,
        "memory": _memory_metadata(spec), "tools": tools_settings(spec.setup),
    }
    stored_version = (metadata.get("memory") or {}).get("memory_version")
    wanted_version = (expected["memory"] or {}).get("memory_version")
    if expected["memory"] is not None and stored_version != wanted_version:
        raise ValueError(f"cannot resume {out_dir}: it was run with memory_version={stored_version!r},"
                         f" not {wanted_version!r}")
    for key, value in expected.items():
        if metadata.get(key) != value:
            raise ValueError(f"cannot resume {out_dir}: it was run with {key}={metadata.get(key)!r}, not {value!r}")
    stored, digest = metadata.get("model_digest"), extra.get("model_digest")
    if stored is not None and digest is not None and stored != digest:
        raise ValueError(f"cannot resume {out_dir}: model_digest changed since this run started ({stored} -> {digest})")
    metadata.update({"n_pairs": spec.n_pairs, "n_hands": 2 * spec.n_pairs, "seeds": seeds,
                     "git_commit": git_commit()})
    return metadata


def _decision_rows(record, details: list, identity: dict[str, Any],
                   notes_version: Optional[int] = None) -> list[dict[str, Any]]:
    """The engine's decision rows with the run identity first and the LLM detail last.

    `details` are the model player's, one per model decision in order (none for a
    scripted stand-in). `notes_version` goes on the model's rows only.
    """
    model_decisions = sum(decision.player == MODEL for decision in record.decisions)
    if details and len(details) != model_decisions:
        raise ValueError(f"{len(details)} details for {model_decisions} model decisions in hand {record.hand_number}")
    pending = iter(details)
    rows = []
    for decision, row in zip(record.decisions, decision_rows(record)):
        detail = next(pending) if details and decision.player == MODEL else None
        llm = {field: (getattr(detail, attribute) if detail else None) for field, attribute in LLM_FIELDS.items()}
        for timing in ("latency_s", "total_latency_s"):
            if llm[timing] is not None:
                llm[timing] = round(llm[timing], 3)
        version = notes_version if decision.player == MODEL else None
        rows.append({**identity, **row, **llm, "notes_version": version})
    return rows


def _memory_metadata(spec: MatchSpec) -> Optional[dict[str, Any]]:
    return memory_settings() if spec.setup.memory else None


def _new_metadata(spec: MatchSpec, seeds: list[int]) -> dict[str, Any]:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_id = f"poker_{spec.setup.name}_{spec.model.replace(':', '-')}_vs_{spec.bot}_seed{spec.base_seed}_{timestamp}"
    return {
        "run_id": run_id,
        "model": spec.model,
        "setup": spec.setup.name,
        "setup_flags": spec.setup.flags(),
        "bot": spec.bot,
        "base_seed": spec.base_seed,
        "n_pairs": spec.n_pairs,
        "n_hands": 2 * spec.n_pairs,
        "seeds": seeds,
        "prompt_version": PROMPT_VERSION,
        "parser_version": PARSER_VERSION,
        "memory": _memory_metadata(spec),
        "tools": tools_settings(spec.setup),
        "pokerkit_version": importlib.metadata.version("pokerkit"),
        "git_commit": git_commit(),
        "started_at": _now_iso(),
        "sessions": [],
    }


def git_commit() -> Optional[str]:
    """Current commit hash, with '-dirty' if there are uncommitted changes; None outside git."""
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None
    return commit + ("-dirty" if status else "")


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _save(out_dir: Path, metadata: dict[str, Any]) -> None:
    (out_dir / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
