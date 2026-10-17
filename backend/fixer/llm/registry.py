"""Which providers a job uses: vault entries (in the user's order) merged with keys from the environment.

Env keys override vault keys for the same provider (handy for CI), and providers that only exist in the
environment are appended after the vault ones. Persisted provider status (e.g. "OpenRouter's daily quota is
used up until midnight UTC") is applied to every new router, so jobs don't waste requests rediscovering it.
"""

from __future__ import annotations

import dataclasses
import time
from dataclasses import dataclass

from fixer.llm.client import OpenAICompatProvider
from fixer.llm.providers import CATALOG, ProviderSpec, configured, key_for
from fixer.llm.router import LLMRouter
from fixer.store.db import Database
from fixer.vault.vault import Vault, VaultLocked, mask_secret


@dataclass
class ProviderEntry:
    id: str
    preset: str
    label: str
    spec: ProviderSpec  # catalog spec specialised with this entry's id, base URL and models
    key: str | None
    source: str  # vault | env
    enabled: bool
    key_hint: str | None

    @property
    def usable(self) -> bool:
        return self.enabled and (self.key is not None or not self.spec.needs_key)


def _spec_for(pid: str, preset: str, base_url: str | None, models: dict[str, str]) -> ProviderSpec:
    base = CATALOG.get(preset, CATALOG["custom"])
    merged = dict(base.models)
    for role, model in (models or {}).items():
        if model:
            merged[role] = (model, *[m for m in base.models.get(role, ()) if m != model])
    if "fix" in merged:
        for role in ("critic", "summarize", "scout"):
            merged.setdefault(role, merged["fix"])
    return dataclasses.replace(base, id=pid, base_url=base_url or base.base_url, models=merged)


def open_vault(db: Database) -> Vault | None:
    try:
        return Vault.open(db)
    except VaultLocked:
        return None


STORED = "__stored__"  # placeholder when listing without decrypting keys


def load_entries(db: Database | None = None, vault: Vault | None = None, decrypt: bool = True) -> list[ProviderEntry]:
    """decrypt=False lists providers (for the dashboard) without ever decrypting a key."""
    entries: list[ProviderEntry] = []
    if vault is not None:
        for rec in vault.providers():
            spec = _spec_for(rec.id, rec.preset, rec.base_url, rec.models)
            env_key = key_for(CATALOG[rec.preset]) if rec.preset in CATALOG and rec.id == rec.preset else None
            if env_key:
                key = env_key if decrypt else STORED
            elif rec.key_hint:
                key = vault.get_secret(rec.id) if decrypt else STORED
            else:
                key = None
            hint = mask_secret(env_key, spec.key_prefix) + " (env)" if env_key else rec.key_hint
            entries.append(ProviderEntry(rec.id, rec.preset, rec.label, spec, key, "vault", rec.enabled, hint))
    known = {e.preset for e in entries if e.id == e.preset}
    for spec, key in configured():
        if spec.id not in known:
            hint = mask_secret(key, spec.key_prefix) if key else None
            entries.append(
                ProviderEntry(spec.id, spec.id, spec.id, spec, key if decrypt else (key and STORED), "env", True, hint)
            )
    return entries


def build_router(
    entries: list[ProviderEntry],
    *,
    db: Database | None,
    private_repo: bool,
    max_requests: int | None,
    on_event,
    only: str | None = None,
) -> LLMRouter:
    providers = [OpenAICompatProvider(e.spec, e.key) for e in entries if e.usable and (not only or e.id == only)]
    router = LLMRouter(providers, private_repo=private_repo, max_requests=max_requests, on_event=on_event)
    if db is not None:
        apply_persisted_status(router, db)
    return router


def apply_persisted_status(router: LLMRouter, db: Database) -> None:
    now = time.time()
    for row in db.query("SELECT provider, state, reason, retry_at FROM provider_status"):
        st = router.status.get(row["provider"])
        if st is None:
            continue
        if row["state"] in ("rate_limited", "quota_exhausted") and (row["retry_at"] or 0) > now:
            st.state, st.reason, st.retry_at = row["state"], row["reason"], row["retry_at"]
        elif row["state"] in ("invalid_key", "out_of_credits"):
            st.state, st.reason = row["state"], row["reason"]
