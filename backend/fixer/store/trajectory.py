"""Trajectory log: every event of a job as JSON lines, with secrets redacted (Plan.md §7.2)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fixer.events import Event


class TrajectoryLog:
    def __init__(self, path: Path, secrets: list[str]):
        self.path = path
        self._secrets = [s for s in secrets if s and len(s) >= 8]
        path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = path.open("a", encoding="utf-8")

    def _redact(self, text: str) -> str:
        for s in self._secrets:
            text = text.replace(s, "[REDACTED]")
        return text

    def __call__(self, event: Event) -> None:
        line = json.dumps({"type": event.type, "at": round(event.at, 3), **_jsonable(event.data)}, default=str)
        self._fh.write(self._redact(line) + "\n")
        self._fh.flush()

    def close(self) -> None:
        self._fh.close()


def _jsonable(data: dict[str, Any]) -> dict[str, Any]:
    return {k.rstrip("_"): v for k, v in data.items()}
