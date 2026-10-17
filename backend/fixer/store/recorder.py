"""Turns job events into database rows: the job record, per-day usage and persisted provider status.

Attached to every job's EventBus (CLI or API), so the dashboard sees CLI runs live and provider state such
as an exhausted daily quota carries over between runs.
"""

from __future__ import annotations

import contextlib
import time
from typing import Any

from fixer.events import Event
from fixer.store.db import Database, dumps, utc_day


class JobRecorder:
    def __init__(self, db: Database, job_id: str):
        self.db = db
        self.job_id = job_id
        self.row: dict[str, Any] | None = None

    def __call__(self, event: Event) -> None:
        with contextlib.suppress(Exception):  # recording must never break a running job
            self._handle(event)

    # ---- event handling ----
    def _handle(self, e: Event) -> None:
        t, d = e.type, e.data
        if t == "job.started":
            self.row = {
                "id": self.job_id,
                "repo": d.get("repo", ""),
                "issue_number": d.get("issue_number", 0),
                "issue_title": d.get("issue_title", ""),
                "issue_url": d.get("issue_url", ""),
                "status": "running",
                "phase": "intake",
                "phases": {p: "pending" for p in d.get("phases", [])},
                "provider": "",
                "requests": 0,
                "request_budget": d.get("request_budget", 0),
                "started_at": e.at,
                "finished_at": None,
                "pr_url": None,
                "reason": None,
                "switches": [],
                "tests": {},
                "job_dir": d.get("job_dir", ""),
            }
            self._save()
        elif t in ("provider.status", "provider.recovered"):
            self._provider_status(d)
        elif t == "llm.response":
            self._usage(d)
            if self.row:
                self.row["requests"] += 1
                self.row["provider"] = d.get("provider", self.row["provider"])
                self._save()
        if not self.row:
            return
        if t == "phase.started":
            self.row["phase"] = d["phase"]
            self.row["phases"][d["phase"]] = "running"
            self._save()
        elif t == "phase.finished":
            self.row["phases"][d["phase"]] = d["state"]
            tests = self.row["tests"]
            if d["phase"] == "baseline" and d["state"] == "done":
                tests["baseline"] = {"passed": d.get("passed", 0), "failing": d.get("failing", 0)}
            elif d["phase"] == "reproduce" and d["state"] == "done":
                tests["repro"] = d.get("test")
            elif d["phase"] == "verify" and d["state"] == "done":
                tests["final"] = {"passed": d.get("passed", 0), "new_failures": d.get("new_failures", 0)}
            if d["state"] == "failed":
                self.row["reason"] = d.get("reason")
            self._save()
        elif t == "provider.switched":
            self.row["switches"].append(
                {
                    "at": e.at,
                    "from": d.get("previous"),
                    "to": d.get("to"),
                    "reason": d.get("reason") or "failover",
                    "agent": d.get("agent"),
                }
            )
            self._save()
        elif t == "github.pr_opened":
            self.row["pr_url"] = d.get("url")
            self._save()
        elif t == "job.finished":
            self.row["status"] = d.get("status", "failed")
            self.row["reason"] = d.get("reason") or self.row["reason"]
            self.row["finished_at"] = e.at
            self.row["pr_url"] = d.get("pr_url") or self.row["pr_url"]
            if d.get("tests"):
                self.row["tests"] = {**self.row["tests"], "result": d["tests"], "repro": d.get("repro_test")}
            self._save()

    # ---- writes ----
    def _save(self) -> None:
        r = self.row
        assert r is not None
        self.db.execute(
            "INSERT INTO jobs(id, repo, issue_number, issue_title, issue_url, status, phase, phases, provider, "
            "requests, request_budget, started_at, finished_at, pr_url, reason, switches, tests, job_dir, "
            "updated_at) VALUES(:id, :repo, :issue_number, :issue_title, :issue_url, :status, :phase, :phases, "
            ":provider, :requests, :request_budget, :started_at, :finished_at, :pr_url, :reason, :switches, "
            ":tests, :job_dir, :updated_at) ON CONFLICT(id) DO UPDATE SET status=excluded.status, "
            "phase=excluded.phase, phases=excluded.phases, provider=excluded.provider, requests=excluded.requests, "
            "finished_at=excluded.finished_at, pr_url=excluded.pr_url, reason=excluded.reason, "
            "switches=excluded.switches, tests=excluded.tests, updated_at=excluded.updated_at",
            {
                **r,
                "phases": dumps(r["phases"]),
                "switches": dumps(r["switches"]),
                "tests": dumps(r["tests"]),
                "updated_at": time.time(),
            },
        )

    def _usage(self, d: dict[str, Any]) -> None:
        usage = d.get("usage") or {}
        self.db.execute(
            "INSERT INTO usage(provider, day, requests, input_tokens, output_tokens) VALUES(?, ?, 1, ?, ?) "
            "ON CONFLICT(provider, day) DO UPDATE SET requests = requests + 1, "
            "input_tokens = input_tokens + excluded.input_tokens, output_tokens = output_tokens + excluded.output_tokens",
            (d.get("provider", "?"), utc_day(), usage.get("input", 0), usage.get("output", 0)),
        )

    def _provider_status(self, d: dict[str, Any]) -> None:
        state = d.get("state", "active")
        self.db.execute(
            "INSERT INTO provider_status(provider, state, reason, retry_at, updated_at) VALUES(?, ?, ?, ?, ?) "
            "ON CONFLICT(provider) DO UPDATE SET state=excluded.state, reason=excluded.reason, "
            "retry_at=excluded.retry_at, updated_at=excluded.updated_at",
            (d.get("provider"), state, d.get("reason", ""), d.get("retry_at"), time.time()),
        )
