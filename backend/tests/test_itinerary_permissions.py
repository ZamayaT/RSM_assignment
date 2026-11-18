"""Who may read and change an itinerary."""
from tests.itinerary_helpers import add, itinerary, make_trip, mock, offers, share  # noqa: F401
from tests.conftest import login

UNKNOWN_ITEM = "00000000-0000-4000-8000-000000000000"


def seeded_trip(client):
    """alice's trip with one item, bob as viewer and carol as editor."""
    headers, trip_id = make_trip(client)
    found = offers(client, headers, trip_id)
    body = add(client, headers, trip_id, found[0]["id"], 1).json()
    share(client, headers, trip_id, "bob", "viewer")
    share(client, headers, trip_id, "carol", "editor")
    return headers, trip_id, found, body


def writes(client, headers, trip_id, offer_id, item_id, version):
    """The three write requests as (name, response)."""
    return {
        "add": add(client, headers, trip_id, offer_id, version),
        "remove": client.delete(f"/trips/{trip_id}/itinerary/{item_id}", params={"version": version}, headers=headers),
        "reorder": client.put(
            f"/trips/{trip_id}/itinerary/order", json={"itemIds": [item_id], "version": version}, headers=headers
        ),
    }


def test_viewer_can_read_but_every_write_is_403(client):
    owner, trip_id, found, body = seeded_trip(client)
    viewer = login(client, "bob")
    item_id = body["items"][0]["id"]

    assert client.get(f"/trips/{trip_id}/itinerary", headers=viewer).status_code == 200
    assert client.get(f"/trips/{trip_id}/budget", headers=viewer).status_code == 200
    results = writes(client, viewer, trip_id, found[1]["id"], item_id, body["version"])

    assert {name: r.status_code for name, r in results.items()} == {"add": 403, "remove": 403, "reorder": 403}
    assert all(r.json()["code"] == "FORBIDDEN" for r in results.values())
    assert itinerary(client, owner, trip_id) == itinerary(client, viewer, trip_id)
    assert itinerary(client, owner, trip_id)["version"] == body["version"]


def test_editor_can_add_reorder_and_remove(client):
    _, trip_id, found, body = seeded_trip(client)
    editor = login(client, "carol")
    item_id = body["items"][0]["id"]

    added = add(client, editor, trip_id, found[1]["id"], body["version"])
    ids = [i["id"] for i in added.json()["items"]]
    reordered = client.put(
        f"/trips/{trip_id}/itinerary/order", json={"itemIds": ids[::-1], "version": added.json()["version"]}, headers=editor
    )
    removed = client.delete(
        f"/trips/{trip_id}/itinerary/{item_id}", params={"version": reordered.json()["version"]}, headers=editor
    )

    assert (added.status_code, reordered.status_code, removed.status_code) == (201, 200, 200)
    assert len(removed.json()["items"]) == 1


def test_non_participant_gets_404_everywhere(client):
    headers, trip_id = make_trip(client)  # alice only
    found = offers(client, headers, trip_id)
    item_id = add(client, headers, trip_id, found[0]["id"], 1).json()["items"][0]["id"]
    outsider = login(client, "carol")

    responses = [
        client.get(f"/trips/{trip_id}/itinerary", headers=outsider),
        client.get(f"/trips/{trip_id}/budget", headers=outsider),
        *writes(client, outsider, trip_id, found[1]["id"], item_id, 2).values(),
    ]

    assert [r.status_code for r in responses] == [404] * 5


def test_requests_without_login_get_401(client):
    headers, trip_id = make_trip(client)
    item_id = UNKNOWN_ITEM

    responses = [
        client.get(f"/trips/{trip_id}/itinerary"),
        client.get(f"/trips/{trip_id}/budget"),
        client.post(f"/trips/{trip_id}/itinerary", json={"offerId": "x", "version": 1}),
        client.delete(f"/trips/{trip_id}/itinerary/{item_id}", params={"version": 1}),
        client.put(f"/trips/{trip_id}/itinerary/order", json={"itemIds": [], "version": 1}),
    ]

    assert [r.status_code for r in responses] == [401] * 5


def test_removed_participant_loses_access_immediately(client):
    owner, trip_id, found, body = seeded_trip(client)
    editor = login(client, "carol")
    assert client.get(f"/trips/{trip_id}/itinerary", headers=editor).status_code == 200
    members = client.get(f"/trips/{trip_id}/participants", headers=owner).json()
    carol_id = next(p["userId"] for p in members if p["username"] == "carol")

    removed = client.delete(f"/trips/{trip_id}/participants/{carol_id}", headers=owner)

    assert removed.status_code == 204
    item_id = body["items"][0]["id"]
    assert client.get(f"/trips/{trip_id}/itinerary", headers=editor).status_code == 404
    assert client.get(f"/trips/{trip_id}/budget", headers=editor).status_code == 404
    results = writes(client, editor, trip_id, found[1]["id"], item_id, body["version"])
    assert [r.status_code for r in results.values()] == [404, 404, 404]


def test_role_downgrade_takes_effect_on_the_next_write(client):
    owner, trip_id, found, body = seeded_trip(client)
    editor = login(client, "carol")
    members = client.get(f"/trips/{trip_id}/participants", headers=owner).json()
    carol_id = next(p["userId"] for p in members if p["username"] == "carol")
    assert add(client, editor, trip_id, found[1]["id"], body["version"]).status_code == 201

    client.put(f"/trips/{trip_id}/participants/{carol_id}", json={"role": "viewer"}, headers=owner)

    assert add(client, editor, trip_id, found[2]["id"], body["version"] + 1).status_code == 403
