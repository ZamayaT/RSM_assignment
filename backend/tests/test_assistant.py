"""The assistant's own code: the conversation loop, the endpoint, the error mapping.

IMPORTANT: the model here is a SCRIPTED client that replays fixed replies. These tests check our code (tool execution,
step limit, failures, trip restriction, status codes, nothing written). They say nothing about how well a real model
recommends; that evidence is `python -m evals.assistant`. The tools themselves are the real MCP tools of the test app.
"""
import asyncio
import json
import uuid
from typing import Any

import anyio
import httpx
import pytest
from mcp import types
from pydantic import SecretStr
from sqlalchemy import text

from app.assistant import llm_client, router
from app.assistant.conversation import MAX_CALLS_PER_STEP, run_conversation
from app.assistant.llm_client import AssistantError, LLMReply, ToolCall
from app.assistant.mcp_bridge import McpBridge
from app.db import get_engine
from app.main import app
from tests.conftest import login
from tests.itinerary_helpers import control, make_trip, mock, share  # noqa: F401 (mock is an autouse fixture)
from tests.mcp_helpers import rpc

ASK = [{"role": "user", "content": "What is the cheapest hotel in Lisbon?"}]
SEARCH = {"category": "accommodation", "destination": "Lisbon"}


# --- scripted model and a bridge to the test app's real MCP endpoint ---


class ScriptedLLM:
    """Replays fixed replies (a reply may be an exception to raise) and records what it was asked."""

    def __init__(self, *replies: LLMReply | Exception):
        self.replies = list(replies)
        self.requests: list[tuple[list[dict[str, Any]], list[dict[str, Any]] | None]] = []

    async def chat(self, messages, tools):
        self.requests.append(([dict(m) for m in messages], tools))
        reply = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        if isinstance(reply, Exception):
            raise reply
        return reply


def say(content: str) -> LLMReply:
    return LLMReply(content=content)


def use(name: str, arguments: dict[str, Any] | str, call_id: str = "c1") -> LLMReply:
    raw = arguments if isinstance(arguments, str) else json.dumps(arguments)
    return LLMReply(content=None, tool_calls=[ToolCall(call_id, name, raw)])


class HttpSession:
    """Stands in for the MCP client session: the same JSON-RPC requests, sent to the test app instead of the network."""

    def __init__(self, client, auth: dict[str, str]):
        self.client, self.auth = client, auth
        self.calls: list[str] = []

    async def _rpc(self, method: str, params: dict | None = None) -> dict:
        response = await anyio.to_thread.run_sync(lambda: rpc(self.client, method, params, self.auth))
        assert response.status_code == 200, response.text
        return response.json()["result"]

    async def list_tools(self):
        return types.ListToolsResult.model_validate(await self._rpc("tools/list"))

    async def call_tool(self, name, arguments):
        self.calls.append(name)
        return types.CallToolResult.model_validate(await self._rpc("tools/call", {"name": name, "arguments": arguments}))


def make_bridge(client, auth: dict[str, str]) -> McpBridge:
    bridge = McpBridge("http://test/mcp", auth["Authorization"])
    bridge._session = HttpSession(client, auth)  # type: ignore[assignment]
    return bridge


def converse(client, auth, trip_id, llm, max_steps=6, history=ASK):
    async def run():
        bridge = make_bridge(client, auth)
        await bridge.model_tools()
        return await run_conversation(llm, bridge, trip_id, history, max_steps), bridge._session.calls

    return asyncio.run(run())


@pytest.fixture
def trip(client):
    alice, trip_id = make_trip(client)
    share(client, alice, trip_id, "bob", "viewer")
    return {"alice": alice, "bob": login(client, "bob"), "carol": login(client, "carol"), "id": trip_id}


# --- the loop ---


def test_tools_are_executed_and_their_results_fed_back(client, trip):
    llm = ScriptedLLM(use("search_options", SEARCH | {"trip_id": trip["id"]}), say("Cheapest: see the list."))

    result, mcp_calls = converse(client, trip["alice"], trip["id"], llm)

    assert result.reply == "Cheapest: see the list." and result.steps == 2 and not result.incomplete
    assert [(c.name, c.ok, c.prefetched) for c in result.tool_calls] == [
        ("get_trip", True, True),
        ("get_budget", True, True),
        ("search_options", True, False),
    ]
    assert mcp_calls == ["get_trip", "get_budget", "search_options"]
    assert result.tool_calls[2].arguments["trip_id"] == trip["id"] and result.tool_calls[2].summary.startswith("complete:")
    second_request = llm.requests[1][0]
    assert second_request[-2]["tool_calls"][0]["function"]["name"] == "search_options"
    assert second_request[-1]["role"] == "tool" and json.loads(second_request[-1]["content"])["offers"]
    assert trip["id"] in second_request[0]["content"] and "Summer in Lisbon" in second_request[0]["content"]  # prefetched context
    assert llm.requests[0][1], "tools are offered to the model"


def test_the_trip_id_is_filled_in_when_the_model_leaves_it_out(client, trip):
    llm = ScriptedLLM(use("get_itinerary", {}), say("Empty itinerary."))

    result, _ = converse(client, trip["alice"], trip["id"], llm)

    assert result.tool_calls[-1].ok and result.tool_calls[-1].arguments == {"trip_id": trip["id"]}


def test_the_step_limit_stops_a_loop(client, trip):
    llm = ScriptedLLM(use("get_itinerary", {"trip_id": trip["id"]}))  # asks again, forever

    result, _ = converse(client, trip["alice"], trip["id"], llm, max_steps=3)

    assert result.incomplete and result.steps == 3 and len(llm.requests) == 3
    assert "could not finish" in result.reply
    assert llm.requests[-1][1] is None, "the last call has no tools, so the model must answer"
    assert llm.requests[0][1] and llm.requests[1][1]


def test_a_tool_failure_is_shown_as_failed_and_reaches_the_model(client, trip):
    llm = ScriptedLLM(use("search_options", {"trip_id": trip["id"], "category": "accommodation", "destination": "Paris"}), say("Search failed."))

    result, _ = converse(client, trip["alice"], trip["id"], llm)

    failure = result.tool_calls[-1]
    assert not failure.ok and failure.summary == "failed" and "destination" in failure.error and failure.result is None
    fed_back = llm.requests[1][0][-1]
    assert fed_back["role"] == "tool" and fed_back["content"].startswith("ERROR:") and "destination" in fed_back["content"]
    assert result.reply == "Search failed."  # the loop does not invent a success


def test_a_partial_search_is_passed_through_as_partial(client, trip):
    control("PUT", "/suppliers/supplier-alamo/failure", mode="unavailable")
    llm = ScriptedLLM(use("search_options", SEARCH | {"trip_id": trip["id"]}), say("Supplier A was down."))

    result, _ = converse(client, trip["alice"], trip["id"], llm)

    assert result.tool_calls[-1].ok and result.tool_calls[-1].summary.startswith("partial:")
    assert "supplier-alamo" in llm.requests[1][0][-1]["content"]


def test_another_trip_is_rejected_even_if_the_user_can_read_it(client, trip):
    _, other_id = make_trip(client)  # a second trip of alice
    assert client.get(f"/trips/{other_id}", headers=trip["alice"]).status_code == 200
    llm = ScriptedLLM(use("get_trip", {"trip_id": other_id}), say("Cannot."))

    result, mcp_calls = converse(client, trip["alice"], trip["id"], llm)

    rejected = result.tool_calls[-1]
    assert not rejected.ok and "other trips cannot be read" in rejected.error
    assert mcp_calls == ["get_trip", "get_budget"], "the rejected call never reached the tools"
    assert "cannot be read" in llm.requests[1][0][-1]["content"]


@pytest.mark.parametrize(
    "reply, expected",
    [
        (use("delete_trip", {"trip_id": "x"}), "Unknown tool"),
        (use("book_offer", {}), "Unknown tool"),
        (use("get_itinerary", "{not json"), "not valid JSON"),
        (use("get_itinerary", '["a list"]'), "JSON object"),
        (use("", ""), "Unknown tool"),
    ],
    ids=["unknown-modifying-tool", "unknown-booking-tool", "invalid-json", "not-an-object", "empty-call"],
)
def test_unknown_or_malformed_tool_calls_do_not_crash(client, trip, reply, expected):
    llm = ScriptedLLM(reply, say("Sorry."))

    result, mcp_calls = converse(client, trip["alice"], trip["id"], llm)

    assert result.reply == "Sorry."
    assert not result.tool_calls[-1].ok and expected in result.tool_calls[-1].error
    assert mcp_calls == ["get_trip", "get_budget"]
    assert llm.requests[1][0][-1]["content"].startswith("ERROR:")


def test_too_many_calls_at_once_are_limited(client, trip):
    many = LLMReply(None, [ToolCall(f"c{n}", "get_itinerary", "{}") for n in range(MAX_CALLS_PER_STEP + 2)])
    llm = ScriptedLLM(many, say("Done."))

    result, mcp_calls = converse(client, trip["alice"], trip["id"], llm)

    extra = result.tool_calls[2:]  # after the two prefetched reads
    assert [c.ok for c in extra] == [True] * MAX_CALLS_PER_STEP + [False] * 2
    assert mcp_calls.count("get_itinerary") == MAX_CALLS_PER_STEP


def test_an_empty_answer_is_a_bad_response(client, trip):
    with pytest.raises(AssistantError) as caught:
        converse(client, trip["alice"], trip["id"], ScriptedLLM(say("   ")))

    assert (caught.value.status_code, caught.value.code) == (502, "ASSISTANT_BAD_RESPONSE")


def test_a_non_participant_gets_failed_prefetches_and_nothing_else(client, trip):
    llm = ScriptedLLM(use("get_itinerary", {"trip_id": trip["id"]}), say("I could not read the trip."))

    result, _ = converse(client, trip["carol"], trip["id"], llm)  # carol is not on this trip

    assert [c.ok for c in result.tool_calls] == [False, False, False]
    assert all("not found" in c.error.lower() for c in result.tool_calls)


# --- model errors: provider answers mapped to our statuses and codes ---


def provider(status: int, body: Any = None, headers: dict[str, str] | None = None) -> httpx.Response:
    return httpx.Response(status, json=body, headers=headers or {})


@pytest.mark.parametrize(
    "response, status, code",
    [
        (provider(401, {"error": {"message": "bad key"}}), 502, "ASSISTANT_UNAUTHORIZED"),
        (provider(403), 502, "ASSISTANT_UNAUTHORIZED"),
        (provider(429, {"error": {"message": "slow down"}}), 429, "ASSISTANT_RATE_LIMITED"),
        (provider(500), 502, "ASSISTANT_UNAVAILABLE"),
        (provider(503), 502, "ASSISTANT_UNAVAILABLE"),
        (provider(400, {"error": {"message": "no tools"}}), 502, "ASSISTANT_BAD_RESPONSE"),
        (httpx.Response(200, text="<html>"), 502, "ASSISTANT_BAD_RESPONSE"),
        (provider(200, {"choices": []}), 502, "ASSISTANT_BAD_RESPONSE"),
        (provider(200, {"error": {"code": 429, "message": "busy"}}), 429, "ASSISTANT_RATE_LIMITED"),
    ],
)
def test_provider_answers_map_to_our_status_and_code(response, status, code):
    with pytest.raises(AssistantError) as caught:
        llm_client.parse_reply(response)

    assert (caught.value.status_code, caught.value.code) == (status, code)


def test_rate_limit_keeps_the_retry_after_header():
    with pytest.raises(AssistantError) as caught:
        llm_client.parse_reply(provider(429, None, {"Retry-After": "30"}))

    assert caught.value.headers == {"Retry-After": "30"}


def test_a_good_reply_is_parsed_with_its_tool_calls():
    body = {"choices": [{"message": {"content": None, "tool_calls": [{"id": "a", "function": {"name": "get_trip", "arguments": "{}"}}]}}]}

    reply = llm_client.parse_reply(provider(200, body))

    assert reply.content is None and [(c.id, c.name, c.arguments) for c in reply.tool_calls] == [("a", "get_trip", "{}")]


@pytest.mark.parametrize(
    "error, status, code",
    [(httpx.ReadTimeout("slow"), 504, "ASSISTANT_TIMEOUT"), (httpx.ConnectError("down"), 502, "ASSISTANT_UNAVAILABLE")],
)
def test_timeouts_and_unreachable_providers_map_to_their_codes(monkeypatch, error, status, code):
    def handler(request):
        raise error

    real = httpx.AsyncClient
    monkeypatch.setattr(llm_client.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    client = llm_client.OpenAICompatibleClient("http://llm.test/v1", "secret-key", "m", 1)

    with pytest.raises(AssistantError) as caught:
        asyncio.run(client.chat([{"role": "user", "content": "hi"}], None))

    assert (caught.value.status_code, caught.value.code) == (status, code)
    assert "secret-key" not in caught.value.message


# --- the endpoint ---


@pytest.fixture
def scripted(client):
    """Install a scripted model and make the endpoint reach the tools through the test app. Returns a setter."""
    holder: dict[str, Any] = {}

    class Bridge(McpBridge):
        async def __aenter__(self):
            self._session = HttpSession(client, {"Authorization": self.token_header})
            holder["session"] = self._session
            return self

        async def __aexit__(self, *exc_info):
            return None

    app.dependency_overrides[router.get_llm_factory] = lambda: (lambda: holder["llm"])
    original = router.McpBridge
    router.McpBridge = Bridge  # type: ignore[misc]

    def install(*replies):
        holder["llm"] = ScriptedLLM(*replies)
        return holder["llm"]

    yield install
    router.McpBridge = original  # type: ignore[misc]
    app.dependency_overrides.pop(router.get_llm_factory, None)


def ask(client, trip_id, headers=None, question="Cheapest hotel?"):
    return client.post(f"/trips/{trip_id}/assistant/messages", json={"messages": [{"role": "user", "content": question}]}, headers=headers)


def test_the_endpoint_answers_with_the_tools_used(client, trip, scripted):
    scripted(use("search_options", SEARCH | {"trip_id": trip["id"]}), say("The cheapest is listed in Search."))

    response = ask(client, trip["id"], trip["alice"])

    assert response.status_code == 200
    body = response.json()
    assert body["reply"] == "The cheapest is listed in Search." and body["steps"] == 2 and body["incomplete"] is False
    assert [c["name"] for c in body["toolCalls"]] == ["get_trip", "get_budget", "search_options"]
    assert {"name", "arguments", "ok", "summary", "error", "result", "durationMs", "prefetched"} <= body["toolCalls"][2].keys()
    assert [c["prefetched"] for c in body["toolCalls"]] == [True, True, False]


def test_a_viewer_can_ask(client, trip, scripted):
    scripted(say("Hello viewer."))

    response = ask(client, trip["id"], trip["bob"])

    assert response.status_code == 200 and response.json()["reply"] == "Hello viewer."
    assert [c["ok"] for c in response.json()["toolCalls"]] == [True, True]


def test_a_tool_asked_about_another_trip_shows_as_failed_in_the_response(client, trip, scripted):
    scripted(use("get_trip", {"trip_id": str(uuid.uuid4())}), say("I could not read that."))

    body = ask(client, trip["id"], trip["alice"]).json()

    assert body["toolCalls"][-1]["ok"] is False and body["toolCalls"][-1]["error"]


def test_the_endpoint_needs_login(client, trip, scripted):
    scripted(say("never"))

    assert client.post(f"/trips/{trip['id']}/assistant/messages", json={"messages": [{"role": "user", "content": "hi"}]}).status_code == 401


def test_a_non_participant_and_a_missing_trip_get_404(client, trip, scripted):
    llm = scripted(say("never"))

    assert ask(client, trip["id"], trip["carol"]).status_code == 404
    assert ask(client, str(uuid.uuid4()), trip["alice"]).status_code == 404
    assert llm.requests == [], "the model is never called for a stranger"


def test_the_question_is_validated(client, trip, scripted):
    scripted(say("never"))
    url = f"/trips/{trip['id']}/assistant/messages"

    assert client.post(url, json={"messages": []}, headers=trip["alice"]).status_code == 400
    assert client.post(url, json={"messages": [{"role": "assistant", "content": "hi"}]}, headers=trip["alice"]).status_code == 400
    assert client.post(url, json={"messages": [{"role": "user", "content": "x" * 4001}]}, headers=trip["alice"]).status_code == 400


def test_not_configured_is_503_with_what_to_set(client, trip, monkeypatch):
    settings = llm_client.get_settings().model_copy(update={"llm_api_key": SecretStr(""), "llm_model": ""})
    monkeypatch.setattr(llm_client, "get_settings", lambda: settings)

    response = ask(client, trip["id"], trip["alice"])

    assert response.status_code == 503
    assert response.json()["code"] == "ASSISTANT_NOT_CONFIGURED" and "LLM_API_KEY" in response.json()["message"]


def test_not_configured_is_not_revealed_to_a_stranger(client, trip, monkeypatch):
    settings = llm_client.get_settings().model_copy(update={"llm_api_key": SecretStr(""), "llm_model": ""})
    monkeypatch.setattr(llm_client, "get_settings", lambda: settings)

    assert ask(client, trip["id"], trip["carol"]).status_code == 404


@pytest.mark.parametrize(
    "error, status, code",
    [
        (AssistantError(502, "ASSISTANT_UNAUTHORIZED", "bad key"), 502, "ASSISTANT_UNAUTHORIZED"),
        (AssistantError(429, "ASSISTANT_RATE_LIMITED", "limit", headers={"Retry-After": "12"}), 429, "ASSISTANT_RATE_LIMITED"),
        (AssistantError(504, "ASSISTANT_TIMEOUT", "slow"), 504, "ASSISTANT_TIMEOUT"),
        (AssistantError(502, "ASSISTANT_BAD_RESPONSE", "garbage"), 502, "ASSISTANT_BAD_RESPONSE"),
    ],
)
def test_model_errors_reach_the_user_with_their_status_and_code(client, trip, scripted, error, status, code):
    scripted(error)

    response = ask(client, trip["id"], trip["alice"])

    assert response.status_code == status and response.json()["code"] == code
    assert response.json()["requestId"]
    if error.headers:
        assert response.headers["retry-after"] == "12"


# --- the assistant changes nothing ---


def snapshot(client, headers, trip_id) -> dict[str, Any]:
    with get_engine().connect() as connection:
        counts = {
            table: connection.execute(text(f"SELECT count(*) FROM {table}")).scalar()
            for table in ("trips", "itinerary_items", "booking_attempts", "documents", "trip_participants")
        }
    pages = {path: client.get(f"/trips/{trip_id}{path}", headers=headers).json() for path in ("", "/itinerary", "/budget", "/bookings")}
    return {"counts": counts, "pages": pages}


def test_the_assistant_changes_nothing(client, trip, scripted):
    before = snapshot(client, trip["alice"], trip["id"])
    scripted(
        LLMReply(
            None,
            [
                ToolCall("1", "get_itinerary", "{}"),
                ToolCall("2", "get_bookings", "{}"),
                ToolCall("3", "search_options", json.dumps(SEARCH)),
                ToolCall("4", "book_offer", json.dumps({"offer_id": "x"})),  # does not exist
                ToolCall("5", "add_to_itinerary", json.dumps({"offer_id": "x"})),  # does not exist
            ],
        ),
        say("I cannot book; use the Itinerary tab."),
    )

    response = ask(client, trip["id"], trip["alice"], "Please book the cheapest hotel.")

    assert response.status_code == 200
    assert [c["ok"] for c in response.json()["toolCalls"]][-2:] == [False, False]
    assert snapshot(client, trip["alice"], trip["id"]) == before
