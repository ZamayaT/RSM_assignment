from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from fastapi.testclient import TestClient

from app.db import get_engine
from app.main import app
from app.seed import run_seed
from tests.conftest import VALID_TRIP, login


def create_trip(client, headers):
    return client.post("/trips", json=VALID_TRIP, headers=headers).json()


def test_successful_update_increments_version(client):
    headers = login(client, "alice")
    trip = create_trip(client, headers)

    response = client.put(
        f"/trips/{trip['id']}",
        json={**VALID_TRIP, "name": "Renamed", "budget": "2000.5", "version": 1},
        headers=headers,
    )

    assert response.status_code == 200
    updated = response.json()
    assert updated["version"] == 2
    assert updated["name"] == "Renamed"
    assert updated["budget"] == "2000.50"
    assert updated["createdAt"] == trip["createdAt"]
    assert updated["updatedAt"] >= trip["updatedAt"]
    assert client.get(f"/trips/{trip['id']}", headers=headers).json() == updated


def test_consecutive_updates_with_fresh_version_succeed(client):
    headers = login(client, "alice")
    trip = create_trip(client, headers)

    for expected_version in (2, 3, 4):
        response = client.put(
            f"/trips/{trip['id']}",
            json={**VALID_TRIP, "version": expected_version - 1},
            headers=headers,
        )
        assert response.status_code == 200
        assert response.json()["version"] == expected_version


def test_stale_update_gets_409_and_loses_nothing(client):
    headers = login(client, "alice")
    trip = create_trip(client, headers)
    first = client.put(
        f"/trips/{trip['id']}", json={**VALID_TRIP, "name": "First save", "version": 1}, headers=headers
    ).json()

    stale = client.put(
        f"/trips/{trip['id']}", json={**VALID_TRIP, "name": "Stale save", "version": 1}, headers=headers
    )

    assert stale.status_code == 409
    body = stale.json()
    assert body["code"] == "VERSION_CONFLICT"
    assert body["details"]["latest"] == first
    current = client.get(f"/trips/{trip['id']}", headers=headers).json()
    assert current == first
    assert current["name"] == "First save"
    assert current["version"] == 2


def test_future_version_is_also_a_conflict(client):
    headers = login(client, "alice")
    trip = create_trip(client, headers)

    response = client.put(f"/trips/{trip['id']}", json={**VALID_TRIP, "version": 5}, headers=headers)

    assert response.status_code == 409
    assert client.get(f"/trips/{trip['id']}", headers=headers).json()["version"] == 1


def test_update_requires_version_and_valid_fields(client):
    headers = login(client, "alice")
    trip = create_trip(client, headers)

    no_version = client.put(f"/trips/{trip['id']}", json=VALID_TRIP, headers=headers)
    bad_field = client.put(f"/trips/{trip['id']}", json={**VALID_TRIP, "travelers": 0, "version": 1}, headers=headers)

    assert no_version.status_code == 400
    assert "version" in no_version.json()["details"]["fields"]
    assert bad_field.status_code == 400
    assert "travelers" in bad_field.json()["details"]["fields"]
    assert client.get(f"/trips/{trip['id']}", headers=headers).json()["version"] == 1


def test_concurrent_saves_from_same_version_exactly_one_succeeds(client):
    headers = login(client, "alice")
    trip = create_trip(client, headers)
    workers = 6
    barrier = Barrier(workers)

    def save(n: int) -> int:
        with TestClient(app) as own_client:
            barrier.wait()
            return own_client.put(
                f"/trips/{trip['id']}",
                json={**VALID_TRIP, "name": f"Writer {n}", "version": 1},
                headers=headers,
            ).status_code

    with ThreadPoolExecutor(max_workers=workers) as pool:
        statuses = list(pool.map(save, range(workers)))

    assert sorted(statuses) == [200] + [409] * (workers - 1)
    final = client.get(f"/trips/{trip['id']}", headers=headers).json()
    assert final["version"] == 2
    assert final["name"].startswith("Writer ")


def test_trips_and_logins_survive_an_engine_restart(client):
    headers = login(client, "alice")
    trip = create_trip(client, headers)
    client.put(f"/trips/{trip['id']}", json={**VALID_TRIP, "name": "Persisted", "version": 1}, headers=headers)

    # Simulate a backend restart: drop every connection and build a new engine; run startup seeding again.
    get_engine().dispose()
    get_engine.cache_clear()
    run_seed()

    with TestClient(app) as restarted:
        assert len(restarted.get("/auth/users").json()) == 4
        listed = restarted.get("/trips", headers=headers)
        assert listed.status_code == 200
        assert [t["name"] for t in listed.json()] == ["Persisted"]
        assert listed.json()[0]["version"] == 2
