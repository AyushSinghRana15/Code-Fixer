"""Docker sandbox: one locked-down container per job, network cut off while tests run.

Uses the docker CLI (works with Docker Desktop, Colima or OrbStack). Not exercised yet on this
machine because Docker isn't installed; run `fixer doctor` after installing it.
"""

from __future__ import annotations

import shlex
import shutil
import subprocess
import time
import uuid

from fixer.sandbox.base import CommandResult, Sandbox


class DockerUnavailable(Exception):
    pass


def docker_available() -> bool:
    if not shutil.which("docker"):
        return False
    return subprocess.run(["docker", "info"], capture_output=True).returncode == 0


class DockerSandbox(Sandbox):
    kind = "docker"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = f"fixer-{uuid.uuid4().hex[:10]}"
        self._connected = True

    def _docker(self, *args: str, timeout: int | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout)

    def start(self) -> None:
        if not docker_available():
            raise DockerUnavailable(
                "Docker isn't running. Install it (e.g. `brew install colima docker && "
                "colima start`) or use --sandbox local."
            )
        res = self._docker(
            "run",
            "-d",
            "--name",
            self.name,
            "-v",
            f"{self.ws.root}:/work",
            "-w",
            "/work",
            "--memory",
            "4g",
            "--cpus",
            "2",
            "--pids-limit",
            "512",
            "--security-opt",
            "no-new-privileges",
            "--cap-drop",
            "ALL",
            "-e",
            "CI=1",
            "-e",
            "NO_COLOR=1",
            "-e",
            "PYTHONDONTWRITEBYTECODE=1",
            self.spec.docker_image,
            "sleep",
            "infinity",
        )
        if res.returncode != 0:
            raise DockerUnavailable(f"couldn't start container: {res.stderr.strip()}")

    def _set_network(self, on: bool) -> None:
        if on == self._connected:
            return
        self._docker("network", "connect" if on else "disconnect", "bridge", self.name)
        self._connected = on

    def exec(self, cmd: str, timeout: int = 600, network: bool = False) -> CommandResult:
        self._set_network(network)
        start = time.monotonic()
        wrapped = f"timeout -k 10 {timeout} bash -c {shlex.quote(cmd)}"
        res = self._docker("exec", "-w", "/work", self.name, "bash", "-c", wrapped, timeout=timeout + 30)
        out = (res.stdout or "") + (res.stderr or "")
        timed_out = res.returncode == 124
        if timed_out:
            out += f"\n[timed out after {timeout}s]"
        return CommandResult(res.returncode, out, time.monotonic() - start, timed_out)

    def stop(self) -> None:
        self._docker("rm", "-f", self.name)
