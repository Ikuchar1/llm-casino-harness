"""Where a run happened: hostname, OS string, GPU names and SLURM job id.

Recorded in metadata.json because temperature-0 replies are only reproducible on the
same software + hardware stack (Mac and HCC runs diverge). Never raises: missing
information is recorded as None.
"""

import os
import platform
import socket
import subprocess
from typing import Any, Callable, Optional

NVIDIA_SMI = ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"]


def query_gpu_names(run: Callable[..., Any] = subprocess.run) -> Optional[list[str]]:
    """GPU names from nvidia-smi, one per GPU; None when nvidia-smi is missing or fails."""
    try:
        result = run(NVIDIA_SMI, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    names = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    return names or None


def platform_info(run: Callable[..., Any] = subprocess.run) -> dict[str, Any]:
    return {
        "hostname": socket.gethostname(),
        "platform": platform.platform(),
        "gpus": query_gpu_names(run),
        "slurm_job_id": os.environ.get("SLURM_JOB_ID"),
    }
