"""Phase 02 backend: vault, provider registry, job recorder and the API the dashboard uses."""

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fixer.api.app import create_app
from fixer.config import Budget
from fixer.events import EventBus
from fixer.github.client import GitHubError
from fixer.llm.check import CheckResult
from fixer.llm.registry import apply_persisted_status, build_router, load_entries
from fixer.llm.router import LLMRouter
from fixer.orchestrator.pipeline import Job, JobConfig
from fixer.store.db import Database
from fixer.store.recorder import JobRecorder
from fixer.vault.vault import Vault, VaultLocked
from tests.fakes import AgentBrain
from tests.test_orchestration import CART, SCRIPTS

OR_KEY = "sk-or-v1-0123456789abcdef0123456789abcdef"


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("FIXER_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("FIXER_VAULT_PASSPHRASE", "test passphrase")
    for name in (
        "FIXER_OPENROUTER_API_KEY",
        "OPENROUTER_API_KEY",
        "FIXER_GROQ_API_KEY",
        "GROQ_API_KEY",
        "FIXER_GITHUB_TOKEN",
        "GITHUB_TOKEN",
        "GH_TOKEN",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr("fixer.github.client.shutil.which", lambda _: None)  # don't pick up a real `gh` login
    monkeypatch.setattr("fixer.api.app.load_env", lambda: None)  # never load the developer's real backend/.env
    db = Database(tmp_path / "home" / "fixer.db")
    return db


def ok_checker(spec, key):
    return CheckResult(True, 120, True, "Key valid · m answered in 120 ms · tool calling works", "ok", "m")


def auth_checker(spec, key):
    return CheckResult(False, 90, False, "The key was rejected (401/403).", "auth")


class FakeGitHub:
    def __init__(self, token):
        self.token = token

    def token_info(self):
        if self.token == "ghp_bad0000000000000000":
            raise GitHubError("Bad credentials", 401)
        return "demo", ["repo", "workflow"]


def client(db, checker=ok_checker, origin="http://localhost:3000"):
    app = create_app(db, checker=checker, github_factory=FakeGitHub)
    return TestClient(app, base_url="http://localhost", headers={"Origin": origin})


# ---- vault ----


def test_vault_encrypts_and_binds_ciphertext_to_its_name(env):
    v = Vault.open(env)
    pid = v.add_provider("openrouter", "openrouter", None, {}, OR_KEY, "sk-or-…cdef")
    assert v.get_secret(pid) == OR_KEY
    assert OR_KEY.encode() not in Path(env.path).read_bytes()  # only ciphertext on disk
    v.put_secret("other", "x" * 20, "hint")
    a = env.one("SELECT nonce, ciphertext FROM credentials WHERE name = ?", (pid,))
    env.execute("UPDATE credentials SET nonce = ?, ciphertext = ? WHERE name = 'other'", (a["nonce"], a["ciphertext"]))
    with pytest.raises(VaultLocked):  # swapping a ciphertext onto another name is detected
        v.get_secret("other")


def test_wrong_passphrase_is_rejected(env, monkeypatch):
    Vault.open(env)
    monkeypatch.setenv("FIXER_VAULT_PASSPHRASE", "wrong")
    with pytest.raises(VaultLocked):
        Vault.open(env)


# ---- registry ----


def test_registry_merges_vault_and_env_and_restores_status(env, monkeypatch):
    v = Vault.open(env)
    v.add_provider("openrouter", "OpenRouter", None, {}, OR_KEY, "sk-or-…cdef")
    monkeypatch.setenv("FIXER_GROQ_API_KEY", "gsk_" + "a" * 40)
    entries = load_entries(env, v)
    assert [(e.id, e.source) for e in entries] == [("openrouter", "vault"), ("groq", "env")]
    assert entries[0].key == OR_KEY
    assert load_entries(env, v, decrypt=False)[0].key != OR_KEY  # listing never decrypts

    env.execute(
        "INSERT INTO provider_status VALUES ('openrouter', 'quota_exhausted', 'daily quota', ?, ?)",
        (time.time() + 3600, time.time()),
    )
    router = build_router(entries, db=env, private_repo=True, max_requests=10, on_event=None)
    assert router.status["openrouter"].state == "quota_exhausted"  # carried over from an earlier run


# ---- recorder ----


def run_recorded_job(db):
    brain = AgentBrain(SCRIPTS)
    cfg = JobConfig(
        repo=CART, issue=(CART / "ISSUE.md").read_text(), budget=Budget(max_requests=30), scouts="never", candidates=1
    )
    bus = EventBus(JobRecorder(db, cfg.job_id))
    router = LLMRouter([brain.provider("p1")], max_requests=30, on_event=lambda type, **d: bus.emit(type, **d))
    apply_persisted_status(router, db)
    return Job(cfg, router, bus).run()


def test_recorder_writes_the_job_and_usage(env):
    result = run_recorded_job(env)
    row = env.one("SELECT * FROM jobs WHERE id = ?", (result.job_id,))
    assert row["status"] == "fixed" and row["requests"] == 5 and row["repo"] == "py_cart"
    assert env.one("SELECT SUM(requests) AS n FROM usage")["n"] == 5


# ---- API ----


def test_jobs_and_stats_match_the_dashboard_types(env):
    result = run_recorded_job(env)
    c = client(env)
    jobs = c.get("/api/jobs").json()
    j = jobs[0]
    assert j["id"] == result.job_id and j["status"] == "fixed"
    assert set(j) >= {
        "id",
        "repo",
        "issueNumber",
        "issueTitle",
        "issueUrl",
        "status",
        "phase",
        "phases",
        "provider",
        "requests",
        "requestBudget",
        "startedAt",
        "switches",
        "trajectoryPath",
    }
    assert j["phases"]["fix"] == "done" and j["tests"]["repro"] == "passing" and j["tests"]["final"]["failed"] == 0
    stats = c.get("/api/stats/summary").json()
    assert stats["jobsToday"] == 1 and stats["successRate7d"] == 1.0
    assert c.get(f"/api/jobs/{result.job_id}").json()["id"] == result.job_id


def test_provider_keys_are_write_only(env):
    c = client(env)
    r = c.post("/api/providers", json={"preset": "openrouter", "apiKey": OR_KEY})
    assert r.status_code == 200
    assert OR_KEY not in r.text  # the full key never comes back out
    p = r.json()[0]
    assert p["id"] == "openrouter" and p["keyHint"] == "sk-or-…cdef" and p["source"] == "vault"
    assert Vault.open(env).get_secret("openrouter") == OR_KEY


def test_rejected_key_is_not_saved(env):
    c = client(env, checker=auth_checker)
    r = c.post("/api/providers", json={"preset": "openrouter", "apiKey": OR_KEY})
    assert r.status_code == 400 and "rejected" in r.json()["detail"]
    assert c.get("/api/providers").json() == []
    bad_prefix = client(env).post("/api/providers", json={"preset": "openrouter", "apiKey": "nope-123456789"})
    assert bad_prefix.status_code == 400


def test_provider_management(env, monkeypatch):
    c = client(env)
    c.post("/api/providers", json={"preset": "openrouter", "apiKey": OR_KEY})
    c.post("/api/providers", json={"preset": "groq", "apiKey": "gsk_" + "b" * 40})
    assert [p["id"] for p in c.put("/api/providers/order", json=["groq", "openrouter"]).json()] == [
        "groq",
        "openrouter",
    ]
    assert c.patch("/api/providers/groq", json={"enabled": False}).json()[0]["state"] == "disabled"
    assert c.post("/api/providers/openrouter/test").json()["ok"] is True
    rotated = c.put("/api/providers/openrouter/key", json={"apiKey": "sk-or-v1-" + "f" * 32 + "9999"}).json()
    assert next(p for p in rotated if p["id"] == "openrouter")["keyHint"].endswith("9999")
    assert [p["id"] for p in c.delete("/api/providers/groq").json()] == ["openrouter"]

    monkeypatch.setenv("FIXER_GROQ_API_KEY", "gsk_" + "c" * 40)  # env-sourced providers are read-only here
    assert client(env).delete("/api/providers/groq").status_code == 409


def test_test_button_marks_rejected_keys(env):
    client(env).post("/api/providers", json={"preset": "openrouter", "apiKey": OR_KEY})
    c = client(env, checker=auth_checker)
    assert c.post("/api/providers/openrouter/test").json()["ok"] is False
    assert c.get("/api/providers").json()[0]["state"] == "invalid_key"


def test_github_credential(env):
    c = client(env)
    assert c.get("/api/credentials/github").json()["state"] == "missing"
    assert c.put("/api/credentials/github", json={"token": "ghp_bad0000000000000000"}).status_code == 400
    g = c.put("/api/credentials/github", json={"token": "ghp_good000000000000000"}).json()
    assert g["state"] == "valid" and g["login"] == "demo" and "repo" in g["scopes"]
    assert "ghp_good000000000000000" not in str(g)
    assert c.delete("/api/credentials/github").json()["state"] == "missing"


def test_local_only_protections(env):
    app = create_app(env, checker=ok_checker, github_factory=FakeGitHub)
    evil_host = TestClient(app, base_url="http://evil.example")
    assert evil_host.get("/api/jobs").status_code == 403  # DNS rebinding
    evil_origin = client(env, origin="https://evil.example")
    assert evil_origin.get("/api/jobs").status_code == 200  # reads are fine
    assert evil_origin.post("/api/providers", json={"preset": "groq", "apiKey": "gsk_x"}).status_code == 403
