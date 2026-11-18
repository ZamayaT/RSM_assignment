"""Concurrent edits: nothing saved is ever silently lost, and every change tells its writer what happened."""
import threading
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

from app.main import app
from tests.conftest import login
from tests.itinerary_helpers import TRIP, add, itinerary, make_trip, mock, offer_ids, offers, share  # noqa: F401


def two_editors(client):
    """alice (organizer) and carol (editor) on one trip; returns both headers, the trip id and some offers."""
    alice, trip_id = make_trip(client)
    share(client, alice, trip_id, "carol", "editor")
    return alice, login(client, "carol"), trip_id, offers(client, alice, trip_id)


def trip_body(version, **changes):
    return {
        "name": TRIP["name"],
        "destinations": TRIP["destinations"],
        "startDate": TRIP["startDate"],
        "endDate": TRIP["endDate"],
        "travelers": TRIP["travelers"],
        "budget": TRIP["budget"],
        "notes": None,
        "version": version,
        **changes,
    }


def test_version_increases_by_one_per_change(client):
    headers, trip_id = make_trip(client)
    found = offers(client, headers, trip_id)

    versions = [itinerary(client, headers, trip_id)["version"]]
    versions.append(add(client, headers, trip_id, found[0]["id"], versions[-1]).json()["version"])
    versions.append(add(client, headers, trip_id, found[1]["id"], versions[-1]).json()["version"])
    ids = [i["id"] for i in itinerary(client, headers, trip_id)["items"]]
    versions.append(
        client.put(
            f"/trips/{trip_id}/itinerary/order", json={"itemIds": ids[::-1], "version": versions[-1]}, headers=headers
        ).json()["version"]
    )
    versions.append(
        client.delete(f"/trips/{trip_id}/itinerary/{ids[0]}", params={"version": versions[-1]}, headers=headers).json()["version"]
    )

    assert versions == [1, 2, 3, 4, 5]


def test_second_writer_with_a_stale_version_gets_409_with_the_latest_state(client):
    alice, carol, trip_id, found = two_editors(client)
    seen = itinerary(client, carol, trip_id)["version"]  # both have this version open

    assert add(client, alice, trip_id, found[0]["id"], seen).status_code == 201
    response = add(client, carol, trip_id, found[1]["id"], seen)

    assert response.status_code == 409 and response.json()["code"] == "VERSION_CONFLICT"
    latest = response.json()["details"]["latest"]
    assert offer_ids(latest["itinerary"]) == [found[0]["id"]]
    assert latest["itinerary"]["version"] == seen + 1 and latest["trip"]["version"] == seen + 1
    # alice's saved change is still there and carol's refused one was not applied
    assert offer_ids(itinerary(client, alice, trip_id)) == [found[0]["id"]]


def test_reapplying_on_the_latest_version_keeps_both_changes(client):
    alice, carol, trip_id, found = two_editors(client)
    seen = itinerary(client, carol, trip_id)["version"]
    add(client, alice, trip_id, found[0]["id"], seen)
    refused = add(client, carol, trip_id, found[1]["id"], seen)

    latest_version = refused.json()["details"]["latest"]["itinerary"]["version"]
    reapplied = add(client, carol, trip_id, found[1]["id"], latest_version)

    assert reapplied.status_code == 201
    assert sorted(offer_ids(reapplied.json())) == sorted([found[0]["id"], found[1]["id"]])


def test_stale_remove_and_reorder_are_refused_too(client):
    alice, carol, trip_id, found = two_editors(client)
    add(client, alice, trip_id, found[0]["id"], 1)
    body = add(client, alice, trip_id, found[1]["id"], 2).json()
    ids = [i["id"] for i in body["items"]]
    stale = body["version"]
    add(client, alice, trip_id, found[2]["id"], stale)  # carol's view is now one version behind

    removed = client.delete(f"/trips/{trip_id}/itinerary/{ids[0]}", params={"version": stale}, headers=carol)
    reordered = client.put(f"/trips/{trip_id}/itinerary/order", json={"itemIds": ids[::-1], "version": stale}, headers=carol)

    assert (removed.status_code, reordered.status_code) == (409, 409)
    assert len(itinerary(client, alice, trip_id)["items"]) == 3


def test_itinerary_change_and_trip_edit_with_the_same_version_conflict(client):
    alice, carol, trip_id, found = two_editors(client)
    seen = itinerary(client, carol, trip_id)["version"]

    assert add(client, alice, trip_id, found[0]["id"], seen).status_code == 201
    edit = client.put(f"/trips/{trip_id}", json=trip_body(seen, name="Renamed"), headers=carol)

    assert edit.status_code == 409
    assert client.get(f"/trips/{trip_id}", headers=alice).json()["name"] == TRIP["name"]

    # the other way round: a trip edit first makes an itinerary change on the old version stale
    seen = client.get(f"/trips/{trip_id}", headers=alice).json()["version"]
    assert client.put(f"/trips/{trip_id}", json=trip_body(seen, name="Renamed"), headers=carol).status_code == 200
    assert add(client, alice, trip_id, found[1]["id"], seen).status_code == 409


def race(calls):
    """Run the calls at the same moment, each with its own client; returns their responses."""
    barrier = threading.Barrier(len(calls))

    def run(call):
        with TestClient(app) as thread_client:
            barrier.wait()
            return call(thread_client)

    with ThreadPoolExecutor(len(calls)) as pool:
        return [f.result() for f in [pool.submit(run, c) for c in calls]]


def test_two_simultaneous_adds_with_the_same_version_save_exactly_one(client):
    alice, carol, trip_id, found = two_editors(client)
    seen = itinerary(client, alice, trip_id)["version"]

    responses = race(
        [
            lambda c: add(c, alice, trip_id, found[0]["id"], seen),
            lambda c: add(c, carol, trip_id, found[1]["id"], seen),
        ]
    )

    assert sorted(r.status_code for r in responses) == [201, 409]
    body = itinerary(client, alice, trip_id)
    assert len(body["items"]) == 1 and body["version"] == seen + 1
    winner = next(r for r in responses if r.status_code == 201).json()
    assert offer_ids(winner) == offer_ids(body)


def test_simultaneous_itinerary_add_and_trip_edit_save_exactly_one(client):
    alice, carol, trip_id, found = two_editors(client)
    seen = itinerary(client, alice, trip_id)["version"]

    responses = race(
        [
            lambda c: add(c, alice, trip_id, found[0]["id"], seen),
            lambda c: c.put(f"/trips/{trip_id}", json=trip_body(seen, name="Renamed"), headers=carol),
        ]
    )

    assert sorted(r.status_code for r in responses) in ([200, 409], [201, 409])
    assert client.get(f"/trips/{trip_id}", headers=alice).json()["version"] == seen + 1
