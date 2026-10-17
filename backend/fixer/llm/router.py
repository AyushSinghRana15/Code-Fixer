"""LLM router: picks a provider, paces requests, and fails over (Plan.md §6 and §7.5).

Thread-safe: several agents (scouts, parallel fixers) share one router, so provider health, the request
budget and rate-limit pacing are global. Network calls and waits happen outside the lock.
The conversation is plain OpenAI-style messages, so switching provider mid-job just works.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from fixer.llm.client import LLMMessage, Provider, ProviderError
from fixer.llm.providers import ROLE_PREFERENCE, models_for

SHORT_WAIT = 20.0  # seconds; rate limits shorter than this are waited out on the same provider
SERVER_RETRIES = 2
UNKNOWN_RATE_WAIT = 8.0  # first 429 without retry-after: wait this long and retry the same provider once
FLAKY_RETRIES = 2  # malformed tool calls / empty replies: retry the same model, then try another provider


class NoProviderAvailable(Exception):
    """Every provider is down or used up. The job should pause, not fail."""


class RequestBudgetExceeded(Exception):
    pass


@dataclass
class ProviderStatus:
    state: str = "active"  # active | rate_limited | quota_exhausted | invalid_key | out_of_credits | no_model
    reason: str = ""
    retry_at: float = 0.0  # epoch seconds
    model_index: dict[str, int] = field(default_factory=dict)
    next_slot: float = 0.0  # earliest time the next request may start (rpm pacing)
    requests: int = 0


@dataclass
class ChatResult:
    message: LLMMessage
    provider: str
    model: str


@dataclass
class _Attempt:
    """Per-call bookkeeping (each concurrent chat() call has its own)."""

    skip: set[str] = field(default_factory=set)  # providers to avoid for this call only
    server: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    flaky: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    rate: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    reason: str = ""


def _next_utc_midnight(now: float) -> float:
    d = datetime.fromtimestamp(now, UTC) + timedelta(days=1)
    return d.replace(hour=0, minute=0, second=5, microsecond=0).timestamp()


class LLMRouter:
    def __init__(
        self,
        providers: list[Provider],
        *,
        private_repo: bool = False,
        max_requests: int | None = None,
        on_event: Callable[..., None] | None = None,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.providers = providers
        self.private_repo = private_repo
        self.max_requests = max_requests
        self.status = {p.spec.id: ProviderStatus() for p in providers}
        self.requests = 0
        self.tokens = {"input": 0, "output": 0}
        self.by_agent: dict[str, dict[str, int]] = defaultdict(lambda: {"requests": 0, "input": 0, "output": 0})
        self._current: dict[str, str] = {}  # agent -> provider it used last
        self._lock = threading.Lock()
        self._emit = on_event or (lambda *a, **k: None)
        self._clock = clock
        self._sleep = sleep

    # ---- selection (call with the lock held) ----
    def _usable(self, p: Provider, now: float) -> bool:
        if self.private_repo and p.spec.trains_on_data:
            return False
        st = self.status[p.spec.id]
        if st.state in ("invalid_key", "out_of_credits", "no_model"):
            return False
        if st.state in ("rate_limited", "quota_exhausted"):
            if now < st.retry_at:
                return False
            st.state, st.reason = "active", ""
            self._emit("provider.recovered", provider=p.spec.id)
        return True

    def _ordered(self, prefer: list[str] | None, role: str) -> list[Provider]:
        prefer = prefer or list(ROLE_PREFERENCE.get(role, ()))
        rank = {pid: i for i, pid in enumerate(prefer)}
        return sorted(self.providers, key=lambda p: rank.get(p.spec.id, len(rank)))

    def _mark(self, p: Provider, state: str, reason: str, retry_at: float = 0.0) -> None:
        st = self.status[p.spec.id]
        st.state, st.reason, st.retry_at = state, reason, retry_at
        self._emit("provider.status", provider=p.spec.id, state=state, reason=reason, retry_at=retry_at or None)

    # ---- main entry ----
    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        *,
        role: str = "fix",
        max_tokens: int = 4096,
        temperature: float = 0.2,
        prefer: list[str] | None = None,
        agent: str = "agent",
    ) -> ChatResult:
        att = _Attempt()
        while True:
            wait = 0.0
            with self._lock:
                if self.max_requests is not None and self.requests >= self.max_requests:
                    raise RequestBudgetExceeded(f"request budget reached ({self.requests}/{self.max_requests})")
                now = self._clock()
                provider = next(
                    (p for p in self._ordered(prefer, role) if p.spec.id not in att.skip and self._usable(p, now)),
                    None,
                )
                if provider is None:
                    if att.skip:
                        raise NoProviderAvailable(
                            f"no provider could take this request ({att.reason or 'all skipped'})"
                        )
                    waits = [s.retry_at - now for s in self.status.values() if s.state == "rate_limited"]
                    waits = [w for w in waits if w > 0]
                    if not waits or min(waits) > 90:
                        reasons = "; ".join(f"{pid}: {s.state} {s.reason}".strip() for pid, s in self.status.items())
                        raise NoProviderAvailable(reasons or "no providers configured")
                    wait = min(waits)
                else:
                    spec, st = provider.spec, self.status[provider.spec.id]
                    models = models_for(spec, role)
                    idx = st.model_index.get(role, 0)
                    if idx >= len(models):
                        self._mark(provider, "no_model", f"no working model for role '{role}'")
                        continue
                    model = models[idx]
                    previous = self._current.get(agent)
                    if previous and previous != spec.id:
                        self._emit("provider.switched", agent=agent, previous=previous, to=spec.id, reason=att.reason)
                    self._current[agent] = spec.id
                    # reserve a pacing slot so concurrent agents together stay under the provider's rpm
                    slot = max(now, st.next_slot)
                    st.next_slot = slot + (60.0 / spec.rpm if spec.rpm else 0.0)
                    self.requests += 1
                    st.requests += 1
                    self.by_agent[agent]["requests"] += 1
                    n = self.requests
            if provider is None:
                self._emit("router.waiting", seconds=round(wait))
                self._sleep(wait)
                continue

            if slot > now:
                self._sleep(slot - now)
            self._emit("llm.request", agent=agent, provider=spec.id, model=model, role=role, n=n)
            try:
                msg = provider.complete(model, messages, tools, max_tokens, temperature)
            except ProviderError as err:
                with self._lock:
                    if err.kind in ("rate", "quota", "too_large"):
                        # rejected before any model ran: don't charge it to the request budget
                        self.requests -= 1
                        st.requests -= 1
                        self.by_agent[agent]["requests"] -= 1
                    att.reason, pause = self._handle(provider, role, err, att)
                if pause:
                    self._emit("router.waiting", seconds=round(pause), provider=spec.id)
                    self._sleep(pause)
                continue

            with self._lock:
                for k in ("input", "output"):
                    self.tokens[k] += msg.usage.get(k, 0)
                    self.by_agent[agent][k] += msg.usage.get(k, 0)
            self._emit(
                "llm.response",
                agent=agent,
                provider=spec.id,
                model=model,
                usage=msg.usage,
                tool_calls=len(msg.tool_calls),
            )
            return ChatResult(msg, spec.id, model)

    def _handle(self, p: Provider, role: str, err: ProviderError, att: _Attempt) -> tuple[str, float]:
        """Update provider state for an error. Returns (reason, seconds to wait before retrying)."""
        now = self._clock()
        pid = p.spec.id
        st = self.status[pid]
        if err.kind == "too_large":
            att.skip.add(pid)
            self._emit("router.skipped", provider=pid, reason="request too large for this provider")
            return f"{pid} can't take a request this large", 0.0
        if err.kind == "auth":
            self._mark(p, "invalid_key", "key rejected; rotate it")
        elif err.kind == "credits":
            self._mark(p, "out_of_credits", "no credits left")
        elif err.kind == "quota":
            self._mark(p, "quota_exhausted", "daily quota reached", _next_utc_midnight(now))
        elif err.kind == "rate":
            att.rate[pid] += 1
            if err.retry_after is None and att.rate[pid] == 1:
                # no retry-after (common for OpenRouter's upstream free models): often a brief blip
                return "rate limited", UNKNOWN_RATE_WAIT
            wait = err.retry_after or 60.0
            if wait <= SHORT_WAIT:
                return "rate limited", wait
            self._mark(p, "rate_limited", "rate limited", now + wait)
        elif err.kind in ("flaky", "empty"):
            att.flaky[pid] += 1
            if att.flaky[pid] <= FLAKY_RETRIES:
                self._emit("router.retry", provider=pid, reason=str(err)[:200])
                return "malformed reply, retrying", 0.0
            att.skip.add(pid)  # this model keeps fumbling this request; let another provider try
            self._emit("router.skipped", provider=pid, reason=f"repeated malformed replies: {str(err)[:150]}")
            return f"{pid} kept producing malformed replies", 0.0
        elif err.kind == "model":
            st.model_index[role] = st.model_index.get(role, 0) + 1
            self._emit("router.model_skipped", provider=pid, role=role, reason=str(err))
            return str(err), 0.0
        elif err.kind == "server":
            att.server[pid] += 1
            if att.server[pid] <= SERVER_RETRIES:
                return "provider error, retrying", 2.0 * att.server[pid]
            self._mark(p, "rate_limited", "provider unreachable", now + 60)
        else:  # bad_request: most likely our own request is malformed; don't hide it behind failover
            raise err
        return st.reason or str(err), 0.0

    def summary(self) -> dict[str, Any]:
        return {
            "requests": self.requests,
            "tokens": dict(self.tokens),
            "agents": {k: dict(v) for k, v in self.by_agent.items()},
            "providers": {
                pid: {"state": s.state, "reason": s.reason, "requests": s.requests} for pid, s in self.status.items()
            },
        }
