"""GitHub flow, fully offline: a local bare repo plays github.com and a fake transport plays the REST API."""

import shutil
import subprocess
from pathlib import Path

import pytest

from fixer.config import Budget
from fixer.events import EventBus
from fixer.github import git as gh_git
from fixer.github.client import GitHubClient, GitHubError, parse_issue_ref
from fixer.github.workflow import branch_name, prepare
from fixer.llm.router import LLMRouter
from fixer.orchestrator.pipeline import GitHubJob, Job, JobConfig
from tests.fakes import AgentBrain, call, text

CART = Path(__file__).resolve().parents[1] / "evals" / "bugs" / "py_cart"
TOKEN = "ghp_faketoken1234567890abcdef"
REPRO = "tests/test_issue_coupon.py::test_fifteen_percent_coupon"
SCRIPTS = {
    "reproducer": [
        call(
            "create_file",
            path="tests/test_issue_coupon.py",
            content="from cart.pricing import apply_discount\n\n\ndef test_fifteen_percent_coupon():\n"
            "    assert apply_discount(200, 15) == 170.0\n",
        ),
        call("finish", test_id=REPRO, explanation="15% off 200 should be 170"),
    ],
    "fixer": [
        call("edit_file", path="cart/pricing.py", old_text="percent / 10)", new_text="percent / 100)"),
        call("finish", summary="apply_discount divided by 10 instead of 100"),
    ],
    "critic": [text('{"approve": true, "concerns": []}')],
}


def git(*args, cwd=None):
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


@pytest.fixture
def github(tmp_path, monkeypatch):
    """A bare 'acme/shop' repo (+ 'me/shop' for forks) and a fake API that records what it was asked."""
    monkeypatch.setenv("FIXER_HOME", str(tmp_path / "home"))
    work = tmp_path / "seed"
    shutil.copytree(CART, work)
    git("init", "-q", "-b", "main", cwd=work)
    git("add", "-A", cwd=work)
    git("commit", "-q", "-m", "init", cwd=work)
    host = tmp_path / "gh"
    for slug in ("acme/shop", "me/shop"):
        (host / slug).parent.mkdir(parents=True, exist_ok=True)
        git("clone", "-q", "--bare", str(work), str(host / f"{slug}.git"))

    calls: list[tuple[str, str, object]] = []
    state = {"can_push": True}

    def transport(method, url, body, headers):
        path = url.removeprefix("https://api.github.com")
        calls.append((method, path, body))
        assert headers.get("Authorization") == f"Bearer {TOKEN}"
        if path == "/user":
            return 200, {"login": "me", "id": 42, "name": "Me"}
        if path == "/repos/acme/shop":
            return 200, {"default_branch": "main", "private": True, "permissions": {"push": state["can_push"]}}
        if path == "/repos/acme/shop/issues/7":
            return 200, {
                "title": "Coupons give wrong totals",
                "body": (CART / "ISSUE.md").read_text(),
                "state": "open",
                "comments": 1,
                "html_url": "https://github.com/acme/shop/issues/7",
            }
        if path.startswith("/repos/acme/shop/issues/7/comments") and method == "GET":
            return 200, [{"user": {"login": "qa"}, "body": "Also happens at 10%."}]
        if path == "/repos/acme/shop/forks":
            return 202, {"full_name": "me/shop"}
        if path == "/repos/me/shop":
            return 200, {"full_name": "me/shop"}
        if path == "/repos/acme/shop/pulls":
            return 201, {"html_url": "https://github.com/acme/shop/pull/8", "number": 8}
        if path == "/repos/acme/shop/issues/7/comments" and method == "POST":
            return 201, {"id": 1}
        return 404, {"message": "Not Found"}

    return {
        "host": f"file://{host}",
        "bare": host,
        "calls": calls,
        "state": state,
        "client": GitHubClient(TOKEN, transport),
    }


def run_issue(gh, scripts=SCRIPTS, **kw):
    ref = parse_issue_ref("https://github.com/acme/shop/issues/7")
    target = prepare(gh["client"], ref)
    brain = AgentBrain(scripts)
    bus = EventBus()
    router = LLMRouter([brain.provider("p1")], max_requests=30, on_event=lambda type, **d: bus.emit(type, **d))
    job = GitHubJob(target=target, client=gh["client"], token=TOKEN, host=gh["host"], **kw)
    cfg = JobConfig(repo=Path("."), issue=target.issue_text, budget=Budget(max_requests=30), scouts="never", github=job)
    return Job(cfg, router, bus).run(), target


def test_issue_to_pull_request(github):
    result, target = run_issue(github)
    assert result.status == "fixed", result.reason
    assert result.pr_url == "https://github.com/acme/shop/pull/8"
    assert "Also happens at 10%" in target.issue_text  # comments are part of the agents' input

    pull = next(b for m, p, b in github["calls"] if p == "/repos/acme/shop/pulls")
    assert pull["base"] == "main" and pull["head"] == result.branch and pull["draft"] is True
    assert pull["body"].startswith("Fixes #7")
    assert REPRO in pull["body"] and "no new failures" in pull["body"]
    assert "LLM requests: 5 " in pull["body"] and "reproducer (2)" in pull["body"]  # usage is filled in

    # the branch really landed on the remote, with one commit holding the test and the fix
    bare = github["bare"] / "acme/shop.git"
    log = git("log", "--format=%an <%ae>%n%s%n%b", "-1", result.branch, cwd=bare)
    assert "Me <42+me@users.noreply.github.com>" in log and "Fixes #7" in log
    files = git("show", "--name-only", "--format=", result.branch, cwd=bare).split()
    assert sorted(files) == ["cart/pricing.py", "tests/test_issue_coupon.py"]
    # the token never landed on disk
    source = Path(result.job_dir) / "source"
    assert TOKEN not in (source / ".git" / "config").read_text()


def test_without_push_access_pushes_to_a_fork(github):
    github["state"]["can_push"] = False
    result, _ = run_issue(github)
    assert result.status == "fixed", result.reason
    assert any(p == "/repos/acme/shop/forks" for _, p, _ in github["calls"])
    pull = next(b for _, p, b in github["calls"] if p == "/repos/acme/shop/pulls")
    assert pull["head"] == f"me:{result.branch}"
    git("rev-parse", "--verify", result.branch, cwd=github["bare"] / "me/shop.git")


def test_no_pr_when_disabled_and_comment_on_failure(github):
    giving_up = {**SCRIPTS, "reproducer": [call("give_up", reason="can't reproduce")]}
    result, _ = run_issue(github, scripts=giving_up, comment_on_failure=True)
    assert result.status == "gave_up" and result.pr_url is None
    comment = next(b for m, p, b in github["calls"] if m == "POST" and p.endswith("/issues/7/comments"))
    assert "stopped" in comment["body"]
    assert not any(p.endswith("/pulls") for _, p, _ in github["calls"])


def test_issue_refs_and_branch_names():
    assert str(parse_issue_ref("acme/shop#12")) == "acme/shop#12"
    assert parse_issue_ref("https://github.com/acme/shop.git/issues/3").repo == "shop"
    with pytest.raises(GitHubError):
        parse_issue_ref("not an issue")
    name = branch_name(parse_issue_ref("a/b#5"), "Coupons give WRONG totals!!", "j-20261017-abcd")
    assert name == "fixer/issue-5-coupons-give-wrong-totals-abcd"


def test_git_auth_goes_through_env_not_arguments():
    env = gh_git._env(TOKEN)
    assert env["GIT_CONFIG_KEY_0"].startswith("http.https://github.com/")
    assert TOKEN not in env["GIT_CONFIG_VALUE_0"]  # base64-encoded basic auth header
