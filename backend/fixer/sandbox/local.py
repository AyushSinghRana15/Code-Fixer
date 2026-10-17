"""Local sandbox: runs commands in the workspace copy on this machine.

No isolation: the repo's code runs with your user's permissions. Use only on repos you trust;
the Docker sandbox is the safe default once Docker is installed.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import time

from fixer.sandbox.base import CommandResult, Sandbox

# Only these variables reach the repo's code, so API keys and tokens never leak into test runs.
ENV_ALLOWLIST = (
    "PATH",
    "HOME",
    "USER",
    "LOGNAME",
    "SHELL",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "TERM",
    "TMPDIR",
    "JAVA_HOME",
    "UV_CACHE_DIR",
    "UV_PYTHON",
    "PIP_CACHE_DIR",
    "npm_config_cache",
)


def safe_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k in ENV_ALLOWLIST}
    env.update(
        {
            "CI": "1",
            "NO_COLOR": "1",
            "FORCE_COLOR": "0",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONUNBUFFERED": "1",
            "npm_config_audit": "false",
            "npm_config_fund": "false",
        }
    )
    return env


class LocalSandbox(Sandbox):
    kind = "local"

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def exec(self, cmd: str, timeout: int = 600, network: bool = False) -> CommandResult:
        # `network` can't be enforced locally; the Docker sandbox disconnects the network for tests.
        start = time.monotonic()
        proc = subprocess.Popen(
            ["/bin/bash", "-c", cmd],
            cwd=self.ws.root,
            env=safe_env(),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=True,
        )
        try:
            out, _ = proc.communicate(timeout=timeout)
            return CommandResult(proc.returncode, out or "", time.monotonic() - start)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)  # kill the whole process group, not just bash
            out, _ = proc.communicate()
            return CommandResult(124, (out or "") + f"\n[timed out after {timeout}s]", time.monotonic() - start, True)


def has_uv() -> bool:
    return shutil.which("uv") is not None
