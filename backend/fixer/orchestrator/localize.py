"""Localize (Plan.md §4, phase 5) without spending LLM requests: rank suspect files from
stack traces, identifiers named in the issue, and what the reproduction test imports."""

from __future__ import annotations

import re
from collections import defaultdict

from fixer.sandbox.detect import EnvSpec
from fixer.sandbox.workspace import Workspace

PATH_LINE = re.compile(
    r"""(?:File\s+["']?|at\s+.*?\(|^|\s)([\w./-]+\.(?:py|js|jsx|ts|tsx|mjs|cjs|java|kt))["']?(?:,\s*line\s+|:)(\d+)""",
    re.MULTILINE,
)
IDENT = re.compile(
    r"`([A-Za-z_][\w.]*)`|\b([a-z]+(?:_[a-z0-9]+)+)\b|\b([A-Z][a-z0-9]+(?:[A-Z][a-z0-9]+)+)\b|"
    r"\b([A-Za-z_]\w*)\("
)
PY_IMPORT = re.compile(r"^\s*(?:from\s+([\w.]+)\s+import\s+([\w, ]+)|import\s+([\w.]+))", re.MULTILINE)
JS_IMPORT = re.compile(r"""(?:from\s+|require\()\s*['"](\.{1,2}/[^'"]+)['"]""")
STOPWORDS = {
    "print",
    "len",
    "range",
    "str",
    "int",
    "list",
    "dict",
    "self",
    "return",
    "assert",
    "test",
    "expect",
    "describe",
    "it",
    "function",
    "def",
    "class",
    "import",
    "from",
    "true",
    "false",
    "none",
    "null",
}


def issue_identifiers(issue: str) -> set[str]:
    """Code-like names mentioned in the issue: `quoted`, snake_case, CamelCase, or called like f(...)."""
    idents = {next(g for g in m if g).split(".")[-1] for m in IDENT.findall(issue)}
    return {i for i in idents if len(i) > 3 and i.lower() not in STOPWORDS}


def _source_files(ws: Workspace, spec: EnvSpec) -> list[str]:
    exts = {"python": (".py",), "node": (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"), "java": (".java", ".kt")}
    wanted = exts.get(spec.language, (".py",))
    return [f for f in ws.baseline_files() if f.endswith(wanted) and not spec.is_test_path(f)]


def rank(
    ws: Workspace,
    spec: EnvSpec,
    issue: str,
    failure_text: str,
    repro_file: str | None,
    top: int = 6,
    with_reasons: bool = True,
) -> list[str]:
    files = _source_files(ws, spec)
    if not files:
        return []
    score: dict[str, float] = defaultdict(float)
    why: dict[str, list[str]] = defaultdict(list)

    # 1. files named in stack traces (issue and the reproduction failure)
    for text, weight in ((failure_text, 6.0), (issue, 5.0)):
        for path, line in PATH_LINE.findall(text or ""):
            match = next((f for f in files if f.endswith(path.lstrip("./")) or path.endswith(f)), None)
            if match:
                score[match] += weight
                note = f"line {line} is in a stack trace"
                if note not in why[match]:
                    why[match].append(note)

    # 2. modules the reproduction test imports
    if repro_file:
        try:
            text = ws.resolve(repro_file).read_text(errors="ignore")
        except Exception:  # noqa: BLE001
            text = ""
        mods = [m[0] or m[2] for m in PY_IMPORT.findall(text)] + JS_IMPORT.findall(text)
        for mod in mods:
            stem = mod.replace(".", "/").lstrip("./")
            for f in files:
                if f.startswith(stem) or f.rsplit(".", 1)[0].endswith(stem):
                    score[f] += 3.0
                    why[f].append("imported by the reproduction test")

    # 3. identifiers from the issue that are defined or used in a file
    idents = issue_identifiers(issue)
    for f in files:
        try:
            body = (ws.root / f).read_text(errors="ignore")
        except OSError:
            continue
        hits = [i for i in idents if re.search(rf"\b{re.escape(i)}\b", body)]
        defs = [
            i
            for i in hits
            if re.search(
                rf"(def|class|function|const|let|var)\s+{re.escape(i)}\b|"
                rf"\b{re.escape(i)}\s*\(.*\)\s*\{{",
                body,
            )
        ]
        if hits:
            score[f] += len(hits) * 0.6 + len(defs) * 2.0
            if defs:
                why[f].append("defines " + ", ".join(sorted(defs)[:3]))
            else:
                why[f].append("mentions " + ", ".join(sorted(hits)[:3]))

    ranked = sorted(score, key=lambda f: -score[f])[:top]
    if not with_reasons:
        return ranked
    return [f"{f} ({'; '.join(dict.fromkeys(why[f]))})" for f in ranked]
