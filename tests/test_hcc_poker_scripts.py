"""Tests for the HCC poker submission scripts (hcc/submit_poker.sh, hcc/poker_run.sbatch), run with bash."""

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SUBMIT = REPO_ROOT / "hcc" / "submit_poker.sh"
RUN = REPO_ROOT / "hcc" / "poker_run.sbatch"

BOTS = ("calling_station", "maniac", "rock", "control")


def dry_run(*args):
    result = subprocess.run(["bash", str(SUBMIT), "--dry-run", *args], capture_output=True, text=True, cwd=REPO_ROOT)
    sbatch_lines = [line for line in result.stderr.splitlines() if line.startswith("sbatch ")]
    return result, sbatch_lines


def run_jobs(sbatch_lines):
    """(setup, bot) for each poker_run.sbatch command, in order."""
    jobs = []
    for line in sbatch_lines:
        words = line.split()
        if "hcc/poker_run.sbatch" in words:
            at = words.index("hcc/poker_run.sbatch")
            jobs.append((words[at + 1], words[at + 2]))
    return jobs


def test_a_dry_run_lists_all_eight_matches_after_one_model_pull():
    result, lines = dry_run()

    assert result.returncode == 0, result.stderr
    assert lines[0].split()[-2:] == ["hcc/pull_model.sbatch", "qwen2.5:7b"]
    assert run_jobs(lines) == [(setup, bot) for setup in ("plain", "memory") for bot in BOTS]
    for line in lines[1:]:
        assert "--dependency=afterok:DRYRUN" in line
        assert "--job-name=pk_" in line


def test_memory_matches_get_a_longer_time_limit_than_plain_ones():
    _, lines = dry_run()

    run_lines = [line for line in lines if "hcc/poker_run.sbatch" in line]
    assert all("--time=08:00:00" in line for line in run_lines if "poker_run.sbatch plain" in line)
    assert all("--time=12:00:00" in line for line in run_lines if "poker_run.sbatch memory" in line)


def test_a_filter_submits_only_the_matching_setups_and_bots():
    assert run_jobs(dry_run("memory")[1]) == [("memory", bot) for bot in BOTS]
    assert run_jobs(dry_run("rock")[1]) == [("plain", "rock"), ("memory", "rock")]
    assert run_jobs(dry_run("rock", "memory")[1]) == [("memory", "rock")]


def test_an_unknown_filter_word_submits_nothing():
    result, lines = dry_run("rocks")

    assert result.returncode == 2
    assert lines == []
    assert "unknown argument rocks" in result.stderr


def run_sbatch_script(*args, env=None):
    """Runs hcc/poker_run.sbatch outside SLURM; only its argument checks can finish there."""
    return subprocess.run(["bash", str(RUN), *args], capture_output=True, text=True, cwd=REPO_ROOT,
                          env={"PATH": "/usr/bin:/bin", **(env or {})})


def test_a_match_job_without_a_known_setup_and_bot_stops_before_starting_ollama():
    for args, env in [((), None), (("plain",), None), (("solo", "rock"), None), (("plain", "shark"), None),
                      ((), {"SETUP": "memory"})]:
        result = run_sbatch_script(*args, env=env)

        assert result.returncode == 2, (args, env, result.stderr)
        assert "usage: sbatch hcc/poker_run.sbatch" in result.stderr
        assert "ollama" not in result.stdout


def fake_cluster(tmp_path, pokerkit_installed=True):
    """A submit dir, stub cluster commands and a stub env python that logs its run_poker.py call."""
    submit_dir = tmp_path / "repo"
    submit_dir.mkdir()
    (submit_dir / "hcc").symlink_to(REPO_ROOT / "hcc")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stubs = {
        "module": "exit 0",
        "nvidia-smi": "exit 0",
        "curl": "exit 0",
        "ollama": 'if [ "$1" = serve ]; then exec sleep 30; fi; exit 0',
    }
    py_dir = tmp_path / "nrdstor" / "envs" / "bj" / "bin"
    py_dir.mkdir(parents=True)
    calls = tmp_path / "python_calls.txt"
    pokerkit = "exit 0" if pokerkit_installed else "exit 1"
    stubs_at = {bin_dir / name: body for name, body in stubs.items()}
    stubs_at[py_dir / "python"] = (
        f'if [ "$1" = --version ]; then echo Python 3.11; exit 0; fi\n'
        f'if [ "$1" = -c ]; then case "$2" in *"import pokerkit"*) {pokerkit} ;; esac; exit 0; fi\n'
        f'echo "$*" >> {calls}'
    )
    for path, body in stubs_at.items():
        path.write_text(f"#!/bin/bash\n{body}\n")
        path.chmod(0o755)
    env = {"PATH": f"{bin_dir}:/usr/bin:/bin", "SLURM_SUBMIT_DIR": str(submit_dir), "SLURM_JOB_ID": "4242",
           "NRDSTOR": str(tmp_path / "nrdstor")}
    return env, calls


def test_a_match_job_runs_the_model_for_500_pairs_at_seed_2026_into_its_setup_and_bot_folder(tmp_path):
    env, calls = fake_cluster(tmp_path)

    result = run_sbatch_script("memory", "rock", env=env)

    assert result.returncode == 0, result.stderr
    assert calls.read_text().split() == [
        "scripts/run_poker.py", "--model", "qwen2.5:7b", "--bot", "rock", "--pairs", "500", "--seed", "2026",
        "--setup", "memory", "--out", "results/poker_runs/qwen2.5-7b/memory/rock",
    ]


def test_a_match_job_takes_setup_and_bot_from_the_environment_too(tmp_path):
    env, calls = fake_cluster(tmp_path)

    result = run_sbatch_script(env={**env, "SETUP": "plain", "BOT": "calling_station"})

    assert result.returncode == 0, result.stderr
    assert "--out results/poker_runs/qwen2.5-7b/plain/calling_station" in calls.read_text()


def test_a_match_job_stops_with_the_pip_command_when_pokerkit_is_missing(tmp_path):
    env, calls = fake_cluster(tmp_path, pokerkit_installed=False)

    result = run_sbatch_script("plain", "maniac", env=env)

    assert result.returncode == 1
    assert "pokerkit is not installed" in result.stderr
    assert f"{tmp_path}/nrdstor/envs/bj/bin/python -m pip install -r requirements.txt" in result.stderr
    assert not calls.exists()
