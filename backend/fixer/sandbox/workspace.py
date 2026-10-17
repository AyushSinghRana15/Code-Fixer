"""A private, git-tracked copy of the target repo. The user's own checkout is never modified."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

SKIP_DIRS = {
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    ".fixer-venv",
    ".fixer",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".next",
    ".gradle",
    ".tox",
    "target",
    ".idea",
    ".vscode",
}
# Never readable or writable by the agent's tools.
HIDDEN = (".git", ".fixer-venv", ".fixer", "node_modules")
EXCLUDES = "\n".join(f"{d}/" for d in sorted(SKIP_DIRS)) + "\n"

GIT = [
    "git",
    "-c",
    "user.name=Code Fixer",
    "-c",
    "user.email=fixer@localhost",
    "-c",
    "commit.gpgsign=false",
    "-c",
    "core.hooksPath=/dev/null",
]


class PathError(Exception):
    pass


class Workspace:
    def __init__(self, root: Path, baseline: str):
        self.root = root
        self.baseline = baseline

    @classmethod
    def create(cls, src: Path, dest: Path) -> Workspace:
        src = src.resolve()
        if not src.is_dir():
            raise PathError(f"repo not found: {src}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src, dest, symlinks=True, ignore=shutil.ignore_patterns(*SKIP_DIRS))
        if not (dest / ".git").exists():
            cls._git(dest, "init", "-q")
        exclude = dest / ".git" / "info" / "exclude"
        exclude.parent.mkdir(parents=True, exist_ok=True)
        exclude.write_text((exclude.read_text() if exclude.exists() else "") + "\n" + EXCLUDES)
        cls._git(dest, "add", "-A")
        cls._git(dest, "commit", "-q", "--allow-empty", "--no-verify", "-m", "fixer: baseline")
        sha = cls._git(dest, "rev-parse", "HEAD").strip()
        return cls(dest, sha)

    @staticmethod
    def _git(cwd: Path, *args: str) -> str:
        res = subprocess.run([*GIT, *args], cwd=cwd, capture_output=True, text=True)
        if res.returncode != 0:
            raise RuntimeError(f"git {' '.join(args)} failed: {res.stderr.strip()}")
        return res.stdout

    def git(self, *args: str) -> str:
        return self._git(self.root, *args)

    # ---- path safety ----
    def resolve(self, rel: str) -> Path:
        """Repo-relative path -> absolute path, refusing anything outside the repo or in hidden dirs."""
        rel = (rel or ".").strip()
        if rel.startswith("/"):
            # tolerate absolute paths that point inside the workspace
            p = Path(rel).resolve()
        else:
            p = (self.root / rel).resolve()
        root = self.root.resolve()
        if p != root and root not in p.parents:
            raise PathError(f"'{rel}' is outside the repository")
        parts = p.relative_to(root).parts
        if parts and parts[0] in HIDDEN:
            raise PathError(f"'{rel}' is not accessible")
        return p

    def rel(self, p: Path) -> str:
        return p.resolve().relative_to(self.root.resolve()).as_posix()

    # ---- state ----
    def baseline_files(self) -> set[str]:
        return set(self.git("ls-tree", "-r", "--name-only", self.baseline).splitlines())

    def diff(self) -> str:
        self.git("add", "-A")
        return self.git("diff", "--cached", "--no-color", self.baseline)

    def changed_files(self) -> list[tuple[str, str]]:
        """[(status, path)] where status is A (added), M (modified) or D (deleted)."""
        self.git("add", "-A")
        out = self.git("diff", "--cached", "--name-status", "--no-renames", self.baseline)
        return [tuple(line.split("\t", 1)) for line in out.splitlines() if "\t" in line]  # type: ignore[misc]
