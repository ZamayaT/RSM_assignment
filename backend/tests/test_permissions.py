import pytest

from tests.conftest import VALID_TRIP, login

MISSING_USER = "00000000-0000-0000-0000-000000000000"


@pytest.fixture
def shared_trip(client):
    """alice's trip shared with bob (viewer) and carol (editor)."""
    alice = login(client, "alice")
    trip_id = client.post("/trips", json=VALID_TRIP, headers=alice).json()["id"]
    client.post(f"/trips/{trip_id}/participants", json={"username": "bob", "role": "viewer"}, headers=alice)
    client.post(f"/trips/{trip_id}/participants", json={"username": "carol", "role": "editor"}, headers=alice)
    return {
        "id": trip_id,
        "alice": alice,
        "bob": login(client, "bob"),
        "carol": login(client, "carol"),
    }


def update(client, trip, who, version=1, name="Changed"):
    return client.put(f"/trips/{trip['id']}", json={**VALID_TRIP, "name": name, "version": version}, headers=trip[who])


def manage_calls(client, trip, who):
    """Every participant-management call, made as `who`; returns the status codes."""
    base = f"/trips/{trip['id']}/participants"
    headers = trip[who]
    return [
        client.post(base, json={"username": "bob", "role": "editor"}, headers=headers).status_code,
        client.put(f"{base}/{MISSING_USER}", json={"role": "viewer"}, headers=headers).status_code,
        client.delete(f"{base}/{MISSING_USER}", headers=headers).status_code,
    ]


# --- viewer ---


def test_viewer_can_read_trip_and_participants(client, shared_trip):
    trip = client.get(f"/trips/{shared_trip['id']}", headers=shared_trip["bob"])
    people = client.get(f"/trips/{shared_trip['id']}/participants", headers=shared_trip["bob"])

    assert trip.status_code == 200
    assert trip.json()["role"] == "viewer"
    assert people.status_code == 200
    assert len(people.json()) == 3


def test_viewer_cannot_edit_trip(client, shared_trip):
    response = update(client, shared_trip, "bob")

    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN"
    current = client.get(f"/trips/{shared_trip['id']}", headers=shared_trip["alice"]).json()
    assert current["name"] == VALID_TRIP["name"]
    assert current["version"] == 1


def test_viewer_cannot_manage_participants(client, shared_trip):
    assert manage_calls(client, shared_trip, "bob") == [403, 403, 403]


# --- editor ---


def test_editor_can_edit_trip(client, shared_trip):
    response = update(client, shared_trip, "carol")

    assert response.status_code == 200
    assert response.json()["version"] == 2
    assert response.json()["role"] == "editor"


def test_editor_cannot_manage_participants(client, shared_trip):
    assert manage_calls(client, shared_trip, "carol") == [403, 403, 403]


def test_editor_cannot_promote_themselves(client, shared_trip):
    carol_id = next(
        p["userId"]
        for p in client.get(f"/trips/{shared_trip['id']}/participants", headers=shared_trip["carol"]).json()
        if p["username"] == "carol"
    )

    response = client.put(
        f"/trips/{shared_trip['id']}/participants/{carol_id}", json={"role": "editor"}, headers=shared_trip["carol"]
    )

    assert response.status_code == 403


# --- non-participant ---


def test_non_participant_gets_404_everywhere(client):
    alice = login(client, "alice")
    carol = login(client, "carol")
    trip_id = client.post("/trips", json=VALID_TRIP, headers=alice).json()["id"]
    trip = {"id": trip_id, "carol": carol}

    assert client.get(f"/trips/{trip_id}", headers=carol).status_code == 404
    assert client.get(f"/trips/{trip_id}/participants", headers=carol).status_code == 404
    assert update(client, trip, "carol").status_code == 404
    assert manage_calls(client, trip, "carol") == [404, 404, 404]


def test_unauthenticated_requests_get_401_on_participant_endpoints(client, shared_trip):
    base = f"/trips/{shared_trip['id']}/participants"

    assert client.get(base).status_code == 401
    assert client.post(base, json={"username": "bob", "role": "viewer"}).status_code == 401
    assert client.put(f"{base}/{MISSING_USER}", json={"role": "viewer"}).status_code == 401
    assert client.delete(f"{base}/{MISSING_USER}").status_code == 401


# --- changes take effect immediately ---


def test_role_change_takes_effect_on_the_next_request(client, shared_trip):
    base = f"/trips/{shared_trip['id']}/participants"
    bob_id = next(p["userId"] for p in client.get(base, headers=shared_trip["alice"]).json() if p["username"] == "bob")
    assert update(client, shared_trip, "bob").status_code == 403

    client.put(f"{base}/{bob_id}", json={"role": "editor"}, headers=shared_trip["alice"])

    assert update(client, shared_trip, "bob").status_code == 200

    client.put(f"{base}/{bob_id}", json={"role": "viewer"}, headers=shared_trip["alice"])

    assert update(client, shared_trip, "bob", version=2, name="Again").status_code == 403


def test_removed_user_loses_access_immediately(client, shared_trip):
    base = f"/trips/{shared_trip['id']}/participants"
    carol_id = next(
        p["userId"] for p in client.get(base, headers=shared_trip["alice"]).json() if p["username"] == "carol"
    )
    assert client.get(f"/trips/{shared_trip['id']}", headers=shared_trip["carol"]).status_code == 200

    client.delete(f"{base}/{carol_id}", headers=shared_trip["alice"])

    assert client.get(f"/trips/{shared_trip['id']}", headers=shared_trip["carol"]).status_code == 404
    assert client.get(base, headers=shared_trip["carol"]).status_code == 404
    assert update(client, shared_trip, "carol").status_code == 404
    assert client.get("/trips", headers=shared_trip["carol"]).json() == []


def test_organizer_keeps_full_access(client, shared_trip):
    assert update(client, shared_trip, "alice").status_code == 200
    assert client.post(
        f"/trips/{shared_trip['id']}/participants", json={"username": "alice", "role": "viewer"}, headers=shared_trip["alice"]
    ).status_code == 409
