from decimal import Decimal

import pytest
from sqlalchemy import text

from app.db import get_engine
from tests.conftest import VALID_TRIP, login


def assert_error_shape(body: dict, code: str):
    assert body["code"] == code
    assert body["message"]
    assert body["requestId"].startswith("req-")
    assert "details" in body


# --- authentication ---


def test_users_list_is_public_and_seeded(client):
    response = client.get("/auth/users")

    assert response.status_code == 200
    assert [u["username"] for u in response.json()] == ["alice", "bob", "carol"]


def test_login_returns_token_and_me_works(client):
    response = client.post("/auth/login", json={"username": " Alice "})

    assert response.status_code == 200
    body = response.json()
    assert body["user"]["username"] == "alice"
    me = client.get("/auth/me", headers={"Authorization": f"Bearer {body['token']}"})
    assert me.status_code == 200
    assert me.json()["username"] == "alice"


def test_login_unknown_user_is_401(client):
    response = client.post("/auth/login", json={"username": "mallory"})

    assert response.status_code == 401
    assert_error_shape(response.json(), "UNAUTHORIZED")


def test_login_without_username_is_400_with_field(client):
    response = client.post("/auth/login", json={})

    assert response.status_code == 400
    assert "username" in response.json()["details"]["fields"]


@pytest.mark.parametrize(
    "headers",
    [{}, {"Authorization": "Bearer not-a-real-token"}, {"Authorization": "Basic abc"}],
    ids=["missing", "unknown", "wrong-scheme"],
)
@pytest.mark.parametrize("method,path", [("get", "/auth/me"), ("get", "/trips"), ("post", "/trips")])
def test_protected_endpoints_return_401(client, headers, method, path):
    response = getattr(client, method)(path, headers=headers)

    assert response.status_code == 401
    assert_error_shape(response.json(), "UNAUTHORIZED")


def test_unknown_route_uses_error_format(client):
    response = client.get("/nope")

    assert response.status_code == 404
    assert_error_shape(response.json(), "NOT_FOUND")


# --- validation (400 with a message per field) ---


@pytest.mark.parametrize(
    "field,changes",
    [
        ("name", {"name": ""}),
        ("name", {"name": "   "}),
        ("name", {"name": "x" * 121}),
        ("destinations", {"destinations": []}),
        ("destinations", {"destinations": ["Oslo"]}),
        ("startDate", {"startDate": "not-a-date"}),
        ("endDate", {"endDate": "2026-06-30"}),
        ("travelers", {"travelers": 0}),
        ("travelers", {"travelers": 21}),
        ("budget", {"budget": "-1.00"}),
        ("budget", {"budget": "10.123"}),
        ("budget", {"budget": "abc"}),
        ("notes", {"notes": "n" * 2001}),
    ],
)
def test_invalid_field_is_rejected_with_message(client, field, changes):
    headers = login(client, "alice")

    response = client.post("/trips", json={**VALID_TRIP, **changes}, headers=headers)

    assert response.status_code == 400
    body = response.json()
    assert_error_shape(body, "VALIDATION_ERROR")
    assert body["details"]["fields"][field]
    assert client.get("/trips", headers=headers).json() == []


@pytest.mark.parametrize("field", ["name", "destinations", "startDate", "endDate", "travelers", "budget"])
def test_missing_required_field_is_rejected(client, field):
    headers = login(client, "alice")
    payload = {k: v for k, v in VALID_TRIP.items() if k != field}

    response = client.post("/trips", json=payload, headers=headers)

    assert response.status_code == 400
    assert field in response.json()["details"]["fields"]


def test_several_errors_are_reported_together(client):
    headers = login(client, "alice")

    response = client.post("/trips", json={**VALID_TRIP, "name": "", "travelers": 0}, headers=headers)

    assert set(response.json()["details"]["fields"]) == {"name", "travelers"}


# --- create / list / get ---


def test_create_trip_makes_creator_organizer_at_version_1(client):
    headers = login(client, "alice")

    response = client.post("/trips", json=VALID_TRIP, headers=headers)

    assert response.status_code == 201
    trip = response.json()
    assert trip["role"] == "organizer"
    assert trip["version"] == 1
    assert trip["name"] == "Summer in Lisbon"
    assert trip["destinations"] == ["Lisbon"]
    with get_engine().connect() as connection:
        roles = connection.execute(text("SELECT role FROM trip_participants")).scalars().all()
    assert roles == ["organizer"]


def test_create_trip_normalizes_input(client):
    headers = login(client, "alice")
    payload = {**VALID_TRIP, "name": "  Trim me  ", "destinations": ["Rome", "Paris", "Rome"], "notes": "   "}

    trip = client.post("/trips", json=payload, headers=headers).json()

    assert trip["name"] == "Trim me"
    assert trip["destinations"] == ["Rome", "Paris"]
    assert trip["notes"] is None


def test_list_and_get_return_the_trip_with_role(client):
    headers = login(client, "alice")
    created = client.post("/trips", json=VALID_TRIP, headers=headers).json()

    listed = client.get("/trips", headers=headers).json()
    fetched = client.get(f"/trips/{created['id']}", headers=headers)

    assert [t["id"] for t in listed] == [created["id"]]
    assert listed[0]["role"] == "organizer"
    assert fetched.status_code == 200
    assert fetched.json() == created


# --- visibility ---


def test_users_only_see_their_own_trips(client):
    alice = login(client, "alice")
    bob = login(client, "bob")
    alice_trip = client.post("/trips", json=VALID_TRIP, headers=alice).json()
    bob_trip = client.post("/trips", json={**VALID_TRIP, "name": "Bob's trip"}, headers=bob).json()

    assert [t["id"] for t in client.get("/trips", headers=alice).json()] == [alice_trip["id"]]
    assert [t["id"] for t in client.get("/trips", headers=bob).json()] == [bob_trip["id"]]


def test_non_participant_gets_404_not_403(client):
    alice = login(client, "alice")
    bob = login(client, "bob")
    trip = client.post("/trips", json=VALID_TRIP, headers=alice).json()

    response = client.get(f"/trips/{trip['id']}", headers=bob)
    missing = client.get("/trips/00000000-0000-0000-0000-000000000000", headers=bob)

    assert response.status_code == 404
    assert_error_shape(response.json(), "NOT_FOUND")
    # Indistinguishable from a trip that does not exist.
    assert missing.status_code == 404
    assert missing.json()["message"] == response.json()["message"]


def test_non_participant_cannot_update(client):
    alice = login(client, "alice")
    bob = login(client, "bob")
    trip = client.post("/trips", json=VALID_TRIP, headers=alice).json()

    response = client.put(
        f"/trips/{trip['id']}", json={**VALID_TRIP, "name": "Hijacked", "version": 1}, headers=bob
    )

    assert response.status_code == 404
    assert client.get(f"/trips/{trip['id']}", headers=alice).json()["name"] == "Summer in Lisbon"


# --- money exactness ---


@pytest.mark.parametrize("budget", ["0", "0.10", "0.30", "1234.50", "99999999.99", "9999999999.99"])
def test_budget_is_exact(client, budget):
    headers = login(client, "alice")

    created = client.post("/trips", json={**VALID_TRIP, "budget": budget}, headers=headers).json()
    fetched = client.get(f"/trips/{created['id']}", headers=headers).json()

    expected = f"{Decimal(budget):.2f}"
    assert created["budget"] == expected
    assert fetched["budget"] == expected
    with get_engine().connect() as connection:
        stored = connection.execute(text("SELECT budget FROM trips WHERE id = :id"), {"id": created["id"]}).scalar_one()
    assert stored == Decimal(budget)
