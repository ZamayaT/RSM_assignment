"""The read-only MCP layer at `/mcp`: tool list, authentication, permissions, parity with REST, search states.

Uses the real provider mock over HTTP (reset around each test) and the test database.
"""
import ast
import re
import uuid
from pathlib import Path

import pytest

from tests.conftest import login
from tests.itinerary_helpers import add, control, make_trip, mock, offers, share  # noqa: F401 (mock is an autouse fixture)
from tests.mcp_helpers import call_tool, list_tools, rpc

APP_DIR = Path(__file__).resolve().parent.parent / "app"
READ_ONLY_TOOLS = {"get_trip", "get_itinerary", "get_budget", "get_bookings", "search_options"}
SEARCH_ARGS = {"category": "accommodation", "destination": "Lisbon"}


def call_args(name: str, trip_id: str) -> dict:
    return {"trip_id": trip_id, **(SEARCH_ARGS if name == "search_options" else {})}


@pytest.fixture
def shared(client):
    """A trip of alice (organizer) shared with bob (viewer) and carol (editor)."""
    alice, trip_id = make_trip(client)
    share(client, alice, trip_id, "bob", "viewer")
    share(client, alice, trip_id, "carol", "editor")
    return {"alice": alice, "bob": login(client, "bob"), "carol": login(client, "carol"), "trip_id": trip_id}


@pytest.fixture
def stranger(client):
    """A user who is on no trip made by these tests unless a test shares one with them."""
    return login(client, "carol")


# --- the tool list ---


def test_tool_list_is_exactly_the_read_only_set(client, shared):
    tools = list_tools(client, shared["alice"])

    names = {t["name"] for t in tools}
    assert names == READ_ONLY_TOOLS
    assert len(tools) == len(READ_ONLY_TOOLS)
    assert all(re.match(r"(get|search)_", n) for n in names), "only reading verbs"
    assert not [n for n in names if re.search(r"add|create|update|delete|remove|cancel|share|invite|confirm|pay", n)]
    assert all(t["description"] for t in tools)


# --- authentication ---


@pytest.mark.parametrize("header", [{}, {"Authorization": "Bearer not-a-token"}, {"Authorization": "Basic abc"}, {"Authorization": "Bearer "}])
def test_mcp_needs_a_valid_token(client, header):
    response = rpc(client, "tools/list", token_header=header)

    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHORIZED"
    assert response.headers["www-authenticate"] == "Bearer"


def test_a_trip_id_alone_grants_nothing(client, shared):
    response = rpc(client, "tools/call", {"name": "get_trip", "arguments": {"trip_id": shared["trip_id"]}})

    assert response.status_code == 401


# --- permissions ---


@pytest.mark.parametrize("who", ["alice", "carol", "bob"], ids=["organizer", "editor", "viewer"])
@pytest.mark.parametrize("name", sorted(READ_ONLY_TOOLS))
def test_every_participant_can_read(client, shared, who, name):
    ok, data = call_tool(client, shared[who], name, call_args(name, shared["trip_id"]))

    assert ok, data
    if name == "get_trip":
        assert data["role"] == {"alice": "organizer", "carol": "editor", "bob": "viewer"}[who]


@pytest.mark.parametrize("name", sorted(READ_ONLY_TOOLS))
def test_a_non_participant_gets_trip_not_found_from_every_tool(client, stranger, name):
    alice, trip_id = make_trip(client)  # alice's trip; carol (the stranger) is not on it
    missing_ok, missing = call_tool(client, stranger, name, call_args(name, str(uuid.uuid4())))

    ok, text = call_tool(client, stranger, name, call_args(name, trip_id))

    assert not ok and not missing_ok
    assert text == missing  # indistinguishable from a trip that does not exist
    assert "not found" in text.lower()


def test_another_users_token_does_not_open_a_trip(client):
    alice, trip_id = make_trip(client)
    bob = login(client, "bob")

    for name in READ_ONLY_TOOLS:
        ok, text = call_tool(client, bob, name, call_args(name, trip_id))
        assert not ok and "not found" in text.lower()


def test_a_removed_participant_loses_access(client, shared):
    ok, _ = call_tool(client, shared["bob"], "get_trip", {"trip_id": shared["trip_id"]})
    assert ok
    people = client.get(f"/trips/{shared['trip_id']}/participants", headers=shared["alice"]).json()
    bob_id = next(p["userId"] for p in people if p["username"] == "bob")
    assert client.delete(f"/trips/{shared['trip_id']}/participants/{bob_id}", headers=shared["alice"]).status_code == 204

    ok, text = call_tool(client, shared["bob"], "get_trip", {"trip_id": shared["trip_id"]})

    assert not ok and "not found" in text.lower()


def test_an_invalid_trip_id_is_a_tool_error(client, shared):
    ok, text = call_tool(client, shared["alice"], "get_trip", {"trip_id": "not-a-uuid"})

    assert not ok and "trip_id" in text


# --- the tools return what the screens show ---


def test_tool_results_equal_the_rest_responses(client, shared):
    alice, trip_id = shared["alice"], shared["trip_id"]
    offer = offers(client, alice, trip_id)[0]
    version = client.get(f"/trips/{trip_id}", headers=alice).json()["version"]
    assert add(client, alice, trip_id, offer["id"], version).status_code == 201

    for tool, path in [
        ("get_trip", ""),
        ("get_itinerary", "/itinerary"),
        ("get_budget", "/budget"),
        ("get_bookings", "/bookings"),
    ]:
        rest = client.get(f"/trips/{trip_id}{path}", headers=alice)
        assert rest.status_code == 200
        ok, data = call_tool(client, alice, tool, {"trip_id": trip_id})
        assert ok and data == rest.json(), tool


def test_search_options_equals_the_rest_search(client, shared):
    alice, trip_id = shared["alice"], shared["trip_id"]
    rest = client.post(f"/trips/{trip_id}/search", json=SEARCH_ARGS, headers=alice).json()

    ok, data = call_tool(
        client,
        alice,
        "search_options",
        {"trip_id": trip_id, **SEARCH_ARGS, "starts_on": None, "supplier": None},
    )

    assert ok
    assert data["offers"] == rest["offers"] and data["offers"]
    assert data["state"] == "complete" and data["warnings"] == [] and data["searchedAt"]


def test_reading_changes_nothing(client, shared):
    alice, trip_id = shared["alice"], shared["trip_id"]
    before = client.get(f"/trips/{trip_id}", headers=alice).json()

    for name in READ_ONLY_TOOLS:
        call_tool(client, alice, name, call_args(name, trip_id))

    assert client.get(f"/trips/{trip_id}", headers=alice).json() == before
    assert client.get(f"/trips/{trip_id}/itinerary", headers=alice).json()["items"] == []


# --- search states and failures ---


def test_search_options_shows_a_partial_result_with_its_warning(client, shared):
    control("PUT", "/suppliers/supplier-a/failure", mode="unavailable")

    ok, data = call_tool(client, shared["alice"], "search_options", call_args("search_options", shared["trip_id"]))

    assert ok
    assert data["state"] == "partial" and data["offers"]
    assert any(w["providerId"] == "supplier-a" for w in data["warnings"])
    assert "supplier-a" not in {o["providerId"] for o in data["offers"]}


def test_search_options_shows_an_empty_result(client, shared):
    ok, data = call_tool(
        client,
        shared["alice"],
        "search_options",
        {**call_args("search_options", shared["trip_id"]), "starts_on": "2000-01-01", "ends_on": "2000-01-05"},
    )

    assert ok and data["state"] == "empty" and data["offers"] == []


def test_search_options_failures_are_tool_errors(client, shared):
    trip_id = shared["trip_id"]
    alice = shared["alice"]

    outside, text_outside = call_tool(client, alice, "search_options", {"trip_id": trip_id, "category": "accommodation", "destination": "Paris"})
    bad_category, text_category = call_tool(client, alice, "search_options", {"trip_id": trip_id, "category": "spaceship", "destination": "Lisbon"})
    no_origin, text_origin = call_tool(client, alice, "search_options", {"trip_id": trip_id, "category": "transport", "destination": "Lisbon"})

    assert not outside and "destination" in text_outside
    assert not bad_category and "category" in text_category
    assert not no_origin and "origin" in text_origin


def test_all_suppliers_down_is_a_tool_error_not_a_success(client, shared):
    for supplier in ("supplier-a", "supplier-b", "supplier-c"):
        control("PUT", f"/suppliers/{supplier}/failure", mode="unavailable")

    ok, text = call_tool(client, shared["alice"], "search_options", call_args("search_options", shared["trip_id"]))

    assert not ok and text


# --- the dependency rule ---

WRITE_MODULES = {
    "app.booking_steps",
    "app.document_steps",
    "app.documents",
    "app.document_storage",
    "app.document_render",
    "app.document_snapshot",
    "app.participants",
    "app.worker",
    "app.seed",
    "app.provider_client",  # provider access goes through the search code
}
WRITE_CALLS = re.compile(r"\.(add|add_all|delete|commit|merge|flush|execute)\(|\b(insert|update|delete)\(")


def source_files(package: str) -> list[Path]:
    return sorted((APP_DIR / package).glob("*.py"))


def imported_modules(path: Path) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
            found.update(f"{node.module}.{alias.name}" for alias in node.names)
    return found


@pytest.mark.parametrize("package", ["mcp_server", "assistant"])
def test_mcp_and_assistant_import_no_write_module(package):
    files = source_files(package)
    assert files
    for path in files:
        bad = imported_modules(path) & WRITE_MODULES
        assert not bad, f"{path.name} imports {sorted(bad)}"


@pytest.mark.parametrize("package", ["mcp_server", "assistant"])
def test_mcp_and_assistant_contain_no_database_writes(package):
    for path in source_files(package):
        assert not WRITE_CALLS.search(path.read_text(encoding="utf-8")), path.name
