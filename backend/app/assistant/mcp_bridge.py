"""The assistant's connection to the MCP tools: discover them, call them with the user's own token.

The tools are reached over HTTP at `MCP_URL`, the same way any MCP client would, so every call goes through the
server's authentication and permission checks. The model never chooses who it acts as: the token is the user's.
"""
import json
import time
from dataclasses import dataclass
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from app.assistant.llm_client import AssistantError

MAX_RESULT_CHARS = 16000  # what the model gets back from one tool call (bounds tokens and cost)


@dataclass
class ToolResult:
    ok: bool
    text: str  # what the model is told (the JSON result, or the error message)
    data: Any  # the parsed result, for the summary shown to the user
    error: str | None
    duration_ms: int


class McpBridge:
    def __init__(self, url: str, token_header: str, timeout: float = 30):
        self.url = url
        self.token_header = token_header
        self.timeout = timeout
        self._stack: Any = None
        self._session: ClientSession | None = None
        self.tool_names: set[str] = set()

    async def __aenter__(self) -> "McpBridge":
        from contextlib import AsyncExitStack

        stack = AsyncExitStack()
        try:
            read, write, _ = await stack.enter_async_context(
                streamablehttp_client(self.url, headers={"Authorization": self.token_header}, timeout=self.timeout)
            )
            self._session = await stack.enter_async_context(ClientSession(read, write))
            await self._session.initialize()
        except BaseException as exc:
            await stack.aclose()
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            raise AssistantError(
                502, "ASSISTANT_TOOLS_UNAVAILABLE", "The assistant could not reach its read-only tools. Please try again later."
            ) from exc
        self._stack = stack
        return self

    async def __aexit__(self, *exc_info) -> None:
        if self._stack is not None:
            await self._stack.aclose()

    async def model_tools(self) -> list[dict[str, Any]]:
        """The tools in the chat API's function format (discovered from the server, never hard-coded)."""
        assert self._session is not None
        listed = await self._session.list_tools()
        self.tool_names = {t.name for t in listed.tools}
        return [
            {"type": "function", "function": {"name": t.name, "description": t.description or "", "parameters": t.inputSchema}}
            for t in listed.tools
        ]

    async def call(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        assert self._session is not None
        started = time.monotonic()
        try:
            result = await self._session.call_tool(name, arguments)
        except Exception as exc:  # transport trouble: a failed tool call, not a crash
            return ToolResult(False, "The tool could not be reached.", None, f"The tool could not be reached ({exc.__class__.__name__}).", _ms(started))
        text = "\n".join(part.text for part in result.content if getattr(part, "text", None))
        if result.isError:
            message = text.removeprefix(f"Error executing tool {name}: ") or "The tool failed."
            return ToolResult(False, message, None, message, _ms(started))
        data = result.structuredContent if result.structuredContent is not None else _parse(text)
        body = json.dumps(data, ensure_ascii=False, separators=(",", ":")) if data is not None else text
        if len(body) > MAX_RESULT_CHARS:
            body = body[:MAX_RESULT_CHARS] + '..."[truncated: the result was too long]"'
        return ToolResult(True, body, data, None, _ms(started))


def _ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def _parse(text: str) -> Any:
    try:
        return json.loads(text)
    except ValueError:
        return None
