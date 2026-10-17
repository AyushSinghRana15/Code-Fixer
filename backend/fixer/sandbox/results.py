"""Structured test results from JUnit XML (pytest, Maven, Gradle, Vitest), with a raw-output fallback."""

from __future__ import annotations

import hashlib
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class TestFailure:
    id: str
    kind: str  # failure | error
    message: str
    detail: str = ""


@dataclass
class TestReport:
    exit_code: int
    passed: int = 0
    failed: int = 0
    errors: int = 0
    skipped: int = 0
    failures: list[TestFailure] = field(default_factory=list)
    output_tail: str = ""
    structured: bool = False  # parsed from JUnit XML
    timed_out: bool = False

    @property
    def total(self) -> int:
        return self.passed + self.failed + self.errors + self.skipped

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and self.failed == 0 and self.errors == 0

    @property
    def failing_ids(self) -> set[str]:
        return {f.id for f in self.failures}

    def signature(self) -> str:
        """Fingerprint of *how* it fails, for stuck detection."""
        if self.ok:
            return "ok"
        parts = sorted(f"{f.id}|{f.message.splitlines()[0][:120] if f.message else ''}" for f in self.failures)
        if not parts:
            parts = [self.output_tail[-300:]]
        return hashlib.sha1("\n".join(parts).encode()).hexdigest()[:12]

    def summary(self, max_failures: int = 5, detail_chars: int = 1500) -> str:
        """Compact text for the model: counts, then the first few failures."""
        if self.timed_out:
            head = "Tests TIMED OUT."
        elif self.structured:
            head = (
                f"{self.passed} passed, {self.failed} failed, {self.errors} errors, {self.skipped} skipped "
                f"(exit code {self.exit_code})."
            )
        else:
            head = f"Exit code {self.exit_code} ({'passed' if self.exit_code == 0 else 'failed'})."
        lines = [head]
        for f in self.failures[:max_failures]:
            lines.append(f"\n--- {f.kind.upper()}: {f.id}\n{f.message}\n{_trim(f.detail, detail_chars)}".rstrip())
        if len(self.failures) > max_failures:
            lines.append(f"\n(+{len(self.failures) - max_failures} more failing tests)")
        if not self.structured or (not self.ok and not self.failures):
            lines.append("\n--- output (tail) ---\n" + _trim(self.output_tail, 2500, keep="tail"))
        return "\n".join(lines)


def _trim(text: str, limit: int, keep: str = "both") -> str:
    text = text or ""
    if len(text) <= limit:
        return text
    if keep == "tail":
        return "…" + text[-limit:]
    half = limit // 2
    return text[:half] + f"\n… [{len(text) - limit} chars trimmed] …\n" + text[-half:]


def _case_id(cls: str, name: str, file: str | None) -> str:
    """A selector the agent can pass straight back to run_tests."""
    if file and file.endswith(".py"):  # pytest with junit_family=xunit1 -> node id
        module = file[:-3].replace("/", ".")
        if cls.startswith(module + "."):
            return f"{file}::{cls[len(module) + 1 :].replace('.', '::')}::{name}"
        return f"{file}::{name}"
    if cls and cls.split(".")[-1][:1].isupper():  # JUnit (Java): com.acme.CartTest#name
        return f"{cls}#{name}"
    return f"{cls}::{name}" if cls else name


def parse_junit(paths: list[Path], exit_code: int, output: str) -> TestReport:
    report = TestReport(exit_code=exit_code, output_tail=output[-6000:])
    found = False
    for path in paths:
        try:
            root = ET.parse(path).getroot()
        except (ET.ParseError, OSError):
            continue
        found = True
        for case in root.iter("testcase"):
            case_id = _case_id(case.get("classname", ""), case.get("name", ""), case.get("file"))
            failure, error, skipped = case.find("failure"), case.find("error"), case.find("skipped")
            if failure is not None or error is not None:
                node = failure if failure is not None else error
                kind = "failure" if failure is not None else "error"
                report.failures.append(
                    TestFailure(case_id, kind, (node.get("message") or "").strip()[:500], (node.text or "").strip())
                )
                if kind == "failure":
                    report.failed += 1
                else:
                    report.errors += 1
            elif skipped is not None:
                report.skipped += 1
            else:
                report.passed += 1
    report.structured = found
    if not found and exit_code != 0:
        report.failures.append(TestFailure("(run)", "error", "test command failed", _trim(output, 4000, keep="tail")))
        report.errors = 1
    elif found and exit_code not in (0, 1) and report.failed == 0 and report.errors == 0:
        # e.g. pytest exit 2 (collection/usage error) or 5 (no tests collected)
        report.failures.append(
            TestFailure(
                "(collection)", "error", f"test run ended with exit code {exit_code}", _trim(output, 4000, keep="tail")
            )
        )
        report.errors += 1
    return report
