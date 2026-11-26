"""Run one heads-up poker match: one model, one setup, one bot, N duplicate seed pairs.

Usage (from the repo root):
    .venv/bin/python scripts/run_poker.py --bot calling_station --pairs 50 --seed 2026
    .venv/bin/python scripts/run_poker.py --bot maniac --pairs 1 --seed 2026 --model qwen2.5:7b --out runs/smoke
    .venv/bin/python scripts/run_poker.py --player station --bot rock --pairs 5 --seed 1 --out /tmp/poker_test

Each seed is dealt twice (model on the button, then the bot), so --pairs N plays 2N
hands. --player random|station swaps the LLM for a scripted player (no Ollama needed),
for testing. Re-running with the same --out resumes the same run, even halfway
through a pair; model, setup, bot and seed must match.

Writes <out>/decisions.jsonl, hands.jsonl and metadata.json.
"""

import argparse
import platform
import random
import sys
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
# Let the script import the project packages when run from anywhere.
sys.path.insert(0, str(REPO_ROOT))

from agent.ollama_client import (  # noqa: E402
    DEFAULT_KEEP_ALIVE,
    DEFAULT_MODEL,
    DEFAULT_OPTIONS,
    OllamaClient,
    OllamaUnavailableError,
    get_model_digest,
    get_ollama_version,
    resolve_base_url,
)
from agent.platform_info import platform_info  # noqa: E402
from poker.engine import DecisionState  # noqa: E402
from poker.llm_player import SETUPS, PokerLLMPlayer  # noqa: E402
from poker.runner import MatchSpec, Progress, run_match  # noqa: E402

# name -> bot factory; None means poker.bots.BOTS (tests swap in scripted bots).
BOT_REGISTRY: Optional[Mapping[str, Callable[[], Any]]] = None

BIG_BLIND = 2


class StationPlayer:
    """Scripted stand-in for the model: checks when it can, else calls."""

    def decide(self, state: DecisionState) -> str:
        return "check" if any(item.action == "check" for item in state.menu) else "call"


class RandomPlayer:
    """Scripted stand-in for the model: a seeded uniform pick from the menu."""

    def __init__(self, seed: int):
        self.rng = random.Random(seed)

    def decide(self, state: DecisionState) -> str:
        return self.rng.choice(state.menu).action


SCRIPTED_PLAYERS = ("random", "station")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one heads-up poker match against a bot.")
    parser.add_argument("--bot", required=True, help="opponent bot name (see poker/bots.py)")
    parser.add_argument("--pairs", type=int, required=True, help="number of seed pairs (2 hands each)")
    parser.add_argument("--seed", type=int, required=True, help="base seed for the match's deck seeds")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Ollama model tag (default {DEFAULT_MODEL})")
    parser.add_argument("--setup", choices=list(SETUPS), default="plain", help="harness setup (default plain)")
    parser.add_argument("--out", type=Path, default=None, help="run directory (default runs/poker_<...>)")
    parser.add_argument("--player", choices=("llm", *SCRIPTED_PLAYERS), default="llm",
                        help="llm (default), or a scripted stand-in for testing without Ollama")
    return parser.parse_args()


def format_duration(seconds: float) -> str:
    minutes, secs = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes:02d}m" if hours else f"{minutes}m{secs:02d}s"


def print_progress(progress: Progress) -> None:
    bb_per_100 = 100 * progress.model_chips / BIG_BLIND / progress.hands_done if progress.hands_done else 0.0
    eta = format_duration((progress.hands_total - progress.hands_done) * progress.seconds_per_hand)
    print(
        f"hand {progress.hand_number:>4} ({progress.hands_done}/{progress.hands_total}) | "
        f"model chips {progress.model_chips:+d} ({bb_per_100:+.1f} bb/100) | "
        f"fallbacks {progress.fallbacks}/{progress.decisions} | "
        f"{progress.seconds_per_hand:.1f} s/hand | ETA {eta}",
        flush=True,
    )


def ollama_metadata(model: str) -> dict[str, Any]:
    """Facts about the Ollama server and model; raises RuntimeError when it can't be used."""
    url = resolve_base_url()  # OLLAMA_HOST if set, else localhost:11434
    try:
        digest = get_model_digest(model)
        version = get_ollama_version()
    except Exception as error:  # noqa: BLE001 - any failure here means Ollama isn't usable
        raise RuntimeError(f"could not reach Ollama at {url}: {error}") from error
    if digest is None:
        raise RuntimeError(f"model {model!r} is not installed in Ollama (try: ollama pull {model})")
    return {"model_digest": digest, "ollama_version": version, "ollama_url": url,
            "ollama_options": DEFAULT_OPTIONS, "keep_alive": DEFAULT_KEEP_ALIVE}


def main() -> int:
    args = parse_args()
    setup = SETUPS[args.setup]
    extra: dict[str, Any] = {"player": args.player, "python_version": platform.python_version(), **platform_info()}
    if args.player == "llm":
        model = args.model
        try:  # before anything is written, so an unbuilt setup leaves no run folder behind
            player: Any = PokerLLMPlayer(OllamaClient(model=model), setup)
        except NotImplementedError as error:
            print(f"ERROR: setup {setup.name!r} can't run yet: {error}", file=sys.stderr)
            return 2
        try:
            extra.update(ollama_metadata(model))
        except RuntimeError as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 1
    else:
        model = f"scripted-{args.player}"
        player = RandomPlayer(args.seed) if args.player == "random" else StationPlayer()

    out_dir = args.out or REPO_ROOT / "runs" / f"poker_{setup.name}_{model.replace(':', '-')}_vs_{args.bot}_seed{args.seed}"
    spec = MatchSpec(model=model, setup=setup, bot=args.bot, base_seed=args.seed, n_pairs=args.pairs)
    print(f"Poker match {model} ({setup.name}) vs {args.bot}, seed {args.seed}, "
          f"{args.pairs} pairs ({2 * args.pairs} hands) -> {out_dir}", flush=True)
    try:
        run_match(out_dir, spec, player, bots=BOT_REGISTRY, extra_metadata=extra, on_hand=print_progress)
    except ValueError as error:  # unknown bot, or a resume that doesn't match the run
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    except OllamaUnavailableError as error:
        print(f"\nERROR: stopping the match, Ollama is unavailable: {error}", file=sys.stderr)
        print("Nothing was logged for the interrupted hand. Re-run with the same --out to resume.", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nInterrupted. Re-run with the same --out to resume.", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
