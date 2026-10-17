"""Generic tool-use loop. One call to run_agent = one phase's sub-task (reproduce or fix)."""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from fixer.llm.client import ToolCall
from fixer.llm.router import LLMRouter
from fixer.tools.toolbox import Toolbox, ToolError, normalize_args, parse_args

KEEP_RECENT_TOOL_RESULTS = 6  # older tool outputs get shortened to save context
OLD_RESULT_CHARS = 300
MAX_TOOL_RESULT = 7000
MAX_NUDGES = 3


@dataclass
class AgentOutcome:
    status: str  # finished | gave_up | out_of_iterations | budget
    args: dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    iterations: int = 0


# ---- text tool calls: some free models write the call as text instead of using native tool calling ----
_TAGGED = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.DOTALL)
_FENCED = re.compile(r"```(?:json|tool_call)?\s*(\{.*?\})\s*```", re.DOTALL)


def parse_text_tool_calls(
    content: str | None, known: set[str], params: dict[str, set[str]] | None = None
) -> list[ToolCall]:
    """Tool calls written as text. `params` (tool -> argument names) lets us also accept bare argument objects
    like {"test_id": ..., "explanation": ...} when exactly one tool takes those arguments."""
    if not content:
        return []
    blobs = _TAGGED.findall(content) or _FENCED.findall(content)
    if not blobs and content.strip().startswith("{"):
        blobs = [content.strip()]
    calls = []
    for blob in blobs:
        try:
            obj = json.loads(blob)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        name = obj.get("name") or obj.get("tool") or obj.get("function")
        args = obj.get("arguments", obj.get("args", obj.get("parameters", {})))
        if not name and params:
            keys = set(obj)
            matches = [t for t, p in params.items() if keys and keys <= p]
            if len(matches) == 1:
                name, args = matches[0], obj
        if isinstance(name, str) and name in known:
            calls.append(
                ToolCall(
                    id=f"text_{uuid.uuid4().hex[:8]}",
                    name=name,
                    arguments=args if isinstance(args, str) else json.dumps(args),
                )
            )
    return calls


def _compact(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Shorten old tool outputs; the latest few stay intact (cheap context management, refined in phase 09)."""
    tool_idx = [i for i, m in enumerate(messages) if m["role"] == "tool"]
    old = set(tool_idx[:-KEEP_RECENT_TOOL_RESULTS])
    out = []
    for i, m in enumerate(messages):
        if i in old and len(m.get("content") or "") > OLD_RESULT_CHARS:
            m = {
                **m,
                "content": m["content"][:OLD_RESULT_CHARS] + f"\n[… older output trimmed, {len(m['content'])} chars]",
            }
        out.append(m)
    return out


def run_agent(
    *,
    router: LLMRouter,
    toolbox: Toolbox,
    tools: list[dict[str, Any]],
    system: str,
    task: str,
    max_iterations: int,
    validate_finish: Callable[[dict[str, Any]], str | None],
    on_report: Callable[[], str | None] | None = None,
    check_budget: Callable[[], str | None] = lambda: None,
    emit: Callable[..., None] = lambda *a, **k: None,
    role: str = "fix",
    agent: str = "agent",
    prefer: list[str] | None = None,
) -> AgentOutcome:
    """Run until the model calls finish (and validate_finish accepts it), gives up, or runs out of turns.

    validate_finish returns None to accept, or a message explaining why finish was rejected.
    on_report runs after each run_tests call; it may return a message (e.g. stuck warning) or raise to stop.
    """
    known = {t["function"]["name"] for t in tools}
    params = {t["function"]["name"]: set(t["function"]["parameters"].get("properties", {})) for t in tools}
    messages: list[dict[str, Any]] = [{"role": "system", "content": system}, {"role": "user", "content": task}]
    nudges = 0

    for iteration in range(1, max_iterations + 1):
        over = check_budget()
        if over:
            return AgentOutcome("budget", reason=over, iterations=iteration - 1)
        if iteration == max_iterations and max_iterations > 1:
            messages.append(
                {
                    "role": "user",
                    "content": "This is your LAST turn. Call `finish` now with what you "
                    "have (or `give_up` if you truly can't).",
                }
            )
        result = router.chat(_compact(messages), tools=tools, role=role, agent=agent, prefer=prefer)
        msg = result.message
        native = bool(msg.tool_calls)
        calls = msg.tool_calls or parse_text_tool_calls(msg.content, known, params)
        if msg.content and msg.content.strip():
            emit("agent.thought", text=msg.content.strip()[:500])

        if not calls:
            nudges += 1
            if nudges > MAX_NUDGES:
                return AgentOutcome("gave_up", reason="the model stopped using tools", iterations=iteration)
            messages.append({"role": "assistant", "content": msg.content or ""})
            messages.append(
                {
                    "role": "user",
                    "content": "Continue by calling one of the tools. When you are done, "
                    "call `finish`; if it can't be done, call `give_up`.",
                }
            )
            continue

        if native:
            messages.append(
                {
                    "role": "assistant",
                    "content": msg.content or "",
                    "tool_calls": [
                        {"id": c.id, "type": "function", "function": {"name": c.name, "arguments": c.arguments}}
                        for c in calls
                    ],
                }
            )
        else:
            messages.append({"role": "assistant", "content": msg.content or ""})

        extra_notes: list[str] = []
        for call in calls:
            try:
                args = parse_args(call.arguments)
                if call.name in ("finish", "give_up"):
                    args = normalize_args(call.name, args)
            except ToolError as err:
                output, args = f"Error: {err}", {}
            else:
                emit("tool.call", tool=call.name, args=_preview_args(args))
                if call.name == "give_up":
                    return AgentOutcome("gave_up", args, str(args.get("reason", "")), iteration)
                if call.name == "finish":
                    rejection = validate_finish(args)
                    if rejection is None:
                        return AgentOutcome("finished", args, iterations=iteration)
                    output = f"finish was rejected: {rejection}"
                    emit("agent.finish_rejected", reason=rejection[:300])
                else:
                    try:
                        output = toolbox.execute(call.name, args)
                    except ToolError as err:
                        output = f"Error: {err}"
                    if call.name == "run_tests" and on_report:
                        note = on_report()
                        if note:
                            extra_notes.append(note)
            emit(
                "tool.result",
                tool=call.name,
                ok=not output.startswith(("Error", "finish was rejected")),
                preview=output[:200],
            )
            output = output if len(output) <= MAX_TOOL_RESULT else output[:MAX_TOOL_RESULT] + "\n[truncated]"
            if native:
                messages.append({"role": "tool", "tool_call_id": call.id, "content": output})
            else:
                messages.append({"role": "user", "content": f"Result of {call.name}:\n{output}"})
        for note in extra_notes:
            messages.append({"role": "user", "content": note})

    return AgentOutcome(
        "out_of_iterations", reason=f"no result after {max_iterations} turns", iterations=max_iterations
    )


def _preview_args(args: dict[str, Any]) -> dict[str, Any]:
    return {k: (v if not isinstance(v, str) or len(v) <= 120 else v[:120] + "…") for k, v in args.items()}
