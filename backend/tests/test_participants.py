import pytest

from tests.conftest import VALID_TRIP, login


def make_trip(client, owner="alice"):
    headers = login(client, owner)
    trip = client.post("/trips", json=VALID_TRIP, headers=headers).json()
    return headers, trip["id"]


def members(client, headers, trip_id) -> dict[str, str]:
    response = client.get(f"/trips/{trip_id}/participants", headers=headers)
    assert response.status_code == 200
    return {p["username"]: p["role"] for p in response.json()}


def user_id(client, headers, trip_id, username) -> str:
    listed = client.get(f"/trips/{trip_id}/participants", headers=headers).json()
    return next(p["userId"] for p in listed if p["username"] == username)


# --- user search ---


def test_user_search_matches_username_case_insensitively(client):
    headers = login(client, "alice")

    response = client.get("/users", params={"query": "AR"}, headers=headers)

    assert response.status_code == 200
    assert [u["username"] for u in response.json()] == ["carol"]


def test_user_search_returns_public_fields_only(client):
    headers = login(client, "alice")

    users = client.get("/users", params={"query": "a"}, headers=headers).json()

    assert users
    assert all(set(u) == {"id", "username", "displayName"} for u in users)


def test_user_search_requires_login_and_a_query(client):
    headers = login(client, "alice")

    assert client.get("/users", params={"query": "a"}).status_code == 401
    assert client.get("/users", headers=headers).status_code == 400
    assert client.get("/users", params={"query": ""}, headers=headers).status_code == 400


def test_user_search_treats_wildcards_literally_and_limits_results(client):
    headers = login(client, "alice")

    assert client.get("/users", params={"query": "%"}, headers=headers).json() == []
    assert len(client.get("/users", params={"query": "a"}, headers=headers).json()) <= 10


# --- list ---


def test_new_trip_has_only_the_organizer(client):
    headers, trip_id = make_trip(client)

    listed = client.get(f"/trips/{trip_id}/participants", headers=headers).json()

    assert [(p["username"], p["role"]) for p in listed] == [("alice", "organizer")]
    assert set(listed[0]) == {"userId", "username", "displayName", "role"}


# --- add ---


@pytest.mark.parametrize("role", ["editor", "viewer"])
def test_organizer_adds_participant(client, role):
    headers, trip_id = make_trip(client)

    response = client.post(
        f"/trips/{trip_id}/participants", json={"username": "bob", "role": role}, headers=headers
    )

    assert response.status_code == 201
    assert response.json()["role"] == role
    assert members(client, headers, trip_id) == {"alice": "organizer", "bob": role}


def test_added_participant_sees_trip_with_their_role(client):
    headers, trip_id = make_trip(client)
    client.post(f"/trips/{trip_id}/participants", json={"username": "bob", "role": "viewer"}, headers=headers)
    bob = login(client, "bob")

    listed = client.get("/trips", headers=bob).json()

    assert [(t["id"], t["role"]) for t in listed] == [(trip_id, "viewer")]


def test_add_is_case_insensitive_on_username(client):
    headers, trip_id = make_trip(client)

    response = client.post(
        f"/trips/{trip_id}/participants", json={"username": " BOB ", "role": "viewer"}, headers=headers
    )

    assert response.status_code == 201


def test_adding_twice_is_409(client):
    headers, trip_id = make_trip(client)
    body = {"username": "bob", "role": "viewer"}
    client.post(f"/trips/{trip_id}/participants", json=body, headers=headers)

    response = client.post(f"/trips/{trip_id}/participants", json={**body, "role": "editor"}, headers=headers)

    assert response.status_code == 409
    assert response.json()["code"] == "ALREADY_PARTICIPANT"
    assert members(client, headers, trip_id)["bob"] == "viewer"


def test_adding_the_organizer_again_is_409(client):
    headers, trip_id = make_trip(client)

    response = client.post(
        f"/trips/{trip_id}/participants", json={"username": "alice", "role": "viewer"}, headers=headers
    )

    assert response.status_code == 409
    assert members(client, headers, trip_id) == {"alice": "organizer"}


def test_unknown_username_is_400_on_username_field(client):
    headers, trip_id = make_trip(client)

    response = client.post(
        f"/trips/{trip_id}/participants", json={"username": "zed", "role": "viewer"}, headers=headers
    )

    assert response.status_code == 400
    assert response.json()["details"]["fields"]["username"]


@pytest.mark.parametrize("role", ["organizer", "admin", "", None])
def test_invalid_role_is_400_on_role_field(client, role):
    headers, trip_id = make_trip(client)

    response = client.post(
        f"/trips/{trip_id}/participants", json={"username": "bob", "role": role}, headers=headers
    )

    assert response.status_code == 400
    assert response.json()["details"]["fields"]["role"]
    assert members(client, headers, trip_id) == {"alice": "organizer"}


# --- change role ---


def test_organizer_changes_role(client):
    headers, trip_id = make_trip(client)
    client.post(f"/trips/{trip_id}/participants", json={"username": "bob", "role": "viewer"}, headers=headers)
    bob_id = user_id(client, headers, trip_id, "bob")

    response = client.put(f"/trips/{trip_id}/participants/{bob_id}", json={"role": "editor"}, headers=headers)

    assert response.status_code == 200
    assert response.json()["role"] == "editor"
    assert members(client, headers, trip_id)["bob"] == "editor"


@pytest.mark.parametrize("role", ["organizer", "owner"])
def test_change_to_invalid_role_is_400(client, role):
    headers, trip_id = make_trip(client)
    client.post(f"/trips/{trip_id}/participants", json={"username": "bob", "role": "viewer"}, headers=headers)
    bob_id = user_id(client, headers, trip_id, "bob")

    response = client.put(f"/trips/{trip_id}/participants/{bob_id}", json={"role": role}, headers=headers)

    assert response.status_code == 400
    assert members(client, headers, trip_id)["bob"] == "viewer"


def test_change_role_of_someone_not_on_the_trip_is_404(client):
    headers, trip_id = make_trip(client)
    carol_id = login_user_id(client, "carol")

    response = client.put(f"/trips/{trip_id}/participants/{carol_id}", json={"role": "viewer"}, headers=headers)

    assert response.status_code == 404


def login_user_id(client, username) -> str:
    return next(u["id"] for u in client.get("/auth/users").json() if u["username"] == username)


# --- remove ---


def test_organizer_removes_participant(client):
    headers, trip_id = make_trip(client)
    client.post(f"/trips/{trip_id}/participants", json={"username": "bob", "role": "editor"}, headers=headers)
    bob_id = user_id(client, headers, trip_id, "bob")

    response = client.delete(f"/trips/{trip_id}/participants/{bob_id}", headers=headers)

    assert response.status_code == 204
    assert members(client, headers, trip_id) == {"alice": "organizer"}
    assert client.delete(f"/trips/{trip_id}/participants/{bob_id}", headers=headers).status_code == 404


def test_organizer_row_is_protected(client):
    headers, trip_id = make_trip(client)
    alice_id = user_id(client, headers, trip_id, "alice")

    changed = client.put(f"/trips/{trip_id}/participants/{alice_id}", json={"role": "viewer"}, headers=headers)
    removed = client.delete(f"/trips/{trip_id}/participants/{alice_id}", headers=headers)

    assert changed.status_code == 400
    assert changed.json()["code"] == "ORGANIZER_PROTECTED"
    assert removed.status_code == 400
    assert members(client, headers, trip_id) == {"alice": "organizer"}


def test_participant_changes_do_not_change_the_trip_version(client):
    headers, trip_id = make_trip(client)

    client.post(f"/trips/{trip_id}/participants", json={"username": "bob", "role": "viewer"}, headers=headers)

    assert client.get(f"/trips/{trip_id}", headers=headers).json()["version"] == 1
