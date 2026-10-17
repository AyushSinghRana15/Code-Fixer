"""Test doubles: a provider that replays a script instead of calling an LLM."""

from __future__ import annotations

import json
from typing import Any

from fixer.llm.client import LLMMessage, ProviderError, ToolCall
from fixer.llm.providers import ProviderSpec


def spec(pid: str = "fake", rpm: int | None = None, trains: bool = False) -> ProviderSpec:
    return ProviderSpec(
        id=pid,
        name=pid,
        base_url="http://fake",
        key_envs=(),
        rpm=rpm,
        trains_on_data=trains,
        models={"fix": ("m1", "m2"), "critic": ("m1",)},
    )


def call(name: str, **args: Any) -> LLMMessage:
    return LLMMessage(content=None, tool_calls=[ToolCall(id=f"c_{name}", name=name, arguments=json.dumps(args))])


def text(content: str) -> LLMMessage:
    return LLMMessage(content=content)


class ScriptedProvider:
    """Returns queued replies in order; an Exception in the queue is raised instead."""

    def __init__(self, script: list[LLMMessage | Exception], pid: str = "fake", **spec_kw: Any):
        self.spec = spec(pid, **spec_kw)
        self.script = list(script)
        self.calls: list[dict[str, Any]] = []

    def complete(self, model, messages, tools, max_tokens, temperature) -> LLMMessage:
        self.calls.append({"model": model, "messages": messages, "tools": tools})
        if not self.script:
            raise AssertionError("script exhausted: the agent asked for more turns than expected")
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def err(kind: str, retry_after: float | None = None) -> ProviderError:
    return ProviderError(kind, f"fake {kind}", retry_after=retry_after)


class AgentBrain:
    """For parallel agents: picks the reply from the calling agent's own script, by agent kind (from its
    system prompt / task) and by how many turns that conversation has had. Thread-safe by construction."""

    def __init__(self, scripts: dict[str, list[LLMMessage]]):
        self.scripts = scripts
        self.calls: list[str] = []

    @staticmethod
    def kind(messages: list[dict[str, Any]]) -> str:
        system, task = messages[0]["content"], messages[1]["content"] if len(messages) > 1 else ""
        if "You are a scout" in system:
            return "scout-tests" if "How are tests" in task else "scout-code"
        if "You review a bug fix" in system:
            return "critic"
        if "write ONE small automated test" in system:
            return "reproducer"
        return "fixer"

    def provider(self, pid: str) -> BrainProvider:
        return BrainProvider(self, pid)


class BrainProvider:
    def __init__(self, brain: AgentBrain, pid: str):
        self.brain, self.spec = brain, spec(pid)
        self.spec = ProviderSpec(
            id=pid,
            name=pid,
            base_url="http://fake",
            key_envs=(),
            models={"fix": ("m",), "critic": ("m",), "scout": ("m",)},
        )

    def complete(self, model, messages, tools, max_tokens, temperature) -> LLMMessage:
        kind = AgentBrain.kind(messages)
        turn = sum(1 for m in messages if m["role"] == "assistant")
        self.brain.calls.append(f"{self.spec.id}:{kind}:{turn}")
        script = self.brain.scripts[kind]
        if turn >= len(script):
            raise AssertionError(f"{kind} asked for turn {turn} but its script has {len(script)}")
        return script[turn]
