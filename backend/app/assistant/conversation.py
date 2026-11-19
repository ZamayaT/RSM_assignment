"""The conversation loop: ask the model, run the tools it asks for, give the results back, until it answers.

It is bounded (a step limit, with the last model call made without tools so it has to answer), never trusts the
model's arguments (invalid JSON, unknown tools and any other trip id are refused as failed tool calls that the
model and the user both see) and never turns a failure into a success.
"""
import json
import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app.assistant.llm_client import AssistantError, LLMClient, ToolCall
from app.assistant.mcp_bridge import McpBridge
from app.assistant.prompt import system_prompt

logger = logging.getLogger("app.assistant")

MAX_CALLS_PER_STEP = 5
PREFETCH = ("get_trip", "get_budget")  # almost every answer needs them, so they are read before the first model call
RESULT_EXCERPT_CHARS = 16000  # the page and the evaluation see what the model saw (the bridge limits a result to this many characters)


@dataclass
class ToolCallLog:
    name: str
    arguments: dict[str, Any]
    ok: bool
    summary: str
    error: str | None
    result: str | None  # the tool's result as the model saw it (shortened), so the user can check the answer
    duration_ms: int
    prefetched: bool = False  # read by the assistant before the first model call, to save model calls


@dataclass
class AssistantResult:
    reply: str
    tool_calls: list[ToolCallLog] = field(default_factory=list)
    steps: int = 0
    incomplete: bool = False  # True when the step limit stopped the assistant before it could answer


def summarize(name: str, data: Any) -> str:
    """One short line about a successful tool result, for the 'tools used' list."""
    if not isinstance(data, dict):
        return "ok"
    if name == "search_options":
        warnings = len(data.get("warnings", []))
        return f"{data.get('state')}: {len(data.get('offers', []))} offer(s)" + (f", {warnings} supplier warning(s)" if warnings else "")
    if name == "get_trip":
        return f"{data.get('name')} ({data.get('startDate')} to {data.get('endDate')})"
    if name == "get_itinerary":
        return f"{len(data.get('items', []))} item(s)"
    if name == "get_budget":
        return f"{data.get('combinedTotal')} of {data.get('budget')} USD used, {data.get('remaining')} remaining"
    if name == "get_bookings":
        counts = data.get("counts", {})
        return ", ".join(f"{counts.get(k, 0)} {k}" for k in ("confirmed", "pending", "unknown", "failed"))
    return "ok"


def failed(name: str, arguments: dict[str, Any], message: str) -> tuple[ToolCallLog, str]:
    return ToolCallLog(name, arguments, False, "failed", message, None, 0), f"ERROR: {message}"


async def execute(call: ToolCall, bridge: McpBridge, trip_id: str) -> tuple[ToolCallLog, str]:
    """Run one tool call the model asked for. Returns the log entry for the page and the text for the model."""
    try:
        arguments = json.loads(call.arguments) if call.arguments.strip() else {}
    except ValueError:
        return failed(call.name, {}, "The arguments were not valid JSON.")
    if not isinstance(arguments, dict):
        return failed(call.name, {}, "The arguments must be a JSON object.")
    if call.name not in bridge.tool_names:
        return failed(call.name, arguments, f"Unknown tool {call.name!r}. Available tools: {', '.join(sorted(bridge.tool_names))}.")
    if "trip_id" in arguments and str(arguments["trip_id"]) != trip_id:
        return failed(call.name, arguments, f"This conversation is about trip {trip_id}; other trips cannot be read.")
    arguments["trip_id"] = trip_id
    result = await bridge.call(call.name, arguments)
    logger.info("assistant tool %s ok=%s in %d ms", call.name, result.ok, result.duration_ms)
    if not result.ok:
        return ToolCallLog(call.name, arguments, False, "failed", result.error, None, result.duration_ms), f"ERROR: {result.text}"
    excerpt = result.text if len(result.text) <= RESULT_EXCERPT_CHARS else result.text[:RESULT_EXCERPT_CHARS] + "…"
    log = ToolCallLog(call.name, arguments, True, summarize(call.name, result.data), None, excerpt, result.duration_ms)
    return log, result.text


def assistant_message(content: str | None, calls: list[ToolCall]) -> dict[str, Any]:
    """The model's turn as the chat API expects it back (only the standard fields)."""
    return {
        "role": "assistant",
        "content": content or "",
        "tool_calls": [{"id": c.id, "type": "function", "function": {"name": c.name, "arguments": c.arguments}} for c in calls],
    }


async def run_conversation(
    llm: LLMClient,
    bridge: McpBridge,
    trip_id: str,
    history: list[dict[str, str]],
    max_steps: int,
    today: date | None = None,
) -> AssistantResult:
    tools = await bridge.model_tools()
    logs: list[ToolCallLog] = []
    context: list[str] = []
    for number, name in enumerate(PREFETCH):
        if name not in bridge.tool_names:
            continue
        log, text = await execute(ToolCall(f"prefetch_{number}", name, json.dumps({"trip_id": trip_id})), bridge, trip_id)
        log.prefetched = True
        logs.append(log)
        context.append(f"{name}: {text}" if log.ok else f"{name} failed: {log.error} (call it yourself if you still need it)")
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt(trip_id, today or date.today(), "\n".join(context))},
        *history,
    ]
    for step in range(1, max_steps + 1):
        last = step == max_steps
        reply = await llm.chat(messages, None if last else tools)  # the last call has no tools: it must answer
        if not reply.tool_calls:
            content = (reply.content or "").strip()
            if not content:
                raise AssistantError(502, "ASSISTANT_BAD_RESPONSE", "The model sent an empty answer. Please try again.")
            logger.info("assistant answered in %d step(s) with %d tool call(s)", step, len(logs))
            return AssistantResult(content, logs, step)
        if last:
            break
        calls = [ToolCall(c.id or f"call_{step}_{n}", c.name, c.arguments) for n, c in enumerate(reply.tool_calls)]
        messages.append(assistant_message(reply.content, calls))
        for number, call in enumerate(calls):
            if number >= MAX_CALLS_PER_STEP:
                log, text = failed(call.name, {}, "Too many tool calls at once; ask for fewer.")
            else:
                log, text = await execute(call, bridge, trip_id)
            logs.append(log)
            messages.append({"role": "tool", "tool_call_id": call.id, "content": text})
    logger.warning("assistant stopped after %d step(s) without an answer", max_steps)
    return AssistantResult(
        "I could not finish an answer within the allowed number of steps. Please ask a narrower question "
        "(for example one category or one destination).",
        logs,
        max_steps,
        incomplete=True,
    )
