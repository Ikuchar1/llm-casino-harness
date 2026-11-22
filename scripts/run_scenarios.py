"""Run the baseline LLM player on the scenario set: every basic strategy cell once.

Usage (from the repo root):
    .venv/bin/python scripts/run_scenarios.py --seed 2026 --out runs/scenarios_seed2026
    .venv/bin/python scripts/run_scenarios.py --seed 2026 --out runs/scenarios_smoke --limit 5

Uses the same model, prompt, parser and sampling as scripts/run_baseline.py. The
330 scenarios are played in a fixed order, and scenario i is logged as hand_number i.
--limit N plays only the first N (for smoke tests). Re-running with the same --out
resumes: scenarios already in hands.jsonl are skipped.

Writes the same decisions.jsonl / hands.jsonl / metadata.json as the baseline,
plus run_type, scenario_id and is_scenario_cell (see agent/scenario_runner.py).
Only rows with is_scenario_cell = true are the graded chart cells; returns from
this run are meaningless because the hands are not a natural sample.
"""

import argparse
import dataclasses
import json
import platform
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
# Let the script import the project packages when run from anywhere.
sys.path.insert(0, str(REPO_ROOT))

from agent.config import BASELINE  # noqa: E402
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
from agent.prompt import PROMPT_VERSION, build_system_prompt  # noqa: E402
from agent.run_log import RunInfo, RunWriter, check_resume_compatible  # noqa: E402
from agent.scenario_runner import RUN_TYPE, run_scenarios  # noqa: E402
from agent.scenarios import COMPOSITION_RULE, SCENARIO_SET_VERSION, build_scenarios  # noqa: E402
from blackjack.rules import DEFAULT_RULES  # noqa: E402
from scripts.run_baseline import git_commit, now_iso, print_progress  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the baseline LLM player on the scenario set.")
    parser.add_argument("--seed", type=int, required=True, help="run seed for the rest of each forced shoe")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Ollama model tag (default {DEFAULT_MODEL})")
    parser.add_argument("--out", type=Path, default=None, help="run directory (default runs/<run_id>)")
    parser.add_argument("--limit", type=int, default=None, help="play only the first N scenarios (smoke test)")
    return parser.parse_args()


def load_or_create_metadata(out_dir: Optional[Path], args: argparse.Namespace) -> tuple[Path, dict[str, Any]]:
    """Reuse metadata.json when resuming (and check it matches); otherwise start a new run."""
    if out_dir is not None and (out_dir / "metadata.json").exists():
        metadata = json.loads((out_dir / "metadata.json").read_text())
        expected = {
            "run_type": RUN_TYPE,
            "scenario_set_version": SCENARIO_SET_VERSION,
            "model": args.model,
            "run_seed": args.seed,
            "harness_config": BASELINE.name,
            "prompt_version": PROMPT_VERSION,
            "parser_version": PARSER_VERSION,
        }
        try:
            check_resume_compatible(metadata, expected)
        except ValueError as error:
            sys.exit(f"Cannot resume {out_dir}: {error}.")
        return out_dir, metadata

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_id = f"scenarios_{BASELINE.name}_{args.model.replace(':', '-')}_seed{args.seed}_{timestamp}"
    out_dir = out_dir if out_dir is not None else REPO_ROOT / "runs" / run_id
    metadata = {
        "run_id": run_id,
        "run_type": RUN_TYPE,
        "scenario_set_version": SCENARIO_SET_VERSION,
        "model": args.model,
        "harness_config": BASELINE.name,
        "harness_flags": BASELINE.flags(),
        "prompt_version": PROMPT_VERSION,
        "parser_version": PARSER_VERSION,
        "run_seed": args.seed,
        "started_at": now_iso(),
        "sessions": [],
    }
    return out_dir, metadata


def main() -> int:
    args = parse_args()
    all_scenarios = build_scenarios()
    scenarios = all_scenarios[: args.limit] if args.limit is not None else all_scenarios

    out_dir, metadata = load_or_create_metadata(args.out, args)
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

    metadata.update({
        "model_digest": digest,
        "ollama_version": ollama_version,
        "ollama_url": ollama_url,
        "ollama_options": DEFAULT_OPTIONS,
        "keep_alive": DEFAULT_KEEP_ALIVE,
        "rule_set": dataclasses.asdict(DEFAULT_RULES),
        "system_prompt": build_system_prompt(DEFAULT_RULES),
        "scenario_count": len(all_scenarios),
        "composition_rule": COMPOSITION_RULE,
        "n_hands": len(scenarios),  # scenarios played so far (smaller than scenario_count with --limit)
        "python_version": platform.python_version(),
        "git_commit": git_commit(),
    })
    session = {"started_at": now_iso(), "ended_at": None, "status": "running"}
    metadata["sessions"].append(session)

    def save_metadata() -> None:
        (out_dir / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")

    save_metadata()

    info = RunInfo(
        run_id=metadata["run_id"],
        model=args.model,
        model_digest=digest,
        harness_config=BASELINE,
        run_seed=args.seed,
        ollama_seed=DEFAULT_OPTIONS.get("seed"),
        prompt_version=PROMPT_VERSION,
        parser_version=PARSER_VERSION,
    )
    writer = RunWriter(out_dir)
    already = len(writer.completed_hands() & set(range(1, len(scenarios) + 1)))
    print(f"Run {info.run_id} -> {out_dir}")
    print(f"Model {args.model} ({digest[:12]}), seed {args.seed}, scenarios 1..{len(scenarios)} "
          f"of {len(all_scenarios)}" + (f", resuming ({already} already done)" if already else ""), flush=True)

    player = LLMPlayer(OllamaClient(model=args.model), BASELINE, DEFAULT_RULES)
    exit_code = 0
    try:
        run_scenarios(player, writer, info, scenarios, DEFAULT_RULES, on_hand=print_progress)
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
