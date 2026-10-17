"""Live provider check: is the key accepted, does a model answer, does tool calling work? (1 request)"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass

from fixer.llm.client import OpenAICompatProvider, ProviderError
from fixer.llm.providers import ProviderSpec, models_for

_TOOL = {
    "type": "function",
    "function": {
        "name": "add",
        "description": "Add two integers.",
        "parameters": {"type": "object", "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}}},
    },
}
_MSGS = [{"role": "user", "content": "Use the add tool to add 2 and 3."}]


@dataclass
class CheckResult:
    ok: bool
    latencyMs: int  # noqa: N815 - matches the frontend's ProviderTestResult
    toolCalling: bool  # noqa: N815
    message: str
    kind: str = "ok"  # ok | auth | credits | quota | rate | model | server | other
    model: str = ""

    def api(self) -> dict:
        d = asdict(self)
        d.pop("kind")
        d.pop("model")
        return d


def check_provider(spec: ProviderSpec, key: str | None, timeout: float = 45) -> CheckResult:
    client = OpenAICompatProvider(spec, key, timeout=timeout)
    last: CheckResult | None = None
    for model in models_for(spec, "fix")[:3]:
        t0 = time.monotonic()
        try:
            msg = client.complete(model, _MSGS, [_TOOL], max_tokens=200, temperature=0)
        except ProviderError as err:
            ms = int((time.monotonic() - t0) * 1000)
            kind = err.kind if err.kind in ("auth", "credits", "quota", "rate", "model", "server") else "other"
            text = {
                "auth": "The key was rejected (401/403).",
                "credits": "The key works, but the account has no credits left.",
                "quota": "The key works, but today's free quota is used up. It resets at midnight UTC.",
                "rate": "The key works, but the provider is rate-limiting right now.",
            }.get(kind, f"{model}: {str(err)[:160]}")
            last = CheckResult(kind in ("quota", "rate"), ms, False, text, kind, model)
            if kind in ("auth", "credits", "quota", "rate"):
                return last
            continue  # try the next model
        ms = int((time.monotonic() - t0) * 1000)
        tools = any(c.name == "add" for c in msg.tool_calls)
        text = f"Key valid · {model} answered in {ms} ms · tool calling {'works' if tools else 'NOT used'}"
        return CheckResult(True, ms, tools, text, "ok", model)
    return last or CheckResult(False, 0, False, "No model configured for this provider.", "model")
