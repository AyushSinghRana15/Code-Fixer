"""The orchestrator (Plan.md §4 and §4b). Plain code that runs the pipeline and spawns agents:

    intake → env → baseline → context (code-built pack; LLM scouts in parallel only if it's weak)
    → reproduce → localize → fix (staggered race of fixers in separate sandboxes; first verified fix wins)
    → verify → review → deliver

Agents never share a conversation. Each gets a small, task-specific context: the orchestrator hands them a
context pack (and scout briefs when needed), so the expensive agents start informed instead of re-reading
the repo. Parallel work is added only where it pays for itself (see Plan.md §4b).
Loops back to Fix when Verify or Review fails.
"""

from __future__ import annotations

import json
import re
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from fixer.agent import prompts
from fixer.agent.loop import run_agent
from fixer.config import Budget, fixer_home
from fixer.events import EventBus
from fixer.github import git as gh_git
from fixer.github.client import GitHubClient, GitHubError
from fixer.github.workflow import GitHubTarget, failure_comment, open_pull_request
from fixer.guards.tamper import check_diff
from fixer.llm.providers import ROLE_PREFERENCE
from fixer.llm.router import LLMRouter, NoProviderAvailable, RequestBudgetExceeded
from fixer.orchestrator.context import ContextPack, build_pack
from fixer.orchestrator.localize import rank
from fixer.sandbox.base import Sandbox
from fixer.sandbox.detect import EnvSpec, UnsupportedRepo, detect
from fixer.sandbox.local import LocalSandbox, has_uv
from fixer.sandbox.results import TestReport
from fixer.sandbox.workspace import Workspace
from fixer.tools.toolbox import FINISH_FIX, FINISH_REPRODUCE, FINISH_SCOUT, Policy, Toolbox

ALL_PHASES = ["intake", "env", "baseline", "context", "reproduce", "localize", "fix", "verify", "review", "deliver"]
BROKEN_TEST = re.compile(
    r"SyntaxError|IndentationError|ModuleNotFoundError|fixture '\w+' not found|"
    r"NameError: name '\w+' is not defined|Cannot find module|cannot find symbol"
)

# Each scout answers one question in its own throwaway context and returns a short brief.
SCOUTS = [
    (
        "scout-tests",
        "How are tests in this repository written and run? Find the test file(s) closest to the code in the "
        "issue. Report the test file paths, how they import the code under test, any fixtures or helpers, and a "
        "minimal test skeleton in the project's style that would exercise the behaviour from the issue.",
    ),
    (
        "scout-code",
        "Find the code responsible for the behaviour in the issue. Report file paths, function or class names "
        "with line numbers, the most relevant code quoted exactly (40 lines at most), and your best guess at the "
        "root cause. Don't write a fix.",
    ),
]


@dataclass
class GitHubJob:
    """Set when the job comes from a GitHub issue: clone instead of copy, open a PR at the end."""

    target: GitHubTarget
    client: GitHubClient
    token: str | None
    open_pr: bool = True
    draft: bool = True
    comment_on_failure: bool = False
    host: str = "https://github.com"  # tests point this at a local bare repo


class Stop(Exception):
    """Ends the job (or one agent) early with a status and a human-readable reason."""

    def __init__(self, status: str, reason: str):
        super().__init__(reason)
        self.status = status
        self.reason = reason


@dataclass
class JobConfig:
    repo: Path
    issue: str
    sandbox: str = "local"  # local | docker
    budget: Budget = field(default_factory=Budget)
    apply: bool = False  # apply the patch to the user's repo when done
    context_pack: bool = True  # build the code-only context pack (turn off to benchmark the classic agent)
    scouts: str = "auto"  # LLM scouts: auto (only when the context pack is weak) | always | never
    candidates: int = 1  # fixer agents (>1 = race in separate sandboxes)
    stagger: int = 5  # backup fixers start after the first has used this many turns (0 = all at once)
    github: GitHubJob | None = None
    job_id: str = field(default_factory=lambda: f"j-{datetime.now():%Y%m%d-%H%M%S}-{uuid4().hex[:4]}")


@dataclass
class JobResult:
    job_id: str
    status: str  # fixed | needs_review | gave_up | paused | failed
    reason: str = ""
    phases: dict[str, str] = field(default_factory=dict)
    repro_test: str | None = None
    summary: str = ""
    diff: str = ""
    patch_path: str | None = None
    job_dir: str = ""
    review: dict[str, Any] = field(default_factory=dict)
    tests: dict[str, Any] = field(default_factory=dict)
    candidates: dict[str, str] = field(default_factory=dict)  # fixer label -> outcome
    winner: str | None = None
    requests: int = 0
    tokens: dict[str, int] = field(default_factory=dict)
    agents: dict[str, dict[str, int]] = field(default_factory=dict)  # per-agent requests and tokens
    seconds: float = 0.0
    applied: bool = False
    pr_url: str | None = None
    branch: str | None = None


class Job:
    def __init__(self, cfg: JobConfig, router: LLMRouter, bus: EventBus):
        self.cfg = cfg
        self.router = router
        self.bus = bus
        self.job_dir = fixer_home() / "runs" / cfg.job_id
        self.phases = list(ALL_PHASES)
        self.result = JobResult(
            cfg.job_id, "failed", job_dir=str(self.job_dir), phases={p: "pending" for p in self.phases}
        )
        self.started = time.monotonic()
        self.ws: Workspace | None = None
        self.spec: EnvSpec | None = None
        self.sandbox: Sandbox | None = None
        self.baseline: TestReport | None = None
        self.repro: str | None = None
        self.repro_report: TestReport | None = None
        self.fix_summary = ""
        self.hints: list[str] = []
        self.briefs: dict[str, str] = {}

    # ---- helpers ----
    def emit(self, type: str, **data: Any) -> None:
        self.bus.emit(type, job=self.cfg.job_id, **data)

    def emitter(self, agent: str):
        return lambda type, **data: self.emit(type, agent=agent, **data)

    def _phase(self, name: str, state: str, **data: Any) -> None:
        self.result.phases[name] = state
        self.emit("phase." + ("started" if state == "running" else "finished"), phase=name, state=state, **data)

    def _time_left(self) -> str | None:
        if time.monotonic() - self.started > self.cfg.budget.max_seconds:
            return f"time budget reached ({self.cfg.budget.max_seconds // 60} min)"
        return None

    def _make_sandbox(self, ws: Workspace) -> Sandbox:
        assert self.spec
        if self.cfg.sandbox == "docker":
            from fixer.sandbox.docker import DockerSandbox

            return DockerSandbox(ws, self.spec)
        return LocalSandbox(ws, self.spec)

    def _provider_order(self, offset: int = 0, base: tuple[str, ...] = ()) -> list[str]:
        """Configured providers, rotated so parallel agents start on different ones (spreads rate limits)."""
        ids = [p.spec.id for p in self.router.providers]
        ordered = [b for b in base if b in ids] + [i for i in ids if i not in base]
        k = offset % len(ordered) if ordered else 0
        return ordered[k:] + ordered[:k]

    # ---- run ----
    def run(self) -> JobResult:
        self.job_dir.mkdir(parents=True, exist_ok=True)
        current = "intake"
        try:
            for current in self.phases:
                self._phase(current, "running")
                detail = getattr(self, f"_{current}")() or {}
                self._phase(current, "done", **detail)
        except Stop as stop:
            self.result.status, self.result.reason = stop.status, stop.reason
            self._phase(current, "failed", reason=stop.reason)
        except RequestBudgetExceeded as err:
            self.result.status, self.result.reason = "gave_up", str(err)
            self._phase(current, "failed", reason=str(err))
        except NoProviderAvailable as err:
            self.result.status = "paused"
            self.result.reason = f"no LLM provider available: {err}"
            self._phase(current, "failed", reason=self.result.reason)
        finally:
            if self.sandbox:
                self.sandbox.stop()
            self._snapshot_usage()
            if self.ws and not self.result.diff:
                self.result.diff = self.ws.diff()
            self._report_failure()
            (self.job_dir / "result.json").write_text(json.dumps(asdict(self.result), indent=2, default=str))
            self.emit("job.finished", status=self.result.status, reason=self.result.reason)
        return self.result

    # ---- deterministic phases ----
    def _intake(self) -> dict[str, Any]:
        if not self.cfg.issue.strip():
            raise Stop("failed", "the issue text is empty")
        return {"chars": len(self.cfg.issue)}

    def _env(self) -> dict[str, Any]:
        gh = self.cfg.github
        if gh:
            source = self.job_dir / "source"
            gh_git.clone(gh_git.clone_url(gh.target.ref.slug, gh.host), source, gh.target.default_branch, gh.token)
            self.cfg.repo = source  # the clean clone; the PR is built from it at the end
            self.emit("github.cloned", repo=gh.target.ref.slug, branch=gh.target.default_branch)
        self.ws = Workspace.create(self.cfg.repo, self.job_dir / "repo")
        try:
            self.spec = detect(self.ws.root, has_uv=has_uv() and self.cfg.sandbox == "local")
        except UnsupportedRepo as err:
            raise Stop("failed", str(err)) from err
        self.sandbox = self._make_sandbox(self.ws)
        self.sandbox.start()
        res = self.sandbox.setup()
        (self.job_dir / "setup.log").write_text(res.output)
        if res.exit_code != 0:
            raise Stop(
                "failed", f"installing dependencies failed (see {self.job_dir / 'setup.log'}):\n" + res.output[-1500:]
            )
        return {
            "language": self.spec.language,
            "framework": self.spec.framework,
            "sandbox": self.sandbox.kind,
            "seconds": round(res.seconds, 1),
        }

    def _baseline(self) -> dict[str, Any]:
        assert self.sandbox
        self.baseline = self.sandbox.run_tests()
        b = self.baseline
        if b.timed_out:
            raise Stop("failed", "the test suite timed out before any change was made")
        if not b.structured and b.exit_code != 0:
            self.emit("note", text="couldn't read structured results; comparing by exit code only")
        self.result.tests["baseline"] = {"passed": b.passed, "failing": sorted(b.failing_ids)}
        return {"passed": b.passed, "failing": len(b.failing_ids)}

    # ---- context: code-built pack first, LLM scouts (parallel, read-only, cheap model) only if needed ----
    def _context(self) -> dict[str, Any]:
        assert self.ws and self.spec
        files = rank(self.ws, self.spec, self.cfg.issue, "", None, with_reasons=False)
        pack = (
            build_pack(self.ws, self.spec, self.cfg.issue, files)
            if self.cfg.context_pack
            else ContextPack("", False, 0)
        )
        if pack.text:
            self.briefs["context-pack"] = pack.text
        mode = self.cfg.scouts
        if mode == "never" or (mode == "auto" and pack.confident):
            why = "the pack found the code named in the issue" if pack.confident else "disabled"
            return {"pack": f"{len(pack.text)} chars, {pack.snippets} snippets", "scouts": f"skipped ({why})"}
        detail = self._scouts(rank(self.ws, self.spec, self.cfg.issue, "", None))
        return {"pack": f"{len(pack.text)} chars", **detail}

    def _scouts(self, pre_hints: list[str]) -> dict[str, Any]:
        assert self.ws and self.spec
        scout_pref = ROLE_PREFERENCE.get("scout", ())
        with ThreadPoolExecutor(max_workers=len(SCOUTS)) as pool:
            futures = {
                label: pool.submit(self._run_scout, label, question, pre_hints, self._provider_order(i, scout_pref))
                for i, (label, question) in enumerate(SCOUTS)
            }
            for label, fut in futures.items():
                try:
                    self.briefs[label] = fut.result()
                except RequestBudgetExceeded:
                    raise
                except Exception as err:  # noqa: BLE001 - a failed scout only costs us its brief
                    self.emit("agent.failed", agent=label, reason=str(err)[:200])
                    self.briefs[label] = ""
        return {"scouts": {k: f"{len(v)} chars" if v else "none" for k, v in self.briefs.items() if k in dict(SCOUTS)}}

    def _run_scout(self, label: str, question: str, hints: list[str], prefer: list[str]) -> str:
        assert self.ws and self.spec and self.sandbox
        toolbox = Toolbox(
            self.ws, self.sandbox, Policy("scout", lambda rel, exists: "Scouts are read-only."), self.emitter(label)
        )
        tools = toolbox.specs(["read_file", "list_dir", "search"], FINISH_SCOUT)
        brief: dict[str, str] = {}

        def validate(args: dict[str, Any]) -> str | None:
            text = str(args.get("brief", "")).strip()
            if len(text) < 40:
                return "The brief is too short. Include file paths, line numbers and the key code."
            brief["text"] = text[:2500]
            return None

        out = run_agent(
            router=self.router,
            toolbox=toolbox,
            tools=tools,
            system=prompts.SCOUT_SYSTEM.format(language=self.spec.language, framework=self.spec.framework),
            task=prompts.scout_task(self.cfg.issue, question, hints),
            max_iterations=self.cfg.budget.scout_iterations,
            validate_finish=validate,
            check_budget=self._time_left,
            emit=self.emitter(label),
            role="scout",
            agent=label,
            prefer=prefer,
        )
        return brief.get("text", "") if out.status == "finished" else ""

    # ---- reproducer ----
    def _reproduce(self) -> dict[str, Any]:
        assert self.ws and self.spec and self.sandbox
        spec = self.spec

        def can_write(rel: str, exists: bool) -> str | None:
            if not spec.is_test_path(rel):
                return (
                    "While reproducing you may only create or edit test files. Don't fix the bug yet; "
                    "write a failing test first."
                )
            return None

        toolbox = Toolbox(self.ws, self.sandbox, Policy("reproduce", can_write), self.emitter("reproducer"))
        tools = toolbox.specs(
            ["read_file", "list_dir", "search", "create_file", "edit_file", "run_tests", "give_up"], FINISH_REPRODUCE
        )

        def validate(args: dict[str, Any]) -> str | None:
            test_id = str(args.get("test_id", "")).strip()
            if not test_id:
                return "test_id is required."
            report = self.sandbox.run_tests(test_id)
            if report.ok:
                return "That test PASSES, so it doesn't reproduce the bug. Make it check the buggy behaviour."
            if report.total == 0 and not report.failures:
                return f"No test ran for '{test_id}'. Use {spec.selector_hint}."
            text = "\n".join(f"{f.message}\n{f.detail}" for f in report.failures)
            if BROKEN_TEST.search(text) or any(f.id in ("(collection)", "(run)") for f in report.failures):
                return (
                    "The test breaks before it can check the bug (import, syntax or setup error). Fix the "
                    "test itself so it fails on the buggy behaviour:\n" + report.summary(max_failures=2)
                )
            self.repro, self.repro_report = test_id, report
            return None

        tests = sorted(f for f in self.ws.baseline_files() if spec.is_test_path(f))[:8]
        layout = (
            f"{spec.language} project, {spec.framework}; run one test with {spec.selector_hint}. "
            f"Existing test files: {', '.join(tests) or 'none'}"
        )
        out = run_agent(
            router=self.router,
            toolbox=toolbox,
            tools=tools,
            system=prompts.REPRODUCE_SYSTEM.format(
                language=spec.language, framework=spec.framework, selector_hint=spec.selector_hint
            ),
            task=prompts.reproduce_task(self.cfg.issue, layout, self.briefs),
            max_iterations=self.cfg.budget.reproduce_iterations,
            validate_finish=validate,
            check_budget=self._time_left,
            emit=self.emitter("reproducer"),
            agent="reproducer",
        )
        if out.status != "finished":
            raise Stop("gave_up", f"couldn't reproduce the bug: {out.reason or out.status}")
        self.result.repro_test = self.repro
        return {"test": self.repro, "explanation": str(out.args.get("explanation", ""))[:300]}

    def _localize(self) -> dict[str, Any]:
        assert self.ws and self.spec and self.repro_report
        failure = "\n".join(f"{f.message}\n{f.detail}" for f in self.repro_report.failures)
        repro_file = self.repro.split("::")[0] if self.repro and "::" in self.repro else self.repro
        self.hints = rank(self.ws, self.spec, self.cfg.issue, failure, repro_file)
        return {"candidates": self.hints}

    # ---- fixers ----
    def _fix(self) -> dict[str, Any]:
        assert self.ws and self.sandbox
        if self.cfg.candidates <= 1:
            self.fix_summary = self._fix_in(self.ws, self.sandbox, "fixer", None)
            return {"summary": self.fix_summary[:300]}
        return self._race()

    def _fix_in(
        self,
        ws: Workspace,
        sandbox: Sandbox,
        label: str,
        prefer: list[str] | None,
        feedback: str = "",
        cancel: threading.Event | None = None,
        on_turn: Any = None,
        on_progress: Any = None,
    ) -> str:
        """Run one fixer agent in the given workspace until the repro test passes. Returns its summary."""
        assert self.spec and self.repro and self.repro_report
        spec = self.spec
        emit = self.emitter(label)

        def can_write(rel: str, exists: bool) -> str | None:
            if spec.is_test_path(rel):
                return "Test files are read-only while fixing. Change the source code, not the tests."
            return None

        toolbox = Toolbox(ws, sandbox, Policy("fix", can_write), emit)
        tools = toolbox.specs(
            ["read_file", "list_dir", "search", "edit_file", "create_file", "run_tests", "git_diff", "give_up"],
            FINISH_FIX,
        )
        stuck_warnings = 0
        summary: dict[str, str] = {}

        def on_report() -> str | None:
            nonlocal stuck_warnings
            if on_progress and toolbox.reports and toolbox.reports[-1].ok:
                on_progress()
            sigs = [r.signature() for r in toolbox.reports]
            n = self.cfg.budget.stuck_repeats
            if len(sigs) >= n and len(set(sigs[-n:])) == 1 and sigs[-1] != "ok":
                stuck_warnings += 1
                toolbox.reports.clear()
                if stuck_warnings >= 2:
                    raise Stop("gave_up", f"stuck: the same test failure repeated {n} times, twice")
                emit("agent.stuck", repeats=n)
                return (
                    f"You've hit the same failure {n} times in a row. Step back: re-read the failure "
                    f"output, reconsider the root cause, and look at other candidate files: "
                    + "; ".join(self.hints[:4])
                )
            return None

        def validate(args: dict[str, Any]) -> str | None:
            report = sandbox.run_tests(self.repro)
            if not report.ok:
                return "The reproduction test still fails:\n" + report.summary(max_failures=2)
            summary["text"] = str(args.get("summary", ""))
            return None

        def check_budget() -> str | None:
            if on_turn:
                on_turn()
            if cancel is not None and cancel.is_set():
                return "another fixer already produced a verified fix"
            return self._time_left()

        task = prompts.fix_task(
            self.cfg.issue,
            self.repro,
            self.repro_report.summary(max_failures=2),
            self.hints,
            "\n\n".join(v for k, v in self.briefs.items() if k != "scout-tests" and v),
        )
        if feedback:
            task += f"\n\nYour previous change was sent back:\n{feedback}\n\nCurrent diff:\n{ws.diff()[:6000]}"
        out = run_agent(
            router=self.router,
            toolbox=toolbox,
            tools=tools,
            system=prompts.FIX_SYSTEM.format(
                language=spec.language, framework=spec.framework, selector_hint=spec.selector_hint
            ),
            task=task,
            max_iterations=self.cfg.budget.fix_iterations,
            validate_finish=validate,
            on_report=on_report,
            check_budget=check_budget,
            emit=emit,
            agent=label,
            prefer=prefer,
        )
        if out.status != "finished":
            status = "cancelled" if cancel is not None and cancel.is_set() else "gave_up"
            raise Stop(status, f"couldn't fix the bug: {out.reason or out.status}")
        return summary.get("text", "")

    def _new_failures(self, report: TestReport) -> list[str]:
        assert self.baseline
        new = sorted(report.failing_ids - self.baseline.failing_ids)
        if not report.structured and report.exit_code != 0 and self.baseline.exit_code == 0:
            new = ["(suite)"]
        return new

    def _race(self) -> dict[str, Any]:
        """A staggered race. fixer-a starts at once; backups start (each in its own repo copy and sandbox, on a
        different provider first) only if fixer-a hasn't produced a verified fix within `stagger` turns or
        fails. The first fix that passes the full suite wins and the others are told to stop. Easy bugs pay
        for one fixer; hard ones get several in parallel."""
        assert self.ws
        n = self.cfg.candidates
        done = threading.Event()
        backup = threading.Event()  # releases the backup fixers
        if self.cfg.stagger <= 0:
            backup.set()
        lock = threading.Lock()
        winner: dict[str, Any] = {}

        def candidate(k: int) -> tuple[str, str]:
            label = f"fixer-{chr(ord('a') + k)}"
            if k > 0:
                backup.wait()
                if done.is_set():
                    return label, "not needed (fixer-a won before the backup started)"
                self.emit("candidate.started", agent=label, reason="backup: fixer-a hasn't finished yet")
            turns = 0
            progressing = threading.Event()  # fixer-a has the repro test passing: give it time to finish

            def on_turn() -> None:
                nonlocal turns
                turns += 1
                if k == 0 and turns > self.cfg.stagger > 0 and not progressing.is_set():
                    backup.set()

            ws = Workspace.create(self.ws.root, self.job_dir / f"candidate-{chr(ord('a') + k)}")
            sandbox = self._make_sandbox(ws)
            try:
                sandbox.start()
                if sandbox.setup().exit_code != 0:
                    return label, "setup failed"
                summary = self._fix_in(
                    ws,
                    sandbox,
                    label,
                    self._provider_order(k),
                    cancel=done,
                    on_turn=on_turn,
                    on_progress=progressing.set,
                )
                rounds = self.cfg.budget.verify_rounds
                while True:  # verify inside the candidate's own sandbox
                    if done.is_set():
                        return label, "cancelled (another fixer won)"
                    new = self._new_failures(sandbox.run_tests())
                    if not new:
                        break
                    if rounds <= 0:
                        return label, "breaks other tests: " + ", ".join(new[:3])
                    rounds -= 1
                    self.emit("loop.back", agent=label, to="fix", reason=f"{len(new)} new test failure(s)")
                    summary = self._fix_in(
                        ws,
                        sandbox,
                        label,
                        self._provider_order(k),
                        cancel=done,
                        feedback="These tests passed before your change and fail now:\n" + "\n".join(new[:10]),
                    )
                with lock:
                    if done.is_set():
                        return label, "verified, but another fixer won first"
                    done.set()
                    winner.update(label=label, ws=ws, summary=summary)
                self.emit("candidate.won", agent=label)
                return label, "won"
            except Stop as stop:
                return label, f"{stop.status}: {stop.reason}"
            except (RequestBudgetExceeded, NoProviderAvailable) as err:
                return label, str(err)
            finally:
                sandbox.stop()
                if k == 0:
                    backup.set()  # fixer-a finished either way: start backups if it failed, release them if it won

        with ThreadPoolExecutor(max_workers=n) as pool:
            outcomes = dict(pool.map(candidate, range(n)))
        self.result.candidates = outcomes
        if not winner:
            raise Stop("gave_up", "no fixer succeeded: " + "; ".join(f"{k}: {v}" for k, v in outcomes.items()))

        patch = self.job_dir / "winner.patch"
        patch.write_text(winner["ws"].diff())
        subprocess.run(["git", "apply", "--whitespace=nowarn", str(patch)], cwd=self.ws.root, check=True)
        self.fix_summary = winner["summary"]
        self.result.winner = winner["label"]
        return {"winner": winner["label"], "outcomes": outcomes}

    # ---- gates ----
    def _verify(self, rounds_left: int | None = None) -> dict[str, Any]:
        assert self.sandbox and self.ws
        rounds_left = self.cfg.budget.verify_rounds if rounds_left is None else rounds_left
        full = self.sandbox.run_tests()
        new_failures = self._new_failures(full)
        self.result.tests["final"] = {
            "passed": full.passed,
            "failing": sorted(full.failing_ids),
            "new_failures": new_failures,
        }
        if not new_failures:
            return {"passed": full.passed, "new_failures": 0}
        if rounds_left <= 0:
            raise Stop("gave_up", "the fix breaks other tests: " + ", ".join(new_failures[:5]))
        self.emit("loop.back", to="fix", reason=f"{len(new_failures)} new test failure(s)")
        self.fix_summary = self._fix_in(
            self.ws,
            self.sandbox,
            "fixer",
            None,
            feedback="These tests passed before your change and fail now:\n" + full.summary(max_failures=4),
        )
        return self._verify(rounds_left - 1)

    def _review(self, rounds_left: int | None = None) -> dict[str, Any]:
        assert self.ws and self.spec and self.sandbox
        rounds_left = self.cfg.budget.review_rounds if rounds_left is None else rounds_left
        diff = self.ws.diff()
        tamper = check_diff(diff, self.spec, self.ws.baseline_files(), self.ws.changed_files())
        if tamper:
            raise Stop("gave_up", "test-tampering guard: " + "; ".join(tamper[:3]))

        verdict = self._critic(diff)
        self.result.review = verdict
        if verdict.get("approve", True):
            return {"approved": True}
        concerns = "\n".join(f"- {c}" for c in verdict.get("concerns", [])) or "- (no details)"
        if rounds_left <= 0:
            self.result.status = "needs_review"
            return {"approved": False, "concerns": verdict.get("concerns", [])}
        self.emit("loop.back", to="fix", reason="reviewer rejected the change")
        self.fix_summary = self._fix_in(
            self.ws, self.sandbox, "fixer", None, feedback="A reviewer rejected the change:\n" + concerns
        )
        self._verify()
        return self._review(rounds_left - 1)

    def _critic(self, diff: str) -> dict[str, Any]:
        try:
            res = self.router.chat(
                [
                    {"role": "system", "content": prompts.CRITIC_SYSTEM},
                    {
                        "role": "user",
                        "content": prompts.critic_task(self.cfg.issue, self.repro or "", diff, self.fix_summary),
                    },
                ],
                role="critic",
                max_tokens=800,
                temperature=0.0,
                agent="critic",
            )
        except RequestBudgetExceeded:
            return {"approve": True, "concerns": [], "note": "skipped: request budget reached"}
        text = res.message.content or ""
        match = re.search(r"\{.*\}", text, re.DOTALL)
        try:
            verdict = json.loads(match.group(0)) if match else {}
        except json.JSONDecodeError:
            verdict = {}
        if "approve" not in verdict:
            return {"approve": True, "concerns": [], "note": "reviewer reply was unreadable; not blocking"}
        verdict["approve"] = bool(verdict["approve"])
        verdict["concerns"] = [str(c) for c in verdict.get("concerns", [])][:6]
        self.emit("review.verdict", agent="critic", approve=verdict["approve"], concerns=verdict["concerns"])
        return verdict

    def _snapshot_usage(self) -> None:
        usage = self.router.summary()
        self.result.requests = usage["requests"]
        self.result.tokens = usage["tokens"]
        self.result.agents = usage["agents"]
        self.result.seconds = round(time.monotonic() - self.started, 1)

    def _report_failure(self) -> None:
        gh = self.cfg.github
        if not gh or not gh.comment_on_failure or self.result.status not in ("gave_up", "failed"):
            return
        try:
            gh.client.comment(gh.target.ref, failure_comment(gh.target, self.result))
            self.emit("github.commented", issue=str(gh.target.ref))
        except GitHubError as err:
            self.emit("note", text=f"couldn't comment on the issue: {err}")

    def _deliver(self) -> dict[str, Any]:
        assert self.ws
        diff = self.ws.diff()
        self.result.diff = diff
        self.result.summary = self.fix_summary
        patch = self.job_dir / "fix.patch"
        patch.write_text(diff)
        self.result.patch_path = str(patch)
        if self.result.status != "needs_review":
            self.result.status = "fixed"
        gh = self.cfg.github
        if gh and gh.open_pr:
            self._snapshot_usage()  # the PR body reports requests, tokens and per-agent usage
            try:
                pr = open_pull_request(
                    gh.client, gh.target, self.cfg.repo, patch, self.result, gh.token, draft=gh.draft, host=gh.host
                )
            except GitHubError as err:
                self.result.reason = f"fix verified, but opening the PR failed: {err}"
                self.emit("note", text=self.result.reason)
                return {"patch": str(patch), "pr": "failed"}
            self.result.pr_url, self.result.branch = pr["url"], pr["branch"]
            self.emit("github.pr_opened", url=pr["url"], branch=pr["branch"], draft=gh.draft)
            return {"patch": str(patch), "pr": pr["url"]}
        if self.cfg.apply:
            check = subprocess.run(
                ["git", "apply", "--check", str(patch)], cwd=self.cfg.repo, capture_output=True, text=True
            )
            if check.returncode == 0:
                subprocess.run(["git", "apply", str(patch)], cwd=self.cfg.repo, check=True)
                self.result.applied = True
            else:
                self.emit("note", text="patch doesn't apply cleanly to your repo: " + check.stderr.strip()[:300])
        return {"patch": str(patch), "applied": self.result.applied}
