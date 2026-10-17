"""GitHub issue → verified fix → pull request."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fixer.github import git
from fixer.github.client import GitHubClient, GitHubError, IssueRef

PROJECT_URL = "https://github.com/AyushSinghRana15/Code-Fixer"
MAX_ISSUE_CHARS = 6000


@dataclass
class GitHubTarget:
    ref: IssueRef
    title: str
    issue_text: str  # what the agents read: title, body and the first comments
    issue_url: str
    default_branch: str
    private: bool
    can_push: bool


def prepare(client: GitHubClient, ref: IssueRef) -> GitHubTarget:
    """Read the repo and the issue. Fails early on closed issues and unreadable repos."""
    repo = client.repo(ref.owner, ref.repo)
    issue = client.issue(ref)
    if issue.get("state") != "open":
        raise GitHubError(f"{ref} is {issue.get('state')}; only open issues are fixed")
    comments = client.issue_comments(ref) if issue.get("comments") else []
    return GitHubTarget(
        ref=ref,
        title=issue.get("title", "").strip(),
        issue_text=issue_text(issue, comments),
        issue_url=issue.get("html_url", f"https://github.com/{ref.slug}/issues/{ref.number}"),
        default_branch=repo.get("default_branch", "main"),
        private=bool(repo.get("private")),
        can_push=bool((repo.get("permissions") or {}).get("push")),
    )


def issue_text(issue: dict[str, Any], comments: list[dict[str, Any]]) -> str:
    parts = [f"# {issue.get('title', '').strip()}", (issue.get("body") or "").strip()]
    for c in comments[:5]:
        body = (c.get("body") or "").strip()
        if body:
            parts.append(f"--- comment by @{(c.get('user') or {}).get('login', '?')}:\n{body}")
    text = "\n\n".join(p for p in parts if p)
    return text[:MAX_ISSUE_CHARS] + ("\n[issue truncated]" if len(text) > MAX_ISSUE_CHARS else "")


def branch_name(ref: IssueRef, title: str, job_id: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40].rstrip("-") or "fix"
    return f"fixer/issue-{ref.number}-{slug}-{job_id[-4:]}"


def _md_escape(text: str) -> str:
    return text.replace("\r", "").strip()


def pr_body(target: GitHubTarget, result: Any) -> str:
    tests = result.tests or {}
    base, final = tests.get("baseline", {}), tests.get("final", {})
    lines = [f"Fixes #{target.ref.number}", ""]
    if result.summary:
        lines += ["### Root cause and fix", "", *[f"> {ln}" for ln in _md_escape(result.summary).splitlines()], ""]
    if result.repro_test:
        lines += [
            "### Reproduction",
            "",
            f"`{result.repro_test}` was written first and **failed on the original code**; it passes with this change.",
            "",
        ]
    if base or final:
        before_fail = len(base.get("failing", []))
        after_fail = len(final.get("failing", []))
        new = final.get("new_failures", [])
        lines += [
            "### Verification",
            "",
            "| | passed | failing |",
            "|---|---|---|",
            f"| Before (baseline) | {base.get('passed', '—')} | {before_fail} |",
            f"| After this change | {final.get('passed', '—')} | {after_fail}"
            + (" (no new failures)" if not new else f" ({len(new)} new)")
            + " |",
            "",
        ]
    review = result.review or {}
    if review:
        if review.get("approve", True) and not review.get("concerns"):
            lines += ["**Review:** approved by the critic agent.", ""]
        else:
            lines += ["**Reviewer concerns:**", *[f"- {c}" for c in review.get("concerns", [])], ""]
    tok = result.tokens or {}
    agents = ", ".join(f"{k} ({v['requests']})" for k, v in (result.agents or {}).items())
    lines += [
        "<details><summary>Agent run</summary>",
        "",
        f"- Job: `{result.job_id}`",
        f"- LLM requests: {result.requests} · tokens: {tok.get('input', 0):,} in / {tok.get('output', 0):,} out "
        f"· {result.seconds:.0f}s",
        f"- Agents (requests): {agents}",
        *([f"- Winning fixer: {result.winner}"] if result.winner else []),
        "",
        "</details>",
        "",
        "---",
        f"🤖 Opened by [Code Fixer]({PROJECT_URL}). The change was reproduced, fixed and verified by an agent; "
        "please review it before merging.",
    ]
    return "\n".join(lines)


def commit_message(target: GitHubTarget, summary: str) -> str:
    title = f"Fix: {target.title}"
    title = title if len(title) <= 72 else title[:69] + "..."
    body = _md_escape(summary)[:1500]
    return f"{title}\n\n{body}\n\nFixes #{target.ref.number}".strip()


def open_pull_request(
    client: GitHubClient,
    target: GitHubTarget,
    source: Path,
    patch: Path,
    result: Any,
    token: str | None,
    draft: bool = True,
    host: str = "https://github.com",
) -> dict[str, str]:
    """Commit the verified patch on a new branch of the clean clone, push it (to a fork when the user can't push
    to the repo), and open the PR. Returns {"url", "branch", "head"}."""
    me = client.user()
    login = me["login"]
    email = me.get("email") or f"{me.get('id', 0)}+{login}@users.noreply.github.com"
    branch = branch_name(target.ref, target.title, result.job_id)
    git.commit_patch(source, branch, patch, commit_message(target, result.summary), (me.get("name") or login, email))

    if target.can_push:
        push_slug, head = target.ref.slug, branch
    else:
        fork = client.fork(target.ref.owner, target.ref.repo)
        push_slug, head = fork["full_name"], f"{login}:{branch}"
    git.push(source, git.clone_url(push_slug, host), branch, token)

    title = f"Fix: {target.title}"
    pr = client.create_pull(target.ref, head, target.default_branch, title[:250], pr_body(target, result), draft)
    return {"url": pr["html_url"], "branch": branch, "head": head}


def failure_comment(target: GitHubTarget, result: Any) -> str:
    lines = [f"Code Fixer tried to fix this issue but stopped: **{result.reason or result.status}**", ""]
    if result.repro_test:
        lines.append(f"It did reproduce the bug with a failing test: `{result.repro_test}`.")
    lines += ["", f"<sub>🤖 [Code Fixer]({PROJECT_URL}) · job `{result.job_id}` · {result.requests} LLM requests</sub>"]
    return "\n".join(lines)
