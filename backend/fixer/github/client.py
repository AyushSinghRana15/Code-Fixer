"""Minimal GitHub REST client (stdlib only). The token is sent only in the Authorization header."""

from __future__ import annotations

import json
import os
import re
import shutil
import ssl
import subprocess
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

API = "https://api.github.com"

# (method, url, json body, headers) -> (status, parsed json) or (status, parsed json, response headers)
Transport = Callable[[str, str, Any, dict[str, str]], tuple]


class GitHubError(Exception):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class IssueRef:
    owner: str
    repo: str
    number: int

    @property
    def slug(self) -> str:
        return f"{self.owner}/{self.repo}"

    def __str__(self) -> str:
        return f"{self.slug}#{self.number}"


_URL = re.compile(r"github\.com/([\w.-]+)/([\w.-]+)/(?:issues|pull)/(\d+)")
_SHORT = re.compile(r"^([\w.-]+)/([\w.-]+)#(\d+)$")


def parse_issue_ref(text: str) -> IssueRef:
    """Accepts https://github.com/owner/repo/issues/12 or owner/repo#12."""
    text = text.strip()
    m = _URL.search(text) or _SHORT.match(text)
    if not m:
        raise GitHubError(f"not a GitHub issue reference: {text!r} (use a URL or owner/repo#12)")
    owner, repo, num = m.groups()
    return IssueRef(owner, repo.removesuffix(".git"), int(num))


def find_token(vault: Any = None) -> str | None:
    """FIXER_GITHUB_TOKEN / GITHUB_TOKEN, then the vault, then the GitHub CLI's login (`gh auth token`)."""
    return token_source(vault)[0]


def token_source(vault: Any = None) -> tuple[str | None, str]:
    """(token, where it came from: env | vault | gh | none)."""
    for name in ("FIXER_GITHUB_TOKEN", "GITHUB_TOKEN", "GH_TOKEN"):
        if os.environ.get(name, "").strip():
            return os.environ[name].strip(), "env"
    if vault is not None:
        stored = vault.get_secret("github")
        if stored:
            return stored, "vault"
    if shutil.which("gh"):
        res = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True)
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout.strip(), "gh"
    return None, "none"


def _ssl_context() -> ssl.SSLContext:
    """Verify TLS with certifi's CA bundle: some Python installs (e.g. python.org builds on macOS) ship
    without system certificates, which makes plain urllib fail on every https request."""
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


_SSL = _ssl_context()


def _urllib_transport(method: str, url: str, body: Any, headers: dict[str, str]) -> tuple[int, Any]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30, context=_SSL) as resp:
            raw = resp.read()
            return resp.status, json.loads(raw) if raw else None, dict(resp.headers)
    except urllib.error.HTTPError as err:
        raw = err.read()
        try:
            payload = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            payload = {"message": raw.decode(errors="replace")[:300]}
        return err.code, payload, dict(err.headers or {})
    except urllib.error.URLError as err:
        raise GitHubError(f"couldn't reach GitHub: {err.reason}") from err


class GitHubClient:
    def __init__(self, token: str | None, transport: Transport | None = None):
        self.token = token
        self._transport = transport or _urllib_transport
        self.last_headers: dict[str, str] = {}

    def _call(self, method: str, path: str, body: Any = None, ok: tuple[int, ...] = (200, 201, 202)) -> Any:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "code-fixer",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if body is not None:
            headers["Content-Type"] = "application/json"
        out = self._transport(method, f"{API}{path}", body, headers)
        status, payload = out[0], out[1]
        self.last_headers = {k.lower(): v for k, v in (out[2] if len(out) > 2 else {}).items()}
        if status not in ok:
            msg = (payload or {}).get("message", "") if isinstance(payload, dict) else str(payload)
            errors = (payload or {}).get("errors") if isinstance(payload, dict) else None
            detail = f" ({errors})" if errors else ""
            hint = {
                401: " Is the token valid?",
                403: " Check the token's scopes (needs `repo`).",
                404: " Not found, or the token can't see this repo.",
            }.get(status, "")
            raise GitHubError(f"GitHub {method} {path} failed: {status} {msg}{detail}.{hint}", status)
        return payload

    # ---- reads ----
    def user(self) -> dict[str, Any]:
        return self._call("GET", "/user")

    def token_info(self) -> tuple[str, list[str]]:
        """(login, OAuth scopes). Fine-grained tokens report no scopes header, so scopes may be empty."""
        login = self.user()["login"]
        scopes = [s.strip() for s in self.last_headers.get("x-oauth-scopes", "").split(",") if s.strip()]
        return login, scopes

    def repo(self, owner: str, repo: str) -> dict[str, Any]:
        return self._call("GET", f"/repos/{owner}/{repo}")

    def issue(self, ref: IssueRef) -> dict[str, Any]:
        data = self._call("GET", f"/repos/{ref.slug}/issues/{ref.number}")
        if data.get("pull_request"):
            raise GitHubError(f"{ref} is a pull request, not an issue")
        return data

    def issue_comments(self, ref: IssueRef, limit: int = 5) -> list[dict[str, Any]]:
        return self._call("GET", f"/repos/{ref.slug}/issues/{ref.number}/comments?per_page={limit}") or []

    # ---- writes ----
    def fork(
        self, owner: str, repo: str, wait_seconds: float = 60, sleep: Callable[[float], None] = time.sleep
    ) -> dict[str, Any]:
        """Create (or reuse) the user's fork and wait until it's ready to receive pushes."""
        fork = self._call("POST", f"/repos/{owner}/{repo}/forks", {"default_branch_only": True})
        full = fork["full_name"]
        waited = 0.0
        while waited < wait_seconds:
            try:
                return self._call("GET", f"/repos/{full}")
            except GitHubError as err:
                if err.status != 404:
                    raise
            sleep(3)
            waited += 3
        raise GitHubError(f"fork {full} wasn't ready after {wait_seconds:.0f}s")

    def create_pull(self, ref: IssueRef, head: str, base: str, title: str, body: str, draft: bool) -> dict[str, Any]:
        return self._call(
            "POST",
            f"/repos/{ref.slug}/pulls",
            {"title": title, "head": head, "base": base, "body": body, "draft": draft},
        )

    def comment(self, ref: IssueRef, body: str) -> dict[str, Any]:
        return self._call("POST", f"/repos/{ref.slug}/issues/{ref.number}/comments", {"body": body})
