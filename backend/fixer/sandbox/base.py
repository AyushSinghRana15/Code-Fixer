"""Sandbox interface: run commands and tests against the workspace."""

from __future__ import annotations

import shlex
from abc import ABC, abstractmethod
from dataclasses import dataclass

from fixer.sandbox.detect import EnvSpec
from fixer.sandbox.results import TestReport, parse_junit
from fixer.sandbox.workspace import Workspace


@dataclass
class CommandResult:
    exit_code: int
    output: str
    seconds: float
    timed_out: bool = False


class Sandbox(ABC):
    kind = "base"

    def __init__(self, workspace: Workspace, spec: EnvSpec):
        self.ws = workspace
        self.spec = spec

    @abstractmethod
    def start(self) -> None: ...

    @abstractmethod
    def exec(self, cmd: str, timeout: int = 600, network: bool = False) -> CommandResult: ...

    @abstractmethod
    def stop(self) -> None: ...

    def setup(self, timeout: int = 900) -> CommandResult:
        """Install dependencies (the only step that gets network access)."""
        outputs, total = [], 0.0
        for cmd in self.spec.setup:
            res = self.exec(cmd, timeout=timeout, network=True)
            total += res.seconds
            outputs.append(f"$ {cmd}\n{res.output}")
            if res.exit_code != 0 or res.timed_out:
                return CommandResult(res.exit_code or 1, "\n".join(outputs), total, res.timed_out)
        return CommandResult(0, "\n".join(outputs), total)

    def run_tests(self, selector: str | None = None, timeout: int = 900) -> TestReport:
        cmd = self.spec.test_one.format(selector=shlex.quote(selector)) if selector else self.spec.test_all
        if self.spec.clean:
            cmd = f"{self.spec.clean}; {cmd}"
        res = self.exec(cmd, timeout=timeout, network=False)
        paths = [p for g in self.spec.junit_globs for p in self.ws.root.glob(g)]
        report = parse_junit(paths, res.exit_code, res.output)
        report.timed_out = res.timed_out
        return report

    def __enter__(self) -> Sandbox:
        self.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.stop()
