"""One provider = one OpenAI-compatible client. Provider-specific errors become a few ProviderError kinds."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

import openai

from fixer.llm.providers import ProviderSpec


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str  # raw JSON string, exactly as the model produced it


@dataclass
class LLMMessage:
    content: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=dict)


class ProviderError(Exception):
    """kind: auth | credits | rate | quota | too_large | model | flaky | server | bad_request | empty"""

    def __init__(self, kind: str, message: str, status: int | None = None, retry_after: float | None = None):
        super().__init__(message)
        self.kind = kind
        self.status = status
        self.retry_after = retry_after
        self.body: object = None


class Provider(Protocol):
    spec: ProviderSpec

    def complete(
        self,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        max_tokens: int,
        temperature: float,
    ) -> LLMMessage: ...


def _retry_after(err: openai.APIStatusError) -> float | None:
    try:
        value = err.response.headers.get("retry-after")
        return float(value) if value else None
    except (AttributeError, ValueError):
        return None


def classify(err: Exception) -> ProviderError:
    """Map SDK exceptions to the router's error kinds (Plan.md §7.5)."""
    if isinstance(err, openai.APITimeoutError | openai.APIConnectionError):
        return ProviderError("server", f"connection problem: {err}")
    if not isinstance(err, openai.APIStatusError):
        return ProviderError("server", str(err))

    status = err.status_code
    text = str(err).lower()
    detail = str(err)[:300]
    if status in (401, 403):
        return ProviderError("auth", f"key rejected ({status})", status)
    if status == 402 or "insufficient credits" in text or ("credit" in text and "balance" in text):
        return ProviderError("credits", f"out of credits ({status})", status)
    # Token-per-minute caps (e.g. Groq free tier): "Limit 8000, Used 5100, Requested 4200".
    # Too large only if this one request exceeds the cap; otherwise it's a normal "wait a bit" rate limit.
    tpm = re.search(r"limit\s*(\d+).*?requested\s*(\d+)", text)
    if status == 413 or (tpm and int(tpm.group(2)) > int(tpm.group(1))):
        return ProviderError("too_large", f"request too large for this provider ({detail})", status)
    if status == 429:
        daily = any(s in text for s in ("per-day", "per day", "daily", "free-models-per-day", "quota"))
        wait = _retry_after(err)
        if wait is None:  # "Please try again in 7.66s"
            m = re.search(r"try again in\s*(?:(\d+)m)?\s*([\d.]+)s", text)
            wait = (int(m.group(1) or 0) * 60 + float(m.group(2))) if m else None
        return ProviderError("quota" if daily else "rate", f"rate limited: {detail}", status, wait)
    if status == 404 or "no endpoints" in text or "model not found" in text or "does not exist" in text:
        return ProviderError("model", f"model unavailable ({status})", status)
    if status == 400 and (
        "tool_use_failed" in text or "failed to call a function" in text or "failed_generation" in text
    ):
        # The model produced a malformed tool call (Groq reports this). A one-off; retrying usually works.
        return ProviderError("flaky", f"model produced a malformed tool call ({detail})", status)
    if status == 400 and ("tool" in text or "function" in text) and "support" in text:
        return ProviderError("model", f"model doesn't support tool calling ({detail})", status)
    if status >= 500:
        return ProviderError("server", f"provider error ({status}: {detail})", status)
    return ProviderError("bad_request", f"request rejected ({status}): {detail}", status)


def recover_failed_generation(err: ProviderError, known: set[str]) -> LLMMessage | None:
    """Groq validates tool calls server-side and rejects the reply when the model garbles one (e.g. a tool
    named "name=finish"). The attempted call is in `failed_generation`; salvage it when it's recognisable."""
    if err.kind != "flaky" or not known:
        return None
    body = getattr(err, "body", None)
    raw = None
    if isinstance(body, dict):
        raw = body.get("failed_generation") or (body.get("error") or {}).get("failed_generation")
    if not isinstance(raw, str):
        return None
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        # Not a JSON call: hand the raw text back as the model's reply. The agent loop's text parser gets a
        # chance at it, and otherwise nudges the model, instead of the whole turn being lost.
        return LLMMessage(content=raw[:4000]) if raw.strip() else None
    items = obj if isinstance(obj, list) else [obj]
    calls = []
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        name = re.sub(r"^(name=|functions\.|function\.|tools?\.)", "", str(item.get("name", ""))).strip()
        args = item.get("arguments", item.get("parameters", {}))
        if name in known:
            calls.append(ToolCall(f"recovered_{i}", name, args if isinstance(args, str) else json.dumps(args)))
    return LLMMessage(content=None, tool_calls=calls) if calls else None


class OpenAICompatProvider:
    def __init__(self, spec: ProviderSpec, api_key: str | None, timeout: float = 120.0):
        self.spec = spec
        headers = {}
        if spec.id == "openrouter":  # optional attribution headers OpenRouter asks for
            headers = {"HTTP-Referer": "https://github.com/AyushSinghRana15/Code-Fixer", "X-Title": "Code Fixer"}
        self._client = openai.OpenAI(
            api_key=api_key or "not-needed",
            base_url=spec.base_url,
            timeout=timeout,
            max_retries=0,  # the router owns retries and failover
            default_headers=headers,
        )

    def complete(self, model, messages, tools, max_tokens, temperature) -> LLMMessage:
        try:
            return self._complete(model, messages, tools, max_tokens, temperature)
        except ProviderError as err:
            recovered = recover_failed_generation(err, {t["function"]["name"] for t in tools or []})
            if recovered:
                return recovered
            raise

    def _complete(self, model, messages, tools, max_tokens, temperature) -> LLMMessage:
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        try:
            resp = self._client.chat.completions.create(**kwargs)
        except Exception as err:  # noqa: BLE001 - every failure is classified for the router
            pe = classify(err)
            pe.body = getattr(err, "body", None)
            raise pe from err

        if not resp.choices:
            raise ProviderError("empty", "provider returned no choices")
        msg = resp.choices[0].message
        calls = [
            ToolCall(id=c.id or f"call_{i}", name=c.function.name, arguments=c.function.arguments or "{}")
            for i, c in enumerate(msg.tool_calls or [])
            if getattr(c, "function", None)
        ]
        if not calls and not (msg.content or "").strip():
            raise ProviderError("empty", "model returned an empty reply")
        usage = {}
        if resp.usage:
            usage = {"input": resp.usage.prompt_tokens or 0, "output": resp.usage.completion_tokens or 0}
        return LLMMessage(content=msg.content, tool_calls=calls, usage=usage)
