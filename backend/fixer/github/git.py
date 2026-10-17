"""git operations against GitHub. The token is passed through environment variables (GIT_CONFIG_*), so it
never appears in a URL, in .git/config, in the process list's arguments or in logs."""

from __future__ import annotations

import base64
import os
import subprocess
from pathlib import Path

from fixer.github.client import GitHubError

COMMITTER = ["-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null"]


def _env(token: str | None) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_CONFIG")}
    env["GIT_TERMINAL_PROMPT"] = "0"
    if token:
        basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
        env.update(
            {
                "GIT_CONFIG_COUNT": "1",
                "GIT_CONFIG_KEY_0": "http.https://github.com/.extraheader",
                "GIT_CONFIG_VALUE_0": f"AUTHORIZATION: basic {basic}",
            }
        )
    return env


def _run(args: list[str], cwd: Path | None, token: str | None, timeout: int = 600) -> str:
    res = subprocess.run(["git", *args], cwd=cwd, env=_env(token), capture_output=True, text=True, timeout=timeout)
    if res.returncode != 0:
        msg = (res.stderr or res.stdout).strip()
        if token:
            msg = msg.replace(token, "[REDACTED]")
        raise GitHubError(f"git {args[0]} failed: {msg[-500:]}")
    return res.stdout


def clone_url(slug: str, host: str = "https://github.com") -> str:
    return f"{host}/{slug}.git"


def clone(url: str, dest: Path, branch: str, token: str | None, depth: int = 50) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    _run(
        ["clone", "--quiet", "--depth", str(depth), "--single-branch", "--branch", branch, url, str(dest)], None, token
    )


def commit_patch(repo: Path, branch: str, patch: Path, message: str, author: tuple[str, str]) -> str:
    """Create `branch` from HEAD, apply the patch and commit it. Returns the commit sha."""
    name, email = author
    _run(["checkout", "--quiet", "-b", branch], repo, None)
    _run(["apply", "--whitespace=nowarn", "--index", str(patch)], repo, None)
    _run(
        [*COMMITTER, "-c", f"user.name={name}", "-c", f"user.email={email}", "commit", "--quiet", "-m", message],
        repo,
        None,
    )
    return _run(["rev-parse", "HEAD"], repo, None).strip()


def push(repo: Path, url: str, branch: str, token: str | None) -> None:
    _run(["push", "--quiet", url, f"HEAD:refs/heads/{branch}"], repo, token)
