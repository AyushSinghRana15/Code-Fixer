"""The agent's tools (Plan.md §5). Few and simple: free models handle small toolsets more reliably.

Every path goes through Workspace.resolve, so tools can't reach outside the repo copy.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import re
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from fixer.sandbox.base import Sandbox
from fixer.sandbox.results import TestReport
from fixer.sandbox.workspace import HIDDEN, PathError, Workspace

MAX_READ_LINES = 250
MAX_OUTPUT = 8000


class ToolError(Exception):
    pass


REQUIRED: dict[str, list[str]] = {}


def _fn(
    name: str, description: str, properties: dict[str, Any], required: list[str], register: bool = True
) -> dict[str, Any]:
    """Tool schema. Deliberately loose: no JSON-schema `required` or `additionalProperties`, because some
    providers (e.g. Groq) validate calls server-side and reject the whole reply on any mismatch. The
    harness checks arguments itself (normalize_args) and returns an error the model can correct."""
    if register:  # phase-specific `finish` tools share a name; their checks live in validate_finish
        REQUIRED[name] = required
    if required:
        description += " Required: " + ", ".join(required) + "."
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": properties},
        },
    }


# Argument names models commonly use instead of ours (often habits from their training tools).
ALIASES: dict[str, dict[str, str]] = {
    "*": {
        "file": "path",
        "file_path": "path",
        "filepath": "path",
        "filename": "path",
        "dir": "path",
        "directory": "path",
    },
    "read_file": {"start": "start_line", "end": "end_line", "line_start": "start_line", "line_end": "end_line"},
    "search": {"query": "pattern", "regex": "pattern", "q": "pattern", "include": "glob", "file_pattern": "glob"},
    "edit_file": {
        "old": "old_text",
        "old_str": "old_text",
        "old_string": "old_text",
        "search": "old_text",
        "find": "old_text",
        "new": "new_text",
        "new_str": "new_text",
        "new_string": "new_text",
        "replace": "new_text",
        "replacement": "new_text",
    },
    "create_file": {"text": "content", "contents": "content", "file_text": "content", "body": "content"},
    "run_tests": {"test": "selector", "test_id": "selector", "tests": "selector", "target": "selector"},
    "finish": {"test": "test_id", "selector": "test_id", "test_name": "test_id", "message": "summary"},
    "give_up": {"message": "reason", "explanation": "reason"},
}


def normalize_args(name: str, args: dict[str, Any], allowed: set[str] | None = None) -> dict[str, Any]:
    """Map alias names to ours, drop unknown ones, and check required arguments."""
    aliases = {**ALIASES["*"], **ALIASES.get(name, {})}
    out: dict[str, Any] = {}
    for key, value in args.items():
        key = aliases.get(key, key)
        if allowed is None or key in allowed:
            out.setdefault(key, value)
    missing = [r for r in REQUIRED.get(name, []) if out.get(r) in (None, "")]
    if missing:
        raise ToolError(f"{name} needs: {', '.join(missing)}. You passed: {', '.join(args) or 'nothing'}.")
    return out


S = {"type": "string"}
I = {"type": "integer"}  # noqa: E741

TOOL_SPECS: dict[str, dict[str, Any]] = {
    "read_file": _fn(
        "read_file",
        "Read a file. Each line starts with its line number and a TAB; that prefix is NOT part of the file, "
        "so leave it out when you copy text into edit_file. Use start_line/end_line for large files.",
        {"path": S, "start_line": I, "end_line": I},
        ["path"],
    ),
    "list_dir": _fn("list_dir", "List files and folders (two levels deep).", {"path": S}, []),
    "search": _fn(
        "search",
        "Search file contents with a regular expression (ripgrep). Returns path:line: text.",
        {"pattern": S, "path": S, "glob": {"type": "string", "description": "e.g. *.py"}},
        ["pattern"],
    ),
    "edit_file": _fn(
        "edit_file",
        "Replace one exact occurrence of old_text with new_text. old_text must match the "
        "file exactly (including indentation) and be unique; include surrounding lines if needed.",
        {"path": S, "old_text": S, "new_text": S},
        ["path", "old_text", "new_text"],
    ),
    "create_file": _fn(
        "create_file",
        "Create a new file. Fails if it already exists (use edit_file instead).",
        {"path": S, "content": S},
        ["path", "content"],
    ),
    "run_tests": _fn(
        "run_tests",
        "Run tests and get a summary. Pass a selector to run one test or file; omit it to run the whole suite.",
        {"selector": S},
        [],
    ),
    "git_diff": _fn("git_diff", "Show all changes made so far, as a unified diff.", {}, []),
    "give_up": _fn(
        "give_up", "Stop because the task can't be done. Explain why and what you found.", {"reason": S}, ["reason"]
    ),
}

FINISH_REPRODUCE = _fn(
    "finish",
    "Call when a test exists that fails because of the bug. The harness re-runs it to check.",
    {
        "test_id": {"type": "string", "description": "selector for the new failing test"},
        "explanation": {"type": "string", "description": "why this test captures the bug"},
    },
    ["test_id", "explanation"],
    register=False,
)
FINISH_SCOUT = _fn(
    "finish",
    "Call with your brief when you've answered the question.",
    {"brief": {"type": "string", "description": "file paths, line numbers, key code, conclusions (≤250 words)"}},
    ["brief"],
    register=False,
)
FINISH_FIX = _fn(
    "finish",
    "Call when the reproduction test passes. The harness re-runs it, then the full suite.",
    {"summary": {"type": "string", "description": "root cause and what you changed"}},
    ["summary"],
    register=False,
)


@dataclass
class Policy:
    """Which files the agent may write in the current phase. Returns a reason string when denied."""

    name: str
    can_write: Callable[[str, bool], str | None]  # (repo-relative path, exists) -> denial reason | None


@dataclass
class Toolbox:
    ws: Workspace
    sandbox: Sandbox
    policy: Policy
    emit: Callable[..., None] = lambda *a, **k: None
    reports: list[TestReport] = field(default_factory=list)
    _reads: dict[tuple[str, int, int], tuple[str, int]] = field(default_factory=dict)  # range -> (digest, call no.)
    _calls: int = 0

    def specs(self, names: list[str], finish: dict[str, Any]) -> list[dict[str, Any]]:
        return [TOOL_SPECS[n] for n in names] + [finish]

    def execute(self, name: str, args: dict[str, Any]) -> str:
        handler = getattr(self, f"_t_{name}", None)
        self._calls += 1
        if handler is None:
            raise ToolError(f"unknown tool '{name}'")
        allowed = set(TOOL_SPECS[name]["function"]["parameters"]["properties"])
        args = normalize_args(name, args, allowed)
        for key in ("start_line", "end_line"):  # some models send numbers as strings
            if isinstance(args.get(key), str) and args[key].strip().isdigit():
                args[key] = int(args[key])
        try:
            return handler(**args)
        except TypeError as err:  # wrong/missing arguments from the model
            raise ToolError(f"bad arguments for {name}: {err}") from err
        except PathError as err:
            raise ToolError(str(err)) from err

    # ---- tools ----
    def _t_read_file(self, path: str, start_line: int | None = None, end_line: int | None = None) -> str:
        p = self.ws.resolve(path)
        if not p.is_file():
            raise ToolError(f"'{path}' is not a file")
        raw = p.read_bytes()
        if b"\0" in raw[:4096]:
            raise ToolError(f"'{path}' looks like a binary file")
        lines = raw.decode("utf-8", errors="replace").splitlines()
        start = max(1, int(start_line or 1))
        end = min(len(lines), int(end_line or start + MAX_READ_LINES - 1), start + MAX_READ_LINES - 1)
        # Re-reading an unchanged range that's still in context wastes requests; weak models loop on it.
        key, digest = (self.ws.rel(p), start, end), hashlib.sha1(raw).hexdigest()
        seen = self._reads.get(key)
        self._reads[key] = (digest, self._calls)
        if seen and seen[0] == digest and self._calls - seen[1] <= 5:
            return (
                f"You read {key[0]} (lines {start}-{end}) {self._calls - seen[1]} tool call(s) ago and it "
                "hasn't changed. Use that content and take the next step instead of reading it again."
            )
        body = "\n".join(f"{i}\t{lines[i - 1]}" for i in range(start, end + 1))
        note = f"\n[lines {start}-{end} of {len(lines)}]" if (start > 1 or end < len(lines)) else ""
        return (body or "(empty file)") + note

    def _t_list_dir(self, path: str = ".") -> str:
        root = self.ws.resolve(path)
        if not root.is_dir():
            raise ToolError(f"'{path}' is not a directory")
        out: list[str] = []

        def walk(d, depth: int) -> None:
            for child in sorted(d.iterdir(), key=lambda c: (c.is_file(), c.name)):
                if child.name in HIDDEN or child.name in {"__pycache__", ".pytest_cache", "node_modules"}:
                    continue
                rel = self.ws.rel(child)
                out.append(rel + ("/" if child.is_dir() else ""))
                if child.is_dir() and depth < 2:
                    walk(child, depth + 1)
                if len(out) >= 300:
                    return

        walk(root, 1)
        return "\n".join(out[:300]) + ("\n[truncated]" if len(out) >= 300 else "")

    def _t_search(self, pattern: str, path: str = ".", glob: str | None = None) -> str:
        target = self.ws.resolve(path)
        if shutil.which("rg"):
            cmd = [
                "rg",
                "--line-number",
                "--no-heading",
                "--color",
                "never",
                "--smart-case",
                "--max-columns",
                "200",
                "--max-count",
                "20",
            ]
            for hidden in HIDDEN:
                cmd += ["-g", f"!{hidden}"]
            if glob:
                cmd += ["-g", glob]
            cmd += ["-e", pattern, str(target)]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if res.returncode == 2:
                raise ToolError(f"search failed: {res.stderr.strip()[:300]}")
            lines = [ln.replace(str(self.ws.root.resolve()) + "/", "") for ln in res.stdout.splitlines()]
        else:  # small pure-Python fallback
            rx = re.compile(pattern)
            lines = []
            for f in target.rglob(glob or "*"):
                if f.is_file() and not any(h in f.parts for h in HIDDEN):
                    for n, line in enumerate(f.read_text(errors="ignore").splitlines(), 1):
                        if rx.search(line):
                            lines.append(f"{self.ws.rel(f)}:{n}:{line[:200]}")
        if not lines:
            return "No matches."
        return "\n".join(lines[:80]) + (f"\n[{len(lines) - 80} more matches]" if len(lines) > 80 else "")

    def _check_write(self, path: str) -> tuple[str, bool]:
        p = self.ws.resolve(path)
        rel = self.ws.rel(p)
        denied = self.policy.can_write(rel, p.exists())
        if denied:
            raise ToolError(denied)
        return rel, p.exists()

    def _t_edit_file(self, path: str, old_text: str, new_text: str) -> str:
        rel, exists = self._check_write(path)
        if not exists:
            raise ToolError(f"'{path}' doesn't exist; use create_file")
        p = self.ws.resolve(rel)
        text = p.read_text()
        if not old_text.strip():
            raise ToolError("old_text is empty.")
        updated, how = replace_once(text, old_text, new_text)
        p.write_text(updated)
        self.emit("file.edited", path=rel)
        note = " (matched ignoring indentation differences)" if how == "fuzzy" else ""
        return f"Edited {rel}: replaced {old_text.count(chr(10)) + 1} line(s) with {new_text.count(chr(10)) + 1}{note}."

    def _t_create_file(self, path: str, content: str) -> str:
        rel, exists = self._check_write(path)
        if exists:
            raise ToolError(f"'{rel}' already exists; use edit_file")
        p = self.ws.resolve(rel)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content if content.endswith("\n") else content + "\n")
        self.emit("file.created", path=rel)
        return f"Created {rel} ({content.count(chr(10)) + 1} lines)."

    def _t_run_tests(self, selector: str | None = None) -> str:
        report = self.sandbox.run_tests(selector or None)
        self.reports.append(report)
        self.emit(
            "tests.ran",
            selector=selector,
            passed=report.passed,
            failed=report.failed,
            errors=report.errors,
            ok=report.ok,
        )
        return report.summary()

    def _t_git_diff(self) -> str:
        diff = self.ws.diff()
        if not diff:
            return "No changes yet."
        return diff if len(diff) <= MAX_OUTPUT else diff[:MAX_OUTPUT] + "\n[diff truncated]"


_LINE_PREFIX = re.compile(r"^\s*\d+(\t| {1,2}|\s*[|│:]\s?)")


def replace_once(text: str, old: str, new: str) -> tuple[str, str]:
    """Replace one occurrence of `old`. Exact match first; then a line-by-line match that ignores leading
    whitespace and stray line-number prefixes (common free-model mistakes). Raises ToolError otherwise."""
    count = text.count(old)
    if count == 1:
        return text.replace(old, new, 1), "exact"
    if count > 1:
        raise ToolError(f"old_text appears {count} times; include more surrounding lines so it is unique.")

    # strip line-number prefixes if *every* non-empty line has one (copied from read_file output)
    old_lines = old.strip("\n").splitlines()
    if old_lines and all(_LINE_PREFIX.match(ln) for ln in old_lines if ln.strip()):
        old_lines = [_LINE_PREFIX.sub("", ln, count=1) for ln in old_lines]
        new = "\n".join(_LINE_PREFIX.sub("", ln, count=1) for ln in new.split("\n"))

    lines = text.splitlines(keepends=True)
    want = [ln.strip() for ln in old_lines]
    n = len(want)
    hits = [i for i in range(len(lines) - n + 1) if all(lines[i + j].strip() == want[j] for j in range(n))]
    if len(hits) > 1:
        raise ToolError(f"old_text matches {len(hits)} places; include more surrounding lines so it is unique.")
    if not hits:
        raise ToolError("old_text not found." + _closest(lines, want))

    i = hits[0]
    file_indent = re.match(r"\s*", lines[i]).group(0)
    old_indent = re.match(r"\s*", old_lines[0]).group(0)
    new_lines = []
    for ln in new.split("\n"):
        if ln.startswith(old_indent) and ln.strip():
            ln = file_indent + ln[len(old_indent) :]
        new_lines.append(ln)
    replacement = "\n".join(new_lines)
    if not replacement.endswith("\n") and lines[i + n - 1].endswith("\n"):
        replacement += "\n"
    return "".join(lines[:i]) + replacement + "".join(lines[i + n :]), "fuzzy"


def _closest(lines: list[str], want: list[str]) -> str:
    first = next((w for w in want if w), "")
    stripped = [ln.strip() for ln in lines]
    match = difflib.get_close_matches(first, stripped, n=1, cutoff=0.5)
    if not match:
        return " Read the file again and copy the exact text."
    i = stripped.index(match[0])
    snippet = "".join(lines[max(0, i - 2) : i + len(want) + 2])
    return f" The closest text in the file (copy it exactly, no line numbers):\n{snippet}"


def parse_args(raw: str) -> dict[str, Any]:
    """Tool-call arguments from the model; tolerant of the small JSON mistakes free models make."""
    raw = (raw or "").strip() or "{}"
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        fixed = re.sub(r",\s*([}\]])", r"\1", raw)  # trailing commas
        try:
            value = json.loads(fixed)
        except json.JSONDecodeError as err:
            raise ToolError(f"arguments are not valid JSON: {err}") from err
    if not isinstance(value, dict):
        raise ToolError("arguments must be a JSON object")
    return value
