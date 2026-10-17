"""Builds a ready-to-run Job: providers from the vault (+ env), trajectory log, database recorder.

Used by the CLI and by the API server, so jobs from either show up in the dashboard the same way.
"""

from __future__ import annotations

from collections.abc import Callable

from fixer.config import fixer_home
from fixer.events import Event, EventBus
from fixer.llm.registry import build_router, load_entries, open_vault
from fixer.llm.router import LLMRouter
from fixer.orchestrator.pipeline import Job, JobConfig
from fixer.store.db import Database
from fixer.store.recorder import JobRecorder
from fixer.store.trajectory import TrajectoryLog


class NoProviders(Exception):
    pass


def make_job(
    cfg: JobConfig,
    *,
    db: Database | None,
    private: bool,
    only: str | None = None,
    sinks: list[Callable[[Event], None]] | None = None,
    extra_secrets: list[str] | None = None,
) -> tuple[Job, LLMRouter, TrajectoryLog]:
    bus = EventBus(*(sinks or []))
    vault = open_vault(db) if db is not None else None
    entries = load_entries(db, vault)
    router = build_router(
        entries,
        db=db,
        private_repo=private,
        max_requests=cfg.budget.max_requests,
        on_event=lambda type, **data: bus.emit(type, **data),
        only=only,
    )
    if not router.providers:
        raise NoProviders(
            "No usable LLM provider. Add one in the dashboard (Providers & keys), with "
            "`fixer providers add`, or put a key in backend/.env."
        )
    if cfg.candidates <= 0:
        cfg.candidates = min(2, len(router.providers))
    secrets = [e.key for e in entries if e.key] + list(extra_secrets or [])
    log = TrajectoryLog(fixer_home() / "runs" / cfg.job_id / "events.jsonl", secrets)
    bus.add(log)
    if db is not None:
        bus.add(JobRecorder(db, cfg.job_id))
    return Job(cfg, router, bus), router, log
