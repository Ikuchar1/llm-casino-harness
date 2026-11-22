"""Tests for agent/platform_info.py: hostname, OS string, GPU names and SLURM job id."""

import subprocess

from agent.platform_info import platform_info, query_gpu_names


def fake_run(stdout="", returncode=0, raises=None):
    def run(cmd, **kwargs):
        if raises is not None:
            raise raises
        return subprocess.CompletedProcess(cmd, returncode, stdout=stdout, stderr="")
    return run


def test_gpu_names_from_nvidia_smi():
    assert query_gpu_names(fake_run("NVIDIA L40S\nNVIDIA L40S\n")) == ["NVIDIA L40S", "NVIDIA L40S"]


def test_gpu_names_none_without_nvidia_smi():
    assert query_gpu_names(fake_run(raises=FileNotFoundError("nvidia-smi"))) is None


def test_gpu_names_none_when_nvidia_smi_fails_or_times_out():
    assert query_gpu_names(fake_run("No devices were found", returncode=9)) is None
    assert query_gpu_names(fake_run(raises=subprocess.TimeoutExpired("nvidia-smi", 10))) is None
    assert query_gpu_names(fake_run("\n")) is None


def test_platform_info_fields(monkeypatch):
    monkeypatch.setenv("SLURM_JOB_ID", "123456")
    info = platform_info(run=fake_run("NVIDIA L40S\n"))
    assert set(info) == {"hostname", "platform", "gpus", "slurm_job_id"}
    assert info["hostname"] and info["platform"]
    assert info["gpus"] == ["NVIDIA L40S"]
    assert info["slurm_job_id"] == "123456"


def test_platform_info_outside_slurm_and_without_gpu(monkeypatch):
    monkeypatch.delenv("SLURM_JOB_ID", raising=False)
    info = platform_info(run=fake_run(raises=OSError("nope")))
    assert info["gpus"] is None and info["slurm_job_id"] is None
