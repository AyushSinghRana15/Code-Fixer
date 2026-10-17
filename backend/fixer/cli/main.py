"""`fixer` command line."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table

from fixer.config import Budget, load_env
from fixer.events import Event
from fixer.llm.providers import CATALOG

app = typer.Typer(no_args_is_help=True, add_completion=False, help="Code Fixer: reproduce, fix and verify bugs.")
providers_app = typer.Typer(no_args_is_help=True, help="LLM providers and their keys (encrypted vault + .env).")
github_app = typer.Typer(no_args_is_help=True, help="GitHub token used by `fixer fix`.")
app.add_typer(github_app, name="github")
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


def _db():
    from fixer.store.db import Database

    return Database()


def _vault(db):
    from fixer.vault.vault import Vault, VaultLocked

    try:
        return Vault.open(db)
    except VaultLocked as err:
        console.print(f"[red]Vault locked:[/] {err}")
        raise typer.Exit(2) from err


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
    """Build the job (vault + env providers, recorded in the dashboard's database), stream events to the
    terminal, then print the result."""
    from fixer.orchestrator.pipeline import JobConfig
    from fixer.runner import NoProviders, make_job

    kind = job_kwargs.pop("sandbox") or os.environ.get("FIXER_SANDBOX", "local")
    if kind == "local":
        console.print("[dim]Sandbox: local (no isolation; only use on repos you trust).[/]")
    candidates = job_kwargs.pop("candidates")
    max_minutes = job_kwargs.pop("max_minutes")
    cfg = JobConfig(
        sandbox=kind,
        budget=Budget(max_requests=max_requests, max_seconds=max_minutes * 60),
        candidates=candidates,
        **job_kwargs,
    )
    try:
        job, router, log = make_job(
            cfg, db=_db(), private=private, only=provider, sinks=[Renderer(verbose)], extra_secrets=extra_secrets
        )
    except NoProviders as err:
        console.print(f"[red]{err}[/]")
        raise typer.Exit(2) from err
    console.print(
        f"[bold]Job {cfg.job_id}[/] · {repo_label} · providers: "
        + ", ".join(p.spec.id for p in router.providers)
        + f" · scouts: {cfg.scouts} · fixers: {cfg.candidates} (stagger {cfg.stagger})"
        + (" · private repo" if private else "")
    )
    result = job.run()
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
        db = _db()
        from fixer.llm.registry import open_vault

        token = find_token(open_vault(db))
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


def _entries(decrypt: bool = False):
    from fixer.llm.registry import load_entries, open_vault

    db = _db()
    return db, load_entries(db, open_vault(db), decrypt=decrypt)


@providers_app.command("list")
def providers_list() -> None:
    """Providers in fallback order: vault entries first, then keys found in .env."""
    load_env()
    from fixer.api.views import providers_view

    db, entries = _entries()
    table = Table("#", "id", "source", "key", "state", "fix model", "today", "trains on data")
    for i, (e, p) in enumerate(zip(entries, providers_view(db, entries), strict=True), 1):
        limit = p["usage"].get("dailyLimit")
        table.add_row(
            str(i),
            e.id,
            e.source,
            e.key_hint or "—",
            p["state"],
            p["models"]["fix"],
            f"{p['usage']['requestsToday']}" + (f"/{limit}" if limit else ""),
            "yes" if e.spec.trains_on_data else "no",
        )
    console.print(table if entries else "[yellow]No providers yet: `fixer providers add openrouter`.[/]")


@providers_app.command("test")
def providers_test(provider: Annotated[str | None, typer.Argument()] = None) -> None:
    """Live check: key works, model answers, tool calling works. Uses 1 request per provider."""
    load_env()
    from fixer.llm.check import check_provider

    _, entries = _entries(decrypt=True)
    for e in entries:
        if (provider and e.id != provider) or not e.usable:
            continue
        r = check_provider(e.spec, e.key)
        mark = "[green]✓[/]" if r.ok and r.toolCalling else ("[yellow]~[/]" if r.ok else "[red]✗[/]")
        console.print(f"{mark} {e.id}: {r.message}")


@providers_app.command("add")
def providers_add(
    preset: Annotated[str, typer.Argument(help=f"One of: {', '.join(CATALOG)}")],
    label: Annotated[str | None, typer.Option(help="Display name.")] = None,
    base_url: Annotated[str | None, typer.Option(help="For custom/ollama.")] = None,
    model: Annotated[str | None, typer.Option(help="Model to use for fixing (overrides the default).")] = None,
) -> None:
    """Add a provider. The key is read from a hidden prompt, checked live, then stored encrypted."""
    load_env()
    from fixer.llm.check import check_provider
    from fixer.llm.registry import _spec_for
    from fixer.vault.vault import mask_secret

    spec0 = CATALOG.get(preset)
    if spec0 is None:
        console.print(f"[red]Unknown provider '{preset}'.[/] Choose from: {', '.join(CATALOG)}")
        raise typer.Exit(2)
    key = None
    if spec0.needs_key:
        if spec0.key_url:
            console.print(f"[dim]Get a key at {spec0.key_url}[/]")
        key = typer.prompt(f"{spec0.name} API key", hide_input=True).strip()
    models = {"fix": model} if model else {}
    spec = _spec_for(preset, preset, base_url, models)
    result = check_provider(spec, key)
    if result.kind == "auth":
        console.print(f"[red]✗ {result.message}[/] Nothing was saved.")
        raise typer.Exit(1)
    db = _db()
    pid = _vault(db).add_provider(
        preset, label or preset, base_url, models, key, mask_secret(key, spec.key_prefix) if key else None
    )
    console.print(f"[green]✓ Added {pid}[/] ({result.message}). Key stored encrypted in {db.path}.")


@providers_app.command("rotate-key")
def providers_rotate(pid: Annotated[str, typer.Argument()]) -> None:
    """Replace a provider's key (checked live first; the old key stays if the new one is rejected)."""
    load_env()
    from fixer.llm.check import check_provider
    from fixer.vault.vault import mask_secret

    db, entries = _entries()
    e = next((x for x in entries if x.id == pid and x.source == "vault"), None)
    if e is None:
        console.print(f"[red]No vault provider '{pid}'.[/]")
        raise typer.Exit(2)
    key = typer.prompt(f"New {e.spec.name} API key", hide_input=True).strip()
    result = check_provider(e.spec, key)
    if result.kind == "auth":
        console.print(f"[red]✗ {result.message}[/] The old key is unchanged.")
        raise typer.Exit(1)
    _vault(db).put_secret(pid, key, mask_secret(key, e.spec.key_prefix))
    db.execute("DELETE FROM provider_status WHERE provider = ?", (pid,))
    console.print(f"[green]✓ Key for {pid} replaced.[/]")


@providers_app.command("order")
def providers_order(ids: Annotated[list[str], typer.Argument(help="Vault provider ids, primary first.")]) -> None:
    """Set the fallback order."""
    db = _db()
    try:
        _vault(db).reorder(ids)
    except ValueError as err:
        console.print(f"[red]{err}[/]")
        raise typer.Exit(2) from err
    console.print("[green]✓ Order saved:[/] " + " → ".join(ids))


@providers_app.command("enable")
def providers_enable(pid: str) -> None:
    db = _db()
    _vault(db).set_enabled(pid, True)
    console.print(f"[green]✓ {pid} enabled[/]")


@providers_app.command("disable")
def providers_disable(pid: str) -> None:
    db = _db()
    _vault(db).set_enabled(pid, False)
    console.print(f"[green]✓ {pid} disabled[/]")


@providers_app.command("remove")
def providers_remove(pid: str) -> None:
    """Remove a provider and delete its encrypted key."""
    db = _db()
    _vault(db).remove_provider(pid)
    console.print(f"[green]✓ {pid} removed[/]")


@providers_app.command("import-env")
def providers_import_env() -> None:
    """Move keys from backend/.env into the encrypted vault (you can then delete them from .env)."""
    load_env()
    from fixer.llm.providers import configured
    from fixer.vault.vault import mask_secret

    db = _db()
    vault = _vault(db)
    have = {p.id for p in vault.providers()}
    moved = []
    for spec, key in configured():
        if spec.id in have or not key:
            continue
        vault.add_provider(spec.id, spec.id, None, {}, key, mask_secret(key, spec.key_prefix))
        moved.append(spec.id)
    if moved:
        console.print(
            f"[green]✓ Imported {', '.join(moved)} into the vault.[/] You can now remove those keys "
            "from backend/.env (while they're there, they take priority)."
        )
    else:
        console.print("Nothing to import.")


@github_app.command("set-token")
def github_set_token() -> None:
    """Store a GitHub token (repo scope) in the encrypted vault."""
    load_env()
    from fixer.github.client import GitHubClient, GitHubError
    from fixer.vault.vault import mask_secret

    token = typer.prompt("GitHub token", hide_input=True).strip()
    try:
        login, scopes = GitHubClient(token).token_info()
    except GitHubError as err:
        console.print(f"[red]✗ {err}[/]")
        raise typer.Exit(1) from err
    db = _db()
    _vault(db).put_secret("github", token, mask_secret(token))
    console.print(f"[green]✓ Stored.[/] Signed in as @{login}; scopes: {', '.join(scopes) or 'fine-grained'}")


@github_app.command("status")
def github_status() -> None:
    """Which GitHub token `fixer fix` will use, and whether it works."""
    load_env()
    from fixer.github.client import GitHubClient, GitHubError, token_source
    from fixer.llm.registry import open_vault

    token, source = token_source(open_vault(_db()))
    if not token:
        console.print("[yellow]No GitHub token: run `fixer github set-token` or `gh auth login`.[/]")
        return
    try:
        login, scopes = GitHubClient(token).token_info()
        console.print(f"[green]✓[/] token from {source}: @{login}, scopes {', '.join(scopes) or 'fine-grained'}")
    except GitHubError as err:
        console.print(f"[red]✗ token from {source} doesn't work: {err}[/]")


@app.command()
def serve(
    port: Annotated[int, typer.Option(help="Port on 127.0.0.1")] = 8000,
) -> None:
    """Run the API server for the dashboard (localhost only)."""
    load_env()
    import uvicorn

    from fixer.api.app import create_app

    console.print(
        f"[bold]Code Fixer API[/] on http://127.0.0.1:{port} (docs at /api/docs). Dashboard: "
        "`cd frontend && npm run dev`."
    )
    uvicorn.run(create_app(), host="127.0.0.1", port=port, log_level="warning")


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
        ("LLM provider configured", any(e.usable for e in _entries()[1])),
    ]
    for name, ok in checks:
        console.print(("[green]✓[/] " if ok else "[yellow]✗[/] ") + name)
    console.print(f"[dim]Known providers: {', '.join(CATALOG)}[/]")


if __name__ == "__main__":
    app()
