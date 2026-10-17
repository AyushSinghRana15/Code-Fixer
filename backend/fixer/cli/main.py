"""`fixer` command line."""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table

from fixer.config import Budget, load_env
from fixer.events import Event, EventBus
from fixer.llm.client import OpenAICompatProvider, ProviderError
from fixer.llm.providers import CATALOG, configured, mask, models_for
from fixer.llm.router import LLMRouter

app = typer.Typer(no_args_is_help=True, add_completion=False, help="Code Fixer: reproduce, fix and verify bugs.")
providers_app = typer.Typer(no_args_is_help=True, help="LLM providers configured through environment variables.")
app.add_typer(providers_app, name="providers")
console = Console(highlight=False, emoji=False)

AGENT_COLORS = ["magenta", "blue", "cyan", "green", "yellow", "bright_magenta", "bright_blue"]
PHASE_LABEL = {
    "context": "Context (pack, + parallel scouts if needed)",
    "intake": "Intake",
    "env": "Env setup",
    "baseline": "Baseline",
    "reproduce": "Reproduce",
    "localize": "Localize",
    "fix": "Fix loop",
    "verify": "Verify",
    "review": "Review",
    "deliver": "Deliver",
}


class Renderer:
    """Turns job events into readable terminal output."""

    def __init__(self, verbose: bool):
        self.verbose = verbose
        self.colors: dict[str, str] = {}

    def tag(self, d: dict) -> str:
        """Short coloured agent label, so interleaved output from parallel agents stays readable."""
        agent = d.get("agent")
        if not agent:
            return ""
        color = self.colors.setdefault(agent, AGENT_COLORS[len(self.colors) % len(AGENT_COLORS)])
        return f"[{color}]{agent:<11}[/] "

    def __call__(self, e: Event) -> None:
        d, t = e.data, e.type
        tag = self.tag(d)
        if t == "phase.started":
            console.print(f"\n[bold]▸ {PHASE_LABEL.get(d['phase'], d['phase'])}[/]")
        elif t == "phase.finished":
            extra = {k: v for k, v in d.items() if k not in ("phase", "state", "job")}
            if d["state"] == "failed":
                console.print(f"  [red]✗ {d.get('reason', '')}[/]")
            elif extra:
                if d["phase"] == "localize":
                    for c in extra.get("candidates", [])[:5]:
                        console.print(f"  [dim]· {c}[/]")
                else:
                    console.print("  [green]✓[/] " + " · ".join(f"{k}: {v}" for k, v in extra.items()))
        elif t == "tool.call":
            args = ", ".join(f"{k}={v!r}" for k, v in d["args"].items() if k not in ("content", "new_text", "old_text"))
            console.print(f"  {tag}[cyan]↳ {d['tool']}[/]([dim]{args[:110]}[/])")
        elif t == "tool.result" and not d["ok"]:
            console.print(f"  {tag}  [yellow]{d['preview'].splitlines()[0][:130]}[/]")
        elif t == "tests.ran":
            mark = "[green]pass[/]" if d["ok"] else "[red]fail[/]"
            console.print(f"  {tag}  tests {mark}: {d['passed']} passed, {d['failed']} failed, {d['errors']} errors")
        elif t == "agent.thought" and self.verbose:
            console.print(f"  {tag}[dim italic]{d['text'][:300]}[/]")
        elif t == "agent.finish_rejected":
            console.print(f"  {tag}  [yellow]finish rejected: {d['reason'].splitlines()[0][:130]}[/]")
        elif t == "agent.stuck":
            console.print(f"  {tag}[yellow]⚠ same failure {d['repeats']}× in a row; nudging the agent to step back[/]")
        elif t == "loop.back":
            console.print(f"  {tag}[yellow]↺ back to {d['to']}: {d['reason']}[/]")
        elif t == "candidate.won":
            console.print(f"  {tag}[bold green]★ verified first — wins the race; other fixers are stopped[/]")
        elif t == "candidate.started":
            console.print(f"  {tag}[bold]started[/] ({d['reason']})")
        elif t == "agent.failed":
            console.print(f"  {tag}[yellow]agent failed: {d['reason']}[/]")
        elif t == "provider.switched":
            console.print(f"  {tag}[yellow]⇄ provider {d['previous']} → {d['to']} ({d.get('reason') or 'failover'})[/]")
        elif t == "provider.status" and d["state"] != "active":
            console.print(f"  [yellow]⚠ {d['provider']}: {d['state']} ({d['reason']})[/]")
        elif t == "router.model_skipped":
            console.print(f"  [dim]skipping model on {d['provider']}: {d['reason'][:100]}[/]")
        elif t in ("router.waiting",):
            console.print(f"  [dim]waiting {d['seconds']}s for rate limit…[/]")
        elif t == "llm.request" and self.verbose:
            console.print(f"  {tag}[dim]llm #{d['n']} {d['provider']}/{d['model']} ({d['role']})[/]")
        elif t == "review.verdict":
            if d["approve"]:
                console.print("  [green]✓ reviewer approved[/]")
            else:
                console.print("  [yellow]reviewer concerns:[/] " + "; ".join(d["concerns"])[:300])
        elif t == "github.cloned":
            console.print(f"  [dim]cloned {d['repo']} ({d['branch']})[/]")
        elif t == "github.pr_opened":
            console.print(f"  [bold green]⇪ opened {'draft ' if d['draft'] else ''}PR:[/] {d['url']}")
        elif t == "github.commented":
            console.print(f"  [dim]commented findings on {d['issue']}[/]")
        elif t == "note":
            console.print(f"  [dim]note: {d['text']}[/]")


def build_router(max_requests: int, private: bool, bus: EventBus, only: str | None = None) -> LLMRouter:
    providers = [OpenAICompatProvider(spec, key) for spec, key in configured() if not only or spec.id == only]
    if not providers:
        console.print("[red]No LLM provider configured.[/] Add a key to backend/.env, e.g. FIXER_OPENROUTER_API_KEY=…")
        raise typer.Exit(2)
    return LLMRouter(
        providers, private_repo=private, max_requests=max_requests, on_event=lambda type, **data: bus.emit(type, **data)
    )


# Options shared by `run` (local repo) and `fix` (GitHub issue)
Sandbox = Annotated[str, typer.Option(help="local or docker")]
MaxRequests = Annotated[int, typer.Option(help="LLM request budget for this job.")]
MaxMinutes = Annotated[int, typer.Option(help="Time budget for this job.")]
OnlyProvider = Annotated[str | None, typer.Option("--provider", help="Use only this provider (e.g. groq).")]
Scouts = Annotated[
    str, typer.Option(help="LLM scouts: auto (only if the code-built context pack is weak), always, never.")
]
Candidates = Annotated[
    int, typer.Option(help="Fixer agents racing in separate sandboxes (default: one per provider, max 2).")
]
Stagger = Annotated[
    int, typer.Option(help="Start backup fixers after the first has used this many turns (0 = all at once).")
]
ContextPackOpt = Annotated[
    bool, typer.Option("--context-pack/--no-context-pack", help="Build the code-only context pack.")
]
Verbose = Annotated[bool, typer.Option("--verbose", "-v")]


def _execute(
    *,
    repo_label: str,
    private: bool,
    max_requests: int,
    provider: str | None,
    verbose: bool,
    extra_secrets: list[str] | None = None,
    **job_kwargs,
) -> None:
    """Build the router and job, stream events to the terminal, then print the result."""
    from fixer.config import fixer_home
    from fixer.orchestrator.pipeline import Job, JobConfig
    from fixer.store.trajectory import TrajectoryLog

    kind = job_kwargs.pop("sandbox") or os.environ.get("FIXER_SANDBOX", "local")
    if kind == "local":
        console.print("[dim]Sandbox: local (no isolation; only use on repos you trust).[/]")
    bus = EventBus(Renderer(verbose))
    router = build_router(max_requests, private=private, bus=bus, only=provider)
    candidates = job_kwargs.pop("candidates") or min(2, len(router.providers))
    max_minutes = job_kwargs.pop("max_minutes")
    cfg = JobConfig(
        sandbox=kind,
        budget=Budget(max_requests=max_requests, max_seconds=max_minutes * 60),
        candidates=candidates,
        **job_kwargs,
    )
    secrets = [k for _, k in configured() if k] + (extra_secrets or [])
    log = TrajectoryLog(fixer_home() / "runs" / cfg.job_id / "events.jsonl", secrets)
    bus.add(log)
    console.print(
        f"[bold]Job {cfg.job_id}[/] · {repo_label} · providers: "
        + ", ".join(p.spec.id for p in router.providers)
        + f" · scouts: {cfg.scouts} · fixers: {cfg.candidates} (stagger {cfg.stagger})"
        + (" · private repo" if private else "")
    )
    result = Job(cfg, router, bus).run()
    log.close()

    color = {"fixed": "green", "needs_review": "yellow", "paused": "yellow"}.get(result.status, "red")
    lines = [f"[bold {color}]{result.status.upper()}[/]  {result.reason}".rstrip()]
    if result.pr_url:
        lines.append(f"[bold]Pull request:[/] {result.pr_url}  (branch {result.branch})")
    if result.repro_test:
        lines.append(f"Reproduction test: {result.repro_test}")
    if result.summary:
        lines.append(f"Summary: {result.summary}")
    if result.review.get("concerns"):
        lines.append("Reviewer concerns: " + "; ".join(result.review["concerns"]))
    if result.winner:
        lines.append(f"Winner: {result.winner} · " + "; ".join(f"{k}: {v}" for k, v in result.candidates.items()))
    tok = result.tokens or {}
    lines.append(
        f"LLM requests: {result.requests}/{max_requests} · tokens: {tok.get('input', 0):,} in / "
        f"{tok.get('output', 0):,} out · {result.seconds:.0f}s"
    )
    lines.append(f"Run folder: {result.job_dir}")
    if result.patch_path and not result.pr_url:
        hint = (
            "  [green](applied to your repo)[/]"
            if result.applied
            else (f"\nApply with: git -C {cfg.repo} apply {result.patch_path}" if not cfg.github else "")
        )
        lines.append("Patch: " + result.patch_path + hint)
    console.print()
    console.print(Panel("\n".join(lines), title="Result", expand=False))
    if result.agents:
        usage = Table("agent", "requests", "tokens in", "tokens out", title="Usage by agent", title_justify="left")
        for name, u in result.agents.items():
            usage.add_row(name, str(u["requests"]), f"{u['input']:,}", f"{u['output']:,}")
        console.print(usage)
    if result.diff and result.status in ("fixed", "needs_review"):
        console.print(Syntax(result.diff, "diff", theme="ansi_dark", word_wrap=True))
    raise typer.Exit(0 if result.status == "fixed" else 1)


@app.command()
def run(
    repo: Annotated[Path, typer.Option("--repo", "-r", help="Path to a local repository.")],
    issue: Annotated[str | None, typer.Option("--issue", "-i", help="Bug report text.")] = None,
    issue_file: Annotated[Path | None, typer.Option("--issue-file", help="Read the bug report from a file.")] = None,
    sandbox: Sandbox = "",
    max_requests: MaxRequests = 60,
    max_minutes: MaxMinutes = 20,
    provider: OnlyProvider = None,
    public: Annotated[
        bool, typer.Option("--public", help="Repo is public: allow providers that train on data.")
    ] = False,
    apply: Annotated[bool, typer.Option("--apply", help="Apply the verified patch to your repo.")] = False,
    scouts: Scouts = "auto",
    candidates: Candidates = 0,
    context_pack: ContextPackOpt = True,
    stagger: Stagger = 5,
    verbose: Verbose = False,
) -> None:
    """Fix a bug in a local repository: reproduce it with a failing test, fix it, verify the fix."""
    load_env()
    text = issue or (issue_file.read_text() if issue_file else "")
    if not text.strip():
        console.print("[red]Give the bug report with --issue or --issue-file.[/]")
        raise typer.Exit(2)
    _execute(
        repo_label=f"repo {repo}",
        private=not public,
        max_requests=max_requests,
        provider=provider,
        verbose=verbose,
        repo=repo,
        issue=text,
        sandbox=sandbox,
        max_minutes=max_minutes,
        apply=apply,
        scouts=scouts,
        candidates=candidates,
        stagger=stagger,
        context_pack=context_pack,
    )


@app.command()
def fix(
    issue: Annotated[
        str, typer.Argument(help="GitHub issue: https://github.com/owner/repo/issues/12 or owner/repo#12")
    ],
    pr: Annotated[bool, typer.Option("--pr/--no-pr", help="Open a pull request with the verified fix.")] = True,
    draft: Annotated[bool, typer.Option("--draft/--ready", help="Open the PR as a draft (default) or ready.")] = True,
    comment_on_failure: Annotated[
        bool, typer.Option("--comment-on-failure", help="If it can't fix the bug, comment its findings on the issue.")
    ] = False,
    sandbox: Sandbox = "",
    max_requests: MaxRequests = 60,
    max_minutes: MaxMinutes = 20,
    provider: OnlyProvider = None,
    scouts: Scouts = "auto",
    candidates: Candidates = 0,
    context_pack: ContextPackOpt = True,
    stagger: Stagger = 5,
    verbose: Verbose = False,
) -> None:
    """Fix a GitHub issue: clone the repo, reproduce, fix and verify, then open a pull request."""
    load_env()
    from fixer.github.client import GitHubClient, GitHubError, find_token, parse_issue_ref
    from fixer.github.workflow import prepare
    from fixer.orchestrator.pipeline import GitHubJob

    try:
        ref = parse_issue_ref(issue)
        token = find_token()
        if not token:
            console.print(
                "[yellow]No GitHub token found (FIXER_GITHUB_TOKEN, GITHUB_TOKEN or `gh auth login`). "
                "Public repos can still be read, but no PR can be opened.[/]"
            )
        client = GitHubClient(token)
        target = prepare(client, ref)
    except GitHubError as err:
        console.print(f"[red]{err}[/]")
        raise typer.Exit(2) from err
    if (pr or comment_on_failure) and not token:
        console.print("[red]A token is needed to open PRs or comment. Use --no-pr to only produce a patch.[/]")
        raise typer.Exit(2)

    console.print(
        f"[bold]{ref}[/] · {target.title}\n[dim]{target.issue_url} · default branch "
        f"{target.default_branch} · {'private' if target.private else 'public'} · "
        f"{'push access' if target.can_push else 'will push to your fork'}[/]"
    )
    gh = GitHubJob(
        target=target, client=client, token=token, open_pr=pr, draft=draft, comment_on_failure=comment_on_failure
    )
    _execute(
        repo_label=str(ref),
        private=target.private,
        max_requests=max_requests,
        provider=provider,
        verbose=verbose,
        extra_secrets=[token] if token else [],
        repo=Path("."),
        issue=target.issue_text,
        sandbox=sandbox,
        max_minutes=max_minutes,
        scouts=scouts,
        candidates=candidates,
        stagger=stagger,
        context_pack=context_pack,
        github=gh,
    )


@providers_app.command("list")
def providers_list() -> None:
    """Show providers that have a key, in fallback order."""
    load_env()
    table = Table("#", "provider", "key", "fix model", "rpm", "trains on data")
    rows = configured()
    for i, (spec, key) in enumerate(rows, 1):
        table.add_row(
            str(i),
            spec.id,
            mask(key),
            models_for(spec, "fix")[0],
            str(spec.rpm or "—"),
            "yes" if spec.trains_on_data else "no",
        )
    console.print(table if rows else "[yellow]No providers configured. Add keys to backend/.env.[/]")


@providers_app.command("test")
def providers_test(provider: Annotated[str | None, typer.Argument()] = None) -> None:
    """Live check: key works, model answers, tool calling works. Uses 1 request per provider."""
    load_env()
    tool = {
        "type": "function",
        "function": {
            "name": "add",
            "description": "Add two integers.",
            "parameters": {
                "type": "object",
                "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
                "required": ["a", "b"],
            },
        },
    }
    msgs = [{"role": "user", "content": "Use the add tool to add 2 and 3."}]
    for spec, key in configured():
        if provider and spec.id != provider:
            continue
        client = OpenAICompatProvider(spec, key, timeout=60)
        for model in models_for(spec, "fix"):
            t0 = time.monotonic()
            try:
                msg = client.complete(model, msgs, [tool], max_tokens=200, temperature=0)
            except ProviderError as err:
                console.print(f"[red]✗[/] {spec.id} / {model}: {err.kind} – {str(err)[:160]}")
                if err.kind in ("auth", "credits", "quota"):
                    break
                continue
            ms = (time.monotonic() - t0) * 1000
            tools_ok = any(c.name == "add" for c in msg.tool_calls)
            mark = "[green]✓[/]" if tools_ok else "[yellow]~[/]"
            console.print(
                f"{mark} {spec.id} / {model}: {ms:.0f} ms, tool calling "
                + ("works" if tools_ok else "NOT used (text only)")
            )
            break


@app.command()
def doctor() -> None:
    """Check the tools the agent needs."""
    load_env()
    from fixer.sandbox.docker import docker_available

    checks = [
        ("git", bool(shutil.which("git"))),
        ("ripgrep (rg)", bool(shutil.which("rg"))),
        ("uv (fast Python setup)", bool(shutil.which("uv"))),
        ("docker running", docker_available()),
        ("LLM provider key", bool(configured())),
    ]
    for name, ok in checks:
        console.print(("[green]✓[/] " if ok else "[yellow]✗[/] ") + name)
    console.print(f"[dim]Known providers: {', '.join(CATALOG)}[/]")


if __name__ == "__main__":
    app()
