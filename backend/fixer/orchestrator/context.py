"""Context pack: the orchestrator's own, LLM-free briefing for the agents (Plan.md §4b).

Pulls the definitions that match identifiers from the issue (exact source, with line ranges) and the head of
the most relevant test file. When it is confident, LLM scouts are skipped entirely; downstream agents start
from this pack instead of spending requests (and a growing context) on exploration.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass

from fixer.orchestrator.localize import issue_identifiers
from fixer.sandbox.detect import EnvSpec
from fixer.sandbox.workspace import Workspace

MAX_SNIPPET_LINES = 40
MAX_CODE_CHARS = 2200
TEST_HEAD_LINES = 25


@dataclass
class ContextPack:
    text: str
    confident: bool  # found definitions of identifiers named in the issue
    snippets: int


def _python_snippets(path: str, source: str, idents: set[str]) -> list[tuple[int, str, bool]]:
    """(start line, snippet, defines-an-identifier) for functions/classes relevant to the issue."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    lines = source.splitlines()
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            continue
        start, end = node.lineno, getattr(node, "end_lineno", node.lineno) or node.lineno
        body = "\n".join(lines[start - 1 : end])
        defines = node.name in idents
        if defines or (not isinstance(node, ast.ClassDef) and any(re.search(rf"\b{i}\b", body) for i in idents)):
            if end - start + 1 > MAX_SNIPPET_LINES:
                end = start + MAX_SNIPPET_LINES - 1
                body = "\n".join(lines[start - 1 : end]) + "\n    # … (truncated)"
            out.append((start, f"{path}:{start}-{end}\n{body}", defines))
    return out


def _text_snippets(path: str, source: str, idents: set[str]) -> list[tuple[int, str, bool]]:
    lines = source.splitlines()
    out, used = [], set()
    for n, line in enumerate(lines, 1):
        hit = next((i for i in idents if re.search(rf"\b{re.escape(i)}\b", line)), None)
        if hit and n not in used:
            lo, hi = max(1, n - 3), min(len(lines), n + 15)
            used.update(range(lo, hi + 1))
            defines = bool(re.search(rf"(function|def|class|const|let|var|public|private|static)\b.*\b{hit}\b", line))
            out.append((lo, f"{path}:{lo}-{hi}\n" + "\n".join(lines[lo - 1 : hi]), defines))
    return out


def build_pack(ws: Workspace, spec: EnvSpec, issue: str, ranked_files: list[str]) -> ContextPack:
    idents = issue_identifiers(issue)
    code_parts: list[str] = []
    confident = False
    total = 0
    for path in ranked_files[:3]:
        try:
            source = ws.resolve(path).read_text(errors="ignore")
        except Exception:  # noqa: BLE001
            continue
        snippets = (_python_snippets if path.endswith(".py") else _text_snippets)(path, source, idents)
        for _, snippet, defines in sorted(snippets, key=lambda s: (not s[2], s[0])):
            if total + len(snippet) > MAX_CODE_CHARS:
                break
            code_parts.append(snippet)
            total += len(snippet)
            confident = confident or defines

    # the test file that already exercises the top-ranked code, for style and imports
    tests = sorted(f for f in ws.baseline_files() if spec.is_test_path(f) and not f.endswith("conftest.py"))
    test_part = ""
    if ranked_files and tests:
        top = ranked_files[0]
        module = top.rsplit(".", 1)[0].replace("/", ".")
        stem = top.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        best = None
        for t in tests:
            try:
                body = ws.resolve(t).read_text(errors="ignore")
            except Exception:  # noqa: BLE001
                continue
            if module in body or re.search(rf"\b{re.escape(stem)}\b", body):
                best = (t, body)
                break
        if best:
            head = "\n".join(best[1].splitlines()[:TEST_HEAD_LINES])
            test_part = f"Closest existing test file ({best[0]}), first lines:\n{head}"

    sections = []
    if code_parts:
        sections.append("Relevant code (exact source with line ranges):\n\n" + "\n\n".join(code_parts))
    if test_part:
        sections.append(test_part)
    if tests:
        sections.append(f"Test files: {', '.join(tests[:10])}. Run one test with {spec.selector_hint}.")
    return ContextPack("\n\n".join(sections), confident, len(code_parts))
