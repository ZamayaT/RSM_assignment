"""Helpers to call the MCP endpoint (`/mcp`) of the test app with plain JSON-RPC over HTTP.

The server is stateless with JSON responses, so one POST is one tool call. This is the wire format any MCP client uses.
"""
import json
from typing import Any

HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


def rpc(client, method: str, params: dict | None = None, token_header: dict[str, str] | None = None):
    body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
    return client.post("/mcp", json=body, headers={**HEADERS, **(token_header or {})})


def list_tools(client, auth: dict[str, str]) -> list[dict[str, Any]]:
    response = rpc(client, "tools/list", token_header=auth)
    assert response.status_code == 200, response.text
    return response.json()["result"]["tools"]


def call_tool(client, auth: dict[str, str] | None, name: str, arguments: dict[str, Any]) -> tuple[bool, Any]:
    """(ok, data): the parsed JSON result when the tool succeeded, the error text when it failed."""
    response = rpc(client, "tools/call", {"name": name, "arguments": arguments}, auth)
    assert response.status_code == 200, response.text
    result = response.json()["result"]
    text = "\n".join(part["text"] for part in result["content"] if part.get("text"))
    if result.get("isError"):
        return False, text
    data = result.get("structuredContent")
    return True, data if data is not None else json.loads(text)
