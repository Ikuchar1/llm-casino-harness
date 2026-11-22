"""Run the baseline LLM player for N hands and log every decision.

Usage (from the repo root):
    .venv/bin/python scripts/run_baseline.py --hands 20 --seed 2026
    .venv/bin/python scripts/run_baseline.py --hands 500 --seed 2026 --model qwen2.5:7b --out runs/my_run
    .venv/bin/python scripts/run_baseline.py --hands 20 --seed 2026 --config prob

--config picks the harness config (default baseline; names in agent/config.py). It is
recorded in metadata.json and on every row, and a resume must use the same config.

Hands are numbered 1..N, so hand N with seed S has the same cards under every
harness config. Re-running with the same --out directory resumes: hands already
in hands.jsonl are skipped and new ones are appended.

Writes runs/<run_id>/decisions.jsonl, hands.jsonl and metadata.json.
"""

import argparse
import dataclasses
import json
import platform
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
# Let the script import the project packages when run from anywhere.
sys.path.insert(0, str(REPO_ROOT))

from agent.config import CONFIG_NAMES, HarnessConfig, get_config  # noqa: E402
from agent.llm_player import LLMPlayer  # noqa: E402
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
from agent.parser import PARSER_VERSION  # noqa: E402
from agent.platform_info import platform_info  # noqa: E402
from agent.prompt import PROMPT_VERSION  # noqa: E402
from agent.run_log import RunInfo, RunWriter, check_resume_compatible  # noqa: E402
from agent.runner import Progress, run_hands  # noqa: E402
from blackjack.rules import DEFAULT_RULES  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the baseline LLM blackjack player.")
    parser.add_argument("--hands", type=int, required=True, help="number of hands (numbered 1..N)")
    parser.add_argument("--seed", type=int, required=True, help="run seed for the per-hand shoes")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Ollama model tag (default {DEFAULT_MODEL})")
    parser.add_argument("--out", type=Path, default=None, help="run directory (default runs/<run_id>)")
    parser.add_argument("--config", choices=CONFIG_NAMES, default="baseline",
                        help="harness config (default baseline; see docs/ablation-plan.md)")
    return parser.parse_args()


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


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def format_duration(seconds: float) -> str:
    minutes, secs = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes:02d}m" if hours else f"{minutes}m{secs:02d}s"


def print_progress(progress: Progress) -> None:
    accuracy = 100 * progress.correct / progress.decisions if progress.decisions else 0.0
    remaining = progress.hands_total - progress.hands_done
    eta = format_duration(remaining * progress.seconds_per_hand)
    print(
        f"hand {progress.hand_number:>4} ({progress.hands_done}/{progress.hands_total}) | "
        f"decisions {progress.hand_decisions} (total {progress.decisions}) | "
        f"accuracy {accuracy:5.1f}% ({progress.correct}/{progress.decisions}) | "
        f"invalid {progress.invalid} | payout {progress.payout:+g} | "
        f"{progress.seconds_per_decision:.1f} s/decision | ETA {eta}",
        flush=True,
    )


def load_or_create_metadata(
    out_dir: Optional[Path], args: argparse.Namespace, config: HarnessConfig
) -> tuple[Path, dict[str, Any]]:
    """Reuse metadata.json when resuming (and check it matches); otherwise start a new run."""
    if out_dir is not None and (out_dir / "metadata.json").exists():
        metadata = json.loads((out_dir / "metadata.json").read_text())
        expected = {
            "model": args.model,
            "run_seed": args.seed,
            "harness_config": config.name,
            "prompt_version": PROMPT_VERSION,
            "parser_version": PARSER_VERSION,
        }
        try:
            check_resume_compatible(metadata, expected)
        except ValueError as error:
            sys.exit(f"Cannot resume {out_dir}: {error}.")
        return out_dir, metadata

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_id = f"{config.name}_{args.model.replace(':', '-')}_seed{args.seed}_{timestamp}"
    out_dir = out_dir if out_dir is not None else REPO_ROOT / "runs" / run_id
    metadata = {
        "run_id": run_id,
        "model": args.model,
        "harness_config": config.name,
        "harness_flags": config.flags(),
        "prompt_version": PROMPT_VERSION,
        "parser_version": PARSER_VERSION,
        "run_seed": args.seed,
        "started_at": now_iso(),
        "sessions": [],
    }
    return out_dir, metadata


def main() -> int:
    args = parse_args()
    config = get_config(args.config)
    try:  # before anything is written, so an unbuilt config leaves no run folder behind
        player = LLMPlayer(OllamaClient(model=args.model), config, DEFAULT_RULES)
    except NotImplementedError as error:
        print(f"ERROR: harness config {config.name!r} can't run yet: {error}", file=sys.stderr)
        return 2
    out_dir, metadata = load_or_create_metadata(args.out, args, config)
    out_dir.mkdir(parents=True, exist_ok=True)

    ollama_url = resolve_base_url()  # OLLAMA_HOST if set, else localhost:11434
    try:
        digest = get_model_digest(args.model)
        ollama_version = get_ollama_version()
    except Exception as error:  # noqa: BLE001 - any failure here means Ollama isn't usable
        print(f"ERROR: could not reach Ollama at {ollama_url}: {error}", file=sys.stderr)
        return 1
    if digest is None:
        print(f"ERROR: model {args.model!r} is not installed in Ollama (try: ollama pull {args.model})", file=sys.stderr)
        return 1
    if metadata.get("model_digest") not in (None, digest):
        print(f"ERROR: model digest changed since this run started ({metadata['model_digest']} -> {digest}).",
              file=sys.stderr)
        return 1

    where = platform_info()  # also kept per session: a resumed job may land on another node
    metadata.update({
        "model_digest": digest,
        "ollama_version": ollama_version,
        "ollama_url": ollama_url,
        "ollama_options": DEFAULT_OPTIONS,
        "keep_alive": DEFAULT_KEEP_ALIVE,
        "rule_set": dataclasses.asdict(DEFAULT_RULES),
        **player.run_metadata(),  # system_prompt, plus strategy-info / self-eval versions when on
        "n_hands": args.hands,
        "python_version": platform.python_version(),
        **where,  # hostname, platform, gpus, slurm_job_id of the latest session
        "git_commit": git_commit(),
    })
    session = {"started_at": now_iso(), "ended_at": None, "status": "running", **where}
    metadata["sessions"].append(session)

    def save_metadata() -> None:
        (out_dir / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")

    save_metadata()

    info = RunInfo(
        run_id=metadata["run_id"],
        model=args.model,
        model_digest=digest,
        harness_config=config,
        run_seed=args.seed,
        ollama_seed=DEFAULT_OPTIONS.get("seed"),
        prompt_version=PROMPT_VERSION,
        parser_version=PARSER_VERSION,
    )
    writer = RunWriter(out_dir)
    already = len(writer.completed_hands() & set(range(1, args.hands + 1)))
    print(f"Run {info.run_id} -> {out_dir}")
    print(f"Model {args.model} ({digest[:12]}), seed {args.seed}, hands 1..{args.hands}"
          + (f", resuming ({already} already done)" if already else ""), flush=True)

    exit_code = 0
    try:
        run_hands(player, writer, info, range(1, args.hands + 1), DEFAULT_RULES, on_hand=print_progress)
        session["status"] = "completed"
    except OllamaUnavailableError as error:
        session["status"] = "ollama_unavailable"
        print(f"\nERROR: stopping the run, Ollama is unavailable: {error}", file=sys.stderr)
        print("Nothing was logged for the interrupted hand. Re-run with the same --out to resume.", file=sys.stderr)
        exit_code = 1
    except KeyboardInterrupt:
        session["status"] = "interrupted"
        print("\nInterrupted. Re-run with the same --out to resume.", file=sys.stderr)
        exit_code = 130
    finally:
        session["ended_at"] = now_iso()
        metadata["ended_at"] = session["ended_at"]
        save_metadata()
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
