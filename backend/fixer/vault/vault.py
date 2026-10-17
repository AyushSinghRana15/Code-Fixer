"""Encrypted key vault (Plan.md §7.2).

- Each secret is encrypted with AES-256-GCM, a fresh 96-bit nonce, and its name as associated data (so a
  ciphertext can't be swapped onto another provider). The database only ever holds ciphertext + a masked hint.
- The 256-bit master key lives in the OS keychain (macOS Keychain, Windows Credential Manager, Secret Service).
- Headless machines: set FIXER_VAULT_PASSPHRASE; the key is derived with scrypt and a random salt.
- A stored check value detects a wrong passphrase / master key instead of returning garbage.
"""

from __future__ import annotations

import base64
import json
import os
import secrets
import time
from dataclasses import dataclass
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from fixer.store.db import Database

KEYCHAIN_SERVICE = "code-fixer"
KEYCHAIN_ACCOUNT = "vault-master-key"
CHECK_PLAINTEXT = b"code-fixer vault v1"


class VaultLocked(Exception):
    """The master key isn't available (no keychain and no passphrase) or doesn't match this vault."""


def mask_secret(secret: str, prefix: str | None = None) -> str:
    """Display hint: known prefix (or first 4 chars) + last 4. Never more."""
    secret = secret.strip()
    head = prefix if prefix and secret.startswith(prefix) else secret[:4]
    return f"{head}…{secret[-4:]}" if len(secret) > 8 else "…"


@dataclass
class ProviderRecord:
    id: str
    preset: str
    label: str
    base_url: str | None
    models: dict[str, str]
    enabled: bool
    priority: int
    key_hint: str | None


class Vault:
    def __init__(self, db: Database, master_key: bytes):
        if len(master_key) != 32:
            raise ValueError("master key must be 32 bytes")
        self.db = db
        self._aead = AESGCM(master_key)
        self._verify()

    # ---- opening ----
    @classmethod
    def open(cls, db: Database) -> Vault:
        passphrase = os.environ.get("FIXER_VAULT_PASSPHRASE")
        if passphrase:
            return cls(db, cls._derive(db, passphrase))
        return cls(db, cls._keychain_key())

    @staticmethod
    def _derive(db: Database, passphrase: str) -> bytes:
        salt_b64 = db.get_meta("vault_salt")
        if salt_b64 is None:
            salt_b64 = base64.b64encode(secrets.token_bytes(16)).decode()
            db.set_meta("vault_salt", salt_b64)
        kdf = Scrypt(salt=base64.b64decode(salt_b64), length=32, n=2**15, r=8, p=1)
        return kdf.derive(passphrase.encode())

    @staticmethod
    def _keychain_key() -> bytes:
        try:
            import keyring
            from keyring.errors import KeyringError

            try:
                stored = keyring.get_password(KEYCHAIN_SERVICE, KEYCHAIN_ACCOUNT)
                if stored is None:
                    stored = base64.b64encode(secrets.token_bytes(32)).decode()
                    keyring.set_password(KEYCHAIN_SERVICE, KEYCHAIN_ACCOUNT, stored)
                return base64.b64decode(stored)
            except KeyringError as err:
                raise VaultLocked(f"OS keychain unavailable ({err}); set FIXER_VAULT_PASSPHRASE instead") from err
        except ImportError as err:  # pragma: no cover - keyring is a dependency
            raise VaultLocked("keyring isn't installed; set FIXER_VAULT_PASSPHRASE") from err

    def _verify(self) -> None:
        stored = self.db.get_meta("vault_check")
        if stored is None:
            nonce = secrets.token_bytes(12)
            ct = self._aead.encrypt(nonce, CHECK_PLAINTEXT, b"check")
            self.db.set_meta("vault_check", base64.b64encode(nonce + ct).decode())
            return
        raw = base64.b64decode(stored)
        try:
            self._aead.decrypt(raw[:12], raw[12:], b"check")
        except InvalidTag as err:
            raise VaultLocked("the master key doesn't match this vault (wrong FIXER_VAULT_PASSPHRASE?)") from err

    # ---- secrets ----
    def put_secret(self, name: str, secret: str, hint: str) -> None:
        nonce = secrets.token_bytes(12)
        ct = self._aead.encrypt(nonce, secret.strip().encode(), name.encode())
        self.db.execute(
            "INSERT INTO credentials(name, nonce, ciphertext, key_hint, created_at) VALUES(?, ?, ?, ?, ?) "
            "ON CONFLICT(name) DO UPDATE SET nonce=excluded.nonce, ciphertext=excluded.ciphertext, "
            "key_hint=excluded.key_hint, created_at=excluded.created_at, checked_at=NULL",
            (name, nonce, ct, hint, time.time()),
        )

    def get_secret(self, name: str) -> str | None:
        row = self.db.one("SELECT nonce, ciphertext FROM credentials WHERE name = ?", (name,))
        if not row:
            return None
        try:
            return self._aead.decrypt(row["nonce"], row["ciphertext"], name.encode()).decode()
        except InvalidTag as err:
            raise VaultLocked(f"couldn't decrypt '{name}': tampered data or wrong master key") from err

    def secret_hint(self, name: str) -> str | None:
        row = self.db.one("SELECT key_hint FROM credentials WHERE name = ?", (name,))
        return row["key_hint"] if row else None

    def delete_secret(self, name: str) -> None:
        self.db.execute("DELETE FROM credentials WHERE name = ?", (name,))

    # ---- providers ----
    def providers(self) -> list[ProviderRecord]:
        rows = self.db.query(
            "SELECT p.*, c.key_hint FROM providers p LEFT JOIN credentials c ON c.name = p.id ORDER BY p.priority"
        )
        return [
            ProviderRecord(
                r["id"],
                r["preset"],
                r["label"],
                r["base_url"],
                json.loads(r["models"] or "{}"),
                bool(r["enabled"]),
                r["priority"],
                r["key_hint"],
            )
            for r in rows
        ]

    def add_provider(
        self,
        preset: str,
        label: str,
        base_url: str | None,
        models: dict[str, str],
        secret: str | None,
        hint: str | None,
    ) -> str:
        with self.db.transaction():
            ids = {r["id"] for r in self.db.query("SELECT id FROM providers")}
            pid, n = preset, 2
            while pid in ids:
                pid, n = f"{preset}-{n}", n + 1
            top = self.db.one("SELECT COALESCE(MAX(priority), -1) AS m FROM providers")["m"]
            self.db.execute(
                "INSERT INTO providers(id, preset, label, base_url, models, enabled, priority, created_at) "
                "VALUES(?, ?, ?, ?, ?, 1, ?, ?)",
                (pid, preset, label or pid, base_url, json.dumps(models), top + 1, time.time()),
            )
        if secret:
            self.put_secret(pid, secret, hint or mask_secret(secret))
        return pid

    def set_enabled(self, pid: str, enabled: bool) -> None:
        self._require(pid)
        self.db.execute("UPDATE providers SET enabled = ? WHERE id = ?", (int(enabled), pid))

    def update(self, pid: str, **fields: Any) -> None:
        self._require(pid)
        allowed = {"label", "base_url", "models"}
        for key, value in fields.items():
            if key in allowed and value is not None:
                self.db.execute(
                    f"UPDATE providers SET {key} = ? WHERE id = ?",
                    (json.dumps(value) if key == "models" else value, pid),
                )

    def reorder(self, ids: list[str]) -> None:
        current = [p.id for p in self.providers()]
        if sorted(ids) != sorted(current):
            raise ValueError("the new order must list every provider exactly once")
        with self.db.transaction():
            for i, pid in enumerate(ids):
                self.db.execute("UPDATE providers SET priority = ? WHERE id = ?", (i, pid))

    def remove_provider(self, pid: str) -> None:
        self._require(pid)
        with self.db.transaction():
            self.db.execute("DELETE FROM providers WHERE id = ?", (pid,))
            self.db.execute("DELETE FROM credentials WHERE name = ?", (pid,))
            self.db.execute("DELETE FROM provider_status WHERE provider = ?", (pid,))

    def _require(self, pid: str) -> None:
        if not self.db.one("SELECT 1 AS x FROM providers WHERE id = ?", (pid,)):
            raise KeyError(f"no provider '{pid}' in the vault")
