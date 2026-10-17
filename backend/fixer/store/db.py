"""SQLite store shared by the CLI and the API server (~/.fixer/fixer.db, mode 0600).

Holds jobs, per-day usage, persisted provider status and the encrypted key vault. Several processes may
use it at once (a CLI run while the API serves the dashboard), so it runs in WAL mode.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from fixer.config import fixer_home

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    repo TEXT NOT NULL,
    issue_number INTEGER NOT NULL DEFAULT 0,
    issue_title TEXT NOT NULL DEFAULT '',
    issue_url TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    phase TEXT NOT NULL DEFAULT 'intake',
    phases TEXT NOT NULL DEFAULT '{}',
    provider TEXT NOT NULL DEFAULT '',
    requests INTEGER NOT NULL DEFAULT 0,
    request_budget INTEGER NOT NULL DEFAULT 0,
    started_at REAL NOT NULL,
    finished_at REAL,
    pr_url TEXT,
    reason TEXT,
    switches TEXT NOT NULL DEFAULT '[]',
    tests TEXT NOT NULL DEFAULT '{}',
    job_dir TEXT NOT NULL DEFAULT '',
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS jobs_updated ON jobs(updated_at);

CREATE TABLE IF NOT EXISTS usage (
    provider TEXT NOT NULL,
    day TEXT NOT NULL,              -- UTC date, matches free-tier reset times
    requests INTEGER NOT NULL DEFAULT 0,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (provider, day)
);

CREATE TABLE IF NOT EXISTS provider_status (
    provider TEXT PRIMARY KEY,
    state TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    retry_at REAL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS providers (           -- vault: provider settings (no secrets)
    id TEXT PRIMARY KEY,
    preset TEXT NOT NULL,
    label TEXT NOT NULL,
    base_url TEXT,
    models TEXT NOT NULL DEFAULT '{}',
    enabled INTEGER NOT NULL DEFAULT 1,
    priority INTEGER NOT NULL,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS credentials (         -- vault: AES-256-GCM ciphertext only
    name TEXT PRIMARY KEY,                       -- provider id, or 'github'
    nonce BLOB NOT NULL,
    ciphertext BLOB NOT NULL,
    key_hint TEXT NOT NULL,
    created_at REAL NOT NULL,
    checked_at REAL
);
"""


class Database:
    def __init__(self, path: Path | None = None):
        self.path = path or fixer_home() / "fixer.db"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        new = not self.path.exists()
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False, timeout=10, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        if new:
            os.chmod(self.path, 0o600)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=10000")
        self._conn.executescript(SCHEMA)

    def execute(self, sql: str, params: tuple | dict = ()) -> sqlite3.Cursor:
        with self._lock:
            return self._conn.execute(sql, params)

    def query(self, sql: str, params: tuple | dict = ()) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(r) for r in self._conn.execute(sql, params).fetchall()]

    def one(self, sql: str, params: tuple | dict = ()) -> dict[str, Any] | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def transaction(self):
        return _Tx(self)

    # ---- meta ----
    def get_meta(self, key: str) -> str | None:
        row = self.one("SELECT value FROM meta WHERE key = ?", (key,))
        return row["value"] if row else None

    def set_meta(self, key: str, value: str) -> None:
        self.execute(
            "INSERT INTO meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )

    def close(self) -> None:
        with self._lock:
            self._conn.close()


class _Tx:
    def __init__(self, db: Database):
        self.db = db

    def __enter__(self) -> Database:
        self.db._lock.acquire()
        self.db._conn.execute("BEGIN IMMEDIATE")
        return self.db

    def __exit__(self, exc_type, *_: Any) -> None:
        try:
            self.db._conn.execute("ROLLBACK" if exc_type else "COMMIT")
        finally:
            self.db._lock.release()


def utc_day(ts: float | None = None) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(ts if ts is not None else time.time()))


def dumps(value: Any) -> str:
    return json.dumps(value, default=str)
