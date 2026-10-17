"""Test-tampering guard (Plan.md §8): an agent must not make tests pass by weakening them."""

from __future__ import annotations

import re

from fixer.sandbox.detect import EnvSpec

REMOVED_RX = re.compile(
    r"\bassert\b|assert[A-Z]\w*\(|expect\(|\.should\b|@Test\b|^\s*def test_|^\s*(it|test)\(", re.MULTILINE
)
ADDED_RX = re.compile(
    r"pytest\.mark\.(skip|xfail)|pytest\.(skip|xfail)\(|unittest\.skip|\b(it|test|describe)\.(skip|todo)\(|"
    r"\bx(it|describe|test)\(|@Disabled\b|@Ignore\b|assert\s+True\b|expect\(true\)"
)


def check_diff(diff: str, spec: EnvSpec, baseline_files: set[str], changed: list[tuple[str, str]]) -> list[str]:
    """Return human-readable problems; an empty list means the diff looks honest."""
    issues: list[str] = []
    for status, path in changed:
        if status == "D" and spec.is_test_path(path):
            issues.append(f"deleted test file {path}")

    current = None
    for line in diff.splitlines():
        if line.startswith("+++ "):
            current = line[6:] if line.startswith("+++ b/") else None
            continue
        if not current or not spec.is_test_path(current) or line.startswith("---"):
            continue
        existing = current in baseline_files
        if line.startswith("-") and existing and REMOVED_RX.search(line[1:]):
            issues.append(f"removed an assertion or test from {current}: {line[1:].strip()[:100]}")
        elif line.startswith("+") and ADDED_RX.search(line[1:]):
            issues.append(f"skipped or neutralised a test in {current}: {line[1:].strip()[:100]}")
    return issues
