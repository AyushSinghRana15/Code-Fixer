"""Database rows → the JSON shapes the dashboard expects (frontend/src/types/index.ts)."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from typing import Any

from fixer.llm.providers import CATALOG, models_for
from fixer.llm.registry import ProviderEntry
from fixer.store.db import Database, utc_day

STALE_AFTER = 30 * 60  # a "running" job with no update for this long was interrupted (process killed)


def iso(ts: float | None) -> str | None:
    return datetime.fromtimestamp(ts, UTC).isoformat().replace("+00:00", "Z") if ts else None


def job_view(row: dict[str, Any], now: float | None = None) -> dict[str, Any]:
    now = now or time.time()
    phases = json.loads(row["phases"] or "{}")
    tests = json.loads(row["tests"] or "{}")
    switches = json.loads(row["switches"] or "[]")
    status, reason = row["status"], row["reason"]
    if status == "running" and now - row["updated_at"] > STALE_AFTER:
        status, reason = "failed", reason or "interrupted (the process stopped before the job finished)"
    if status == "fixed" and row["pr_url"]:
        status = "pr_opened"

    result = tests.get("result") or {}
    base = result.get("baseline") or {}
    final = result.get("final") or {}
    baseline = tests.get("baseline") or {}
    view_tests = None
    if base or baseline:
        repro_state = "not_written"
        if tests.get("repro"):
            repro_state = (
                "passing"
                if status in ("fixed", "pr_opened", "needs_review") or phases.get("fix") == "done"
                else "failing"
            )
        view_tests = {
            "baselinePassed": base.get("passed", baseline.get("passed", 0)),
            "baselineFailing": len(base["failing"]) if "failing" in base else baseline.get("failing", 0),
            "repro": repro_state,
        }
        if final:
            view_tests["final"] = {"passed": final.get("passed", 0), "failed": len(final.get("failing", []))}
    return {
        "id": row["id"],
        "repo": row["repo"],
        "issueNumber": row["issue_number"],
        "issueTitle": row["issue_title"],
        "issueUrl": row["issue_url"] or "",
        "status": status,
        "phase": row["phase"],
        "phases": phases,
        "provider": row["provider"],
        "requests": row["requests"],
        "requestBudget": row["request_budget"],
        "startedAt": iso(row["started_at"]),
        "finishedAt": iso(row["finished_at"]),
        "prUrl": row["pr_url"],
        "reason": reason,
        "switches": [
            {"at": iso(s["at"]), "from": s.get("from"), "to": s.get("to"), "reason": s.get("reason")} for s in switches
        ],
        **({"tests": view_tests} if view_tests else {}),
        "trajectoryPath": f"{row['job_dir']}/events.jsonl" if row["job_dir"] else "",
    }


def provider_view(e: ProviderEntry, status: dict[str, Any] | None, used: int, now: float) -> dict[str, Any]:
    state, reason, retry = "active", None, None
    if not e.enabled:
        state, reason = "disabled", "Disabled by you"
    elif e.spec.needs_key and not e.key:
        state, reason = "invalid_key", "No key set"
    elif status:
        if status["state"] in ("rate_limited", "quota_exhausted") and (status["retry_at"] or 0) > now:
            state, reason, retry = status["state"], status["reason"], status["retry_at"]
        elif status["state"] in ("invalid_key", "out_of_credits"):
            state, reason = status["state"], status["reason"]
    return {
        "id": e.id,
        "preset": e.preset,
        "label": e.label,
        "state": state,
        **({"stateReason": reason} if reason else {}),
        **({"retryAt": iso(retry)} if retry else {}),
        **({"keyHint": e.key_hint} if e.key_hint else {}),
        **({"baseUrl": e.spec.base_url} if e.preset in ("custom", "ollama") else {}),
        "models": {role: (models_for(e.spec, role) or ("",))[0] for role in ("fix", "critic", "summarize")},
        "trainsOnData": e.spec.trains_on_data,
        "usage": {"requestsToday": used, **({"dailyLimit": e.spec.daily_limit} if e.spec.daily_limit else {})},
        "source": e.source,
    }


def providers_view(db: Database, entries: list[ProviderEntry]) -> list[dict[str, Any]]:
    now = time.time()
    status = {r["provider"]: r for r in db.query("SELECT * FROM provider_status")}
    usage = {r["provider"]: r["requests"] for r in db.query("SELECT * FROM usage WHERE day = ?", (utc_day(),))}
    return [provider_view(e, status.get(e.id), usage.get(e.id, 0), now) for e in entries]


def stats_view(db: Database, providers: list[dict[str, Any]]) -> dict[str, Any]:
    now = time.time()
    local_midnight = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    jobs = [job_view(r, now) for r in db.query("SELECT * FROM jobs WHERE started_at >= ?", (now - 7 * 86400,))]
    finished = [j for j in jobs if j["status"] in ("fixed", "pr_opened", "needs_review", "gave_up", "failed")]
    succeeded = [j for j in finished if j["status"] in ("fixed", "pr_opened")]
    usable = [p for p in providers if p["state"] == "active"]
    return {
        "jobsToday": sum(1 for r in db.query("SELECT started_at FROM jobs") if r["started_at"] >= local_midnight),
        "runningNow": sum(1 for j in jobs if j["status"] == "running"),
        "successRate7d": (len(succeeded) / len(finished)) if finished else None,
        "finished7d": len(finished),
        "succeeded7d": len(succeeded),
        "requestsToday": sum(p["usage"]["requestsToday"] for p in providers),
        "capacityToday": sum(
            p["usage"].get("dailyLimit", 0) for p in providers if p["state"] not in ("disabled", "invalid_key")
        ),
        "activeProvider": usable[0]["id"] if usable else None,
        "fallbacksReady": max(0, len(usable) - 1),
    }


def presets_view() -> list[dict[str, Any]]:
    out = []
    for spec in CATALOG.values():
        out.append(
            {
                "id": spec.id,
                "name": spec.name,
                "note": spec.note,
                **({"keyUrl": spec.key_url} if spec.key_url else {}),
                **({"keyPrefix": spec.key_prefix} if spec.key_prefix else {}),
                "needsKey": spec.needs_key,
                "needsBaseUrl": spec.id in ("custom", "ollama"),
                "trainsOnData": spec.trains_on_data,
                **({"dailyLimit": spec.daily_limit} if spec.daily_limit else {}),
                "defaultModels": {r: (spec.models.get(r) or ("",))[0] for r in ("fix", "critic", "summarize")},
            }
        )
    return out
