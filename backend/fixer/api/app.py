"""FastAPI server for the dashboard (docs/frontend.md §6). Run with `fixer serve` (binds to 127.0.0.1).

Keys are write-only: they go into the encrypted vault and only masked hints ever come back out.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import os
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from fixer.api.views import job_view, presets_view, providers_view, stats_view
from fixer.config import Budget, load_env
from fixer.github.client import GitHubClient, GitHubError, parse_issue_ref, token_source
from fixer.llm.check import CheckResult, check_provider
from fixer.llm.providers import CATALOG, ProviderSpec
from fixer.llm.registry import ProviderEntry, load_entries, open_vault
from fixer.store.db import Database
from fixer.vault.vault import Vault, mask_secret

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "[::1]"}
DEFAULT_ORIGINS = {"http://localhost:3000", "http://127.0.0.1:3000"}

Checker = Callable[[ProviderSpec, str | None], CheckResult]


class NewProvider(BaseModel):
    preset: str
    label: str | None = None
    apiKey: str | None = None  # noqa: N815 - frontend field names
    baseUrl: str | None = None  # noqa: N815
    models: dict[str, str] | None = None


class ProviderPatch(BaseModel):
    enabled: bool | None = None
    label: str | None = None
    models: dict[str, str] | None = None


class KeyBody(BaseModel):
    apiKey: str  # noqa: N815


class TokenBody(BaseModel):
    token: str


class NewJob(BaseModel):
    issue: str | None = None  # GitHub issue URL or owner/repo#12
    repoPath: str | None = None  # noqa: N815 - or a local repo + issue text
    issueText: str | None = None  # noqa: N815
    openPr: bool = True  # noqa: N815
    draft: bool = True
    maxRequests: int = 60  # noqa: N815


def create_app(
    db: Database | None = None,
    checker: Checker = check_provider,
    github_factory: Callable[[str | None], GitHubClient] = GitHubClient,
) -> FastAPI:
    load_env()
    db = db or Database()
    app = FastAPI(title="Code Fixer API", docs_url="/api/docs", openapi_url="/api/openapi.json")
    allowed_origins = DEFAULT_ORIGINS | {
        o.strip() for o in os.environ.get("FIXER_ALLOWED_ORIGINS", "").split(",") if o.strip()
    }
    running: dict[str, threading.Thread] = {}
    opened: dict[str, Vault] = {}

    def get_vault() -> Vault | None:
        """Open the vault once (one keychain lookup), then reuse it."""
        if "v" not in opened:
            v = open_vault(db)
            if v is None:
                return None
            opened["v"] = v
        return opened["v"]

    # ---- local-only protections (docs/frontend.md §6.4) ----
    @app.middleware("http")
    async def local_only(request: Request, call_next):
        host = (request.headers.get("host") or "").rsplit(":", 1)[0]
        if host not in LOCAL_HOSTS:  # blocks DNS-rebinding: a malicious site's hostname resolving to 127.0.0.1
            return JSONResponse({"detail": "This API only answers requests addressed to localhost."}, 403)
        origin = request.headers.get("origin")
        if request.method not in ("GET", "HEAD", "OPTIONS") and origin and origin not in allowed_origins:
            return JSONResponse({"detail": f"Origin {origin} may not change state here."}, 403)
        return await call_next(request)

    # ---- helpers ----
    def vault() -> Vault:
        v = get_vault()
        if v is None:
            raise HTTPException(
                503,
                "The key vault is locked: no OS keychain available. Start the server with FIXER_VAULT_PASSPHRASE set.",
            )
        return v

    def entries(decrypt: bool = False) -> list[ProviderEntry]:
        return load_entries(db, get_vault(), decrypt=decrypt)

    def providers() -> list[dict[str, Any]]:
        return providers_view(db, entries())

    def entry(pid: str, decrypt: bool = False) -> ProviderEntry:
        for e in entries(decrypt):
            if e.id == pid:
                return e
        raise HTTPException(404, f"No provider '{pid}'.")

    def vault_entry(pid: str) -> ProviderEntry:
        e = entry(pid)
        if e.source != "vault":
            raise HTTPException(
                409,
                f"'{pid}' is configured in backend/.env. Edit it there, or add it here to "
                "store its key in the encrypted vault instead.",
            )
        return e

    def set_status(pid: str, state: str, reason: str = "", retry_at: float | None = None) -> None:
        db.execute(
            "INSERT INTO provider_status(provider, state, reason, retry_at, updated_at) VALUES(?, ?, ?, ?, ?) "
            "ON CONFLICT(provider) DO UPDATE SET state=excluded.state, reason=excluded.reason, "
            "retry_at=excluded.retry_at, updated_at=excluded.updated_at",
            (pid, state, reason, retry_at, time.time()),
        )

    def validate_key(spec: ProviderSpec, key: str | None) -> CheckResult:
        k = (key or "").strip()
        if spec.needs_key and not k:
            raise HTTPException(400, "Enter an API key.")
        if spec.key_prefix and k and not k.startswith(spec.key_prefix):
            raise HTTPException(
                400, f'This doesn\'t look like a {spec.name} key (they start with "{spec.key_prefix}").'
            )
        result = checker(spec, k or None)
        if result.kind == "auth":
            raise HTTPException(400, f"{spec.name} rejected the key (401). Check that you copied the whole key.")
        return result

    # ---- stats & jobs ----
    @app.get("/api/stats/summary")
    def stats() -> dict[str, Any]:
        return stats_view(db, providers())

    @app.get("/api/jobs")
    def jobs(limit: int = 50) -> list[dict[str, Any]]:
        rows = db.query("SELECT * FROM jobs ORDER BY started_at DESC LIMIT ?", (min(limit, 200),))
        return [job_view(r) for r in rows]

    @app.get("/api/jobs/{job_id}")
    def job(job_id: str) -> dict[str, Any]:
        row = db.one("SELECT * FROM jobs WHERE id = ?", (job_id,))
        if not row:
            raise HTTPException(404, "No such job.")
        return job_view(row)

    @app.post("/api/jobs", status_code=202)
    def start_job(body: NewJob) -> dict[str, Any]:
        from fixer.orchestrator.pipeline import GitHubJob, JobConfig
        from fixer.runner import NoProviders, make_job

        v = get_vault()
        if body.issue:
            token, _ = token_source(v)
            client = github_factory(token)
            try:
                from fixer.github.workflow import prepare

                target = prepare(client, parse_issue_ref(body.issue))
            except GitHubError as err:
                raise HTTPException(400, str(err)) from err
            if body.openPr and not token:
                raise HTTPException(400, "Opening a PR needs a GitHub token (Providers & keys → GitHub).")
            cfg = JobConfig(
                repo=Path("."),
                issue=target.issue_text,
                budget=Budget(max_requests=body.maxRequests),
                candidates=0,
                github=GitHubJob(target=target, client=client, token=token, open_pr=body.openPr, draft=body.draft),
            )
            private, secrets = target.private, [token] if token else []
        elif body.repoPath and body.issueText:
            if not Path(body.repoPath).is_dir():
                raise HTTPException(400, f"Not a directory: {body.repoPath}")
            cfg = JobConfig(
                repo=Path(body.repoPath),
                issue=body.issueText,
                budget=Budget(max_requests=body.maxRequests),
                candidates=0,
            )
            private, secrets = True, []
        else:
            raise HTTPException(400, "Give a GitHub issue, or a local repoPath with issueText.")
        try:
            job, _, log = make_job(cfg, db=db, private=private, extra_secrets=secrets)
        except NoProviders as err:
            raise HTTPException(400, str(err)) from err

        def work() -> None:
            try:
                job.run()
            finally:
                log.close()
                running.pop(cfg.job_id, None)

        t = threading.Thread(target=work, name=f"job-{cfg.job_id}", daemon=True)
        running[cfg.job_id] = t
        t.start()
        return {"id": cfg.job_id}

    # ---- providers ----
    @app.get("/api/providers")
    def list_providers() -> list[dict[str, Any]]:
        return providers()

    @app.get("/api/providers/presets")
    def presets() -> list[dict[str, Any]]:
        return presets_view()

    @app.post("/api/providers")
    def add_provider(body: NewProvider) -> list[dict[str, Any]]:
        spec = CATALOG.get(body.preset)
        if spec is None:
            raise HTTPException(400, f"Unknown provider type '{body.preset}'.")
        if body.preset in ("custom", "ollama"):
            if not (body.baseUrl or (body.preset == "ollama")):
                raise HTTPException(400, "Enter the service's base URL.")
            spec = dataclasses.replace(
                spec,
                base_url=body.baseUrl or spec.base_url,
                models={r: (m,) for r, m in (body.models or {}).items() if m} or spec.models,
                needs_key=body.preset == "custom" and bool(body.apiKey),
            )
            if not any((body.models or {}).values()) and body.preset == "custom":
                raise HTTPException(400, "Enter at least the model to use for fixing.")
        result = validate_key(spec, body.apiKey)
        v = vault()
        key = (body.apiKey or "").strip() or None
        pid = v.add_provider(
            body.preset,
            (body.label or "").strip() or body.preset,
            body.baseUrl,
            body.models or {},
            key,
            mask_secret(key, spec.key_prefix) if key else None,
        )
        if result.kind in ("quota", "rate"):
            set_status(
                pid,
                "quota_exhausted" if result.kind == "quota" else "rate_limited",
                result.message,
                time.time() + (3600 if result.kind == "quota" else 60),
            )
        return providers()

    @app.patch("/api/providers/{pid}")
    def patch_provider(pid: str, body: ProviderPatch) -> list[dict[str, Any]]:
        vault_entry(pid)
        v = vault()
        if body.enabled is not None:
            v.set_enabled(pid, body.enabled)
        v.update(pid, label=body.label, models=body.models)
        return providers()

    @app.put("/api/providers/order")
    def order(ids: list[str] = Body(...)) -> list[dict[str, Any]]:  # noqa: B008
        v = vault()
        vault_ids = [p.id for p in v.providers()]
        try:
            v.reorder([i for i in ids if i in vault_ids])  # env-only providers always follow the vault ones
        except ValueError as err:
            raise HTTPException(400, str(err)) from err
        return providers()

    @app.post("/api/providers/{pid}/test")
    def test_provider(pid: str) -> dict[str, Any]:
        e = entry(pid, decrypt=True)
        result = checker(e.spec, e.key)
        if result.kind == "auth":
            set_status(pid, "invalid_key", "Key rejected (401). Rotate the key to re-enable.")
        elif result.kind == "credits":
            set_status(pid, "out_of_credits", "No credits left")
        elif result.kind == "quota":
            set_status(pid, "quota_exhausted", "Daily quota used up", time.time() + 3600)
        elif result.ok:
            set_status(pid, "active")
        return result.api()

    @app.put("/api/providers/{pid}/key")
    def rotate_key(pid: str, body: KeyBody) -> list[dict[str, Any]]:
        e = vault_entry(pid)
        validate_key(e.spec, body.apiKey)
        vault().put_secret(pid, body.apiKey.strip(), mask_secret(body.apiKey, e.spec.key_prefix))
        set_status(pid, "active")
        return providers()

    @app.delete("/api/providers/{pid}")
    def remove_provider(pid: str) -> list[dict[str, Any]]:
        vault_entry(pid)
        vault().remove_provider(pid)
        return providers()

    # ---- GitHub credential ----
    def github_view(check: bool = False) -> dict[str, Any]:
        v = get_vault()
        token, source = token_source(v)
        if not token:
            return {"state": "missing", "scopes": []}
        cached = json.loads(db.get_meta(f"github_check:{source}") or "null")
        if check or not cached or cached.get("hint") != mask_secret(token):
            try:
                login, scopes = github_factory(token).token_info()
                cached = {"state": "valid", "login": login, "scopes": scopes}
            except GitHubError as err:
                cached = {
                    "state": "invalid" if err.status in (401, 403) else "valid",
                    "scopes": [],
                    **({"error": str(err)} if err.status not in (401, 403) else {}),
                }
            cached.update(hint=mask_secret(token), checkedAt=time.time())
            db.set_meta(f"github_check:{source}", json.dumps(cached))
        hint = {"vault": mask_secret(token), "env": mask_secret(token) + " (env)", "gh": "gh CLI login"}[source]
        from fixer.api.views import iso

        return {
            "state": cached["state"],
            "keyHint": hint,
            "login": cached.get("login"),
            "scopes": cached.get("scopes", []),
            "checkedAt": iso(cached.get("checkedAt")),
            "source": source,
        }

    @app.get("/api/credentials/github")
    def github_get() -> dict[str, Any]:
        return github_view()

    @app.put("/api/credentials/github")
    def github_put(body: TokenBody) -> dict[str, Any]:
        token = body.token.strip()
        if not token.startswith(("ghp_", "github_pat_", "gho_")):
            raise HTTPException(400, 'GitHub tokens start with "ghp_" or "github_pat_".')
        try:
            github_factory(token).token_info()
        except GitHubError as err:
            raise HTTPException(400, f"GitHub rejected the token: {err}") from err
        vault().put_secret(
            "github", token, mask_secret(token, "github_pat_" if token.startswith("github_pat_") else token[:4])
        )
        return github_view(check=True)

    @app.post("/api/credentials/github/test")
    def github_test() -> dict[str, Any]:
        return github_view(check=True)

    @app.delete("/api/credentials/github")
    def github_delete() -> dict[str, Any]:
        vault().delete_secret("github")
        return github_view()

    # ---- live events (SSE) ----
    @app.get("/api/events")
    async def events(request: Request) -> StreamingResponse:
        async def stream():
            seen = {r["id"] for r in db.query("SELECT id FROM jobs")}
            cursor = max([r["u"] for r in db.query("SELECT MAX(updated_at) AS u FROM jobs") if r["u"]] or [0.0])
            last_providers: dict[str, str] = {}
            last_stats = ""
            beat = time.monotonic()
            yield ": connected\n\n"
            while not await request.is_disconnected():
                out = []
                for row in db.query("SELECT * FROM jobs WHERE updated_at > ? ORDER BY updated_at", (cursor,)):
                    cursor = max(cursor, row["updated_at"])
                    kind = "job.updated" if row["id"] in seen else "job.created"
                    seen.add(row["id"])
                    out.append({"type": kind, "job": job_view(row)})
                provs = providers()
                for p in provs:
                    blob = json.dumps(p, sort_keys=True)
                    if last_providers.get(p["id"]) not in (None, blob):
                        out.append({"type": "provider.status_changed", "provider": p})
                    last_providers[p["id"]] = blob
                st = stats_view(db, provs)
                blob = json.dumps(st, sort_keys=True)
                if blob != last_stats:
                    if last_stats:
                        out.append({"type": "stats.updated", "stats": st})
                    last_stats = blob
                if time.monotonic() - beat > 15:
                    out.append({"type": "heartbeat"})
                    beat = time.monotonic()
                for ev in out:
                    yield f"data: {json.dumps(ev)}\n\n"
                await asyncio.sleep(1)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
        )

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {"ok": True, "vault": "unlocked" if get_vault() else "locked", "running_jobs": len(running)}

    return app
