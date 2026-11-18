"""Itinerary add / remove / reorder against the real provider mock."""
from tests.itinerary_helpers import (  # noqa: F401  (mock is an autouse fixture)
    MOCK,
    add,
    control,
    itinerary,
    make_trip,
    mock,
    offer_ids,
    offers,
)

import httpx


def test_add_stores_a_snapshot_of_the_provider_offer(client):
    headers, trip_id = make_trip(client)
    offer = offers(client, headers, trip_id)[0]

    response = add(client, headers, trip_id, offer["id"], 1)

    assert response.status_code == 201
    body = response.json()
    assert body["version"] == 2
    item = body["items"][0]
    assert item["offerId"] == offer["id"] and item["providerId"] == offer["providerId"]
    assert item["title"] == offer["title"] and item["destination"] == "Lisbon"
    assert item["price"] == offer["price"] and item["revision"] == offer["revision"]
    assert item["startsAt"] and item["endsAt"] and item["validUntil"]
    assert item["status"] == "estimate"


def test_new_items_are_inserted_in_chronological_order(client):
    headers, trip_id = make_trip(client)
    found = offers(client, headers, trip_id)
    earliest, middle, latest = found[0], found[1], found[-1]

    add(client, headers, trip_id, latest["id"], 1)
    add(client, headers, trip_id, earliest["id"], 2)
    response = add(client, headers, trip_id, middle["id"], 3)

    assert offer_ids(response.json()) == [earliest["id"], middle["id"], latest["id"]]


def test_unavailable_offer_is_refused_and_nothing_changes(client):
    headers, trip_id = make_trip(client)
    offer = offers(client, headers, trip_id)[0]
    control("POST", f"/offers/{offer['id']}", available=False)

    response = add(client, headers, trip_id, offer["id"], 1)

    assert response.status_code == 409 and response.json()["code"] == "OFFER_UNAVAILABLE"
    assert itinerary(client, headers, trip_id) == {"version": 1, "items": []}


def test_same_offer_twice_is_refused(client):
    headers, trip_id = make_trip(client)
    offer = offers(client, headers, trip_id)[0]
    add(client, headers, trip_id, offer["id"], 1)

    response = add(client, headers, trip_id, offer["id"], 2)

    assert response.status_code == 409 and response.json()["code"] == "ALREADY_IN_ITINERARY"
    body = itinerary(client, headers, trip_id)
    assert len(body["items"]) == 1 and body["version"] == 2


def test_offer_for_a_destination_outside_the_trip_is_refused(client):
    headers, trip_id = make_trip(client)

    response = add(client, headers, trip_id, "paris-accommodation-supplier-a-p2", 1)

    assert response.status_code == 400
    assert "offerId" in response.json()["details"]["fields"]
    assert itinerary(client, headers, trip_id)["items"] == []


def test_unknown_offer_is_404(client):
    headers, trip_id = make_trip(client)

    response = add(client, headers, trip_id, "no-such-offer", 1)

    assert response.status_code == 404


def test_provider_failure_adds_nothing(client):
    headers, trip_id = make_trip(client)
    offer = offers(client, headers, trip_id)[0]
    control("PUT", f"/suppliers/{offer['providerId']}/failure", mode="unavailable")

    response = add(client, headers, trip_id, offer["id"], 1)

    assert response.status_code == 503 and response.json()["code"] == "PROVIDER_UNAVAILABLE"
    assert itinerary(client, headers, trip_id) == {"version": 1, "items": []}


def test_remove_deletes_the_item_and_bumps_the_version(client):
    headers, trip_id = make_trip(client)
    found = offers(client, headers, trip_id)
    add(client, headers, trip_id, found[0]["id"], 1)
    body = add(client, headers, trip_id, found[1]["id"], 2).json()
    first_id = body["items"][0]["id"]

    response = client.delete(f"/trips/{trip_id}/itinerary/{first_id}", params={"version": 3}, headers=headers)

    assert response.status_code == 200
    assert offer_ids(response.json()) == [found[1]["id"]] and response.json()["version"] == 4
    assert offer_ids(itinerary(client, headers, trip_id)) == [found[1]["id"]]


def test_removing_an_item_that_is_already_gone_is_404(client):
    headers, trip_id = make_trip(client)
    offer = offers(client, headers, trip_id)[0]
    item_id = add(client, headers, trip_id, offer["id"], 1).json()["items"][0]["id"]
    client.delete(f"/trips/{trip_id}/itinerary/{item_id}", params={"version": 2}, headers=headers)

    response = client.delete(f"/trips/{trip_id}/itinerary/{item_id}", params={"version": 3}, headers=headers)

    assert response.status_code == 404
    assert itinerary(client, headers, trip_id)["version"] == 3  # the failed request changed nothing


def test_reorder_persists_after_reload(client):
    headers, trip_id = make_trip(client)
    found = offers(client, headers, trip_id)
    for n, offer in enumerate(found[:3]):
        add(client, headers, trip_id, offer["id"], n + 1)
    body = itinerary(client, headers, trip_id)
    ids = [i["id"] for i in body["items"]]

    response = client.put(
        f"/trips/{trip_id}/itinerary/order", json={"itemIds": ids[::-1], "version": body["version"]}, headers=headers
    )

    expected = [found[2]["id"], found[1]["id"], found[0]["id"]]
    assert response.status_code == 200 and offer_ids(response.json()) == expected
    assert offer_ids(itinerary(client, headers, trip_id)) == expected


def test_invalid_orders_are_refused_and_change_nothing(client):
    headers, trip_id = make_trip(client)
    found = offers(client, headers, trip_id)
    add(client, headers, trip_id, found[0]["id"], 1)
    add(client, headers, trip_id, found[1]["id"], 2)
    body = itinerary(client, headers, trip_id)
    a, b = (i["id"] for i in body["items"])
    unknown = "00000000-0000-4000-8000-000000000000"

    for bad in ([a], [a, a], [a, b, unknown], [a, unknown], []):
        response = client.put(
            f"/trips/{trip_id}/itinerary/order", json={"itemIds": bad, "version": body["version"]}, headers=headers
        )
        assert response.status_code == 400, bad
        assert "itemIds" in response.json()["details"]["fields"]

    assert itinerary(client, headers, trip_id) == body


def test_stored_item_does_not_change_when_the_provider_price_changes(client):
    headers, trip_id = make_trip(client)
    offer = offers(client, headers, trip_id)[0]
    add(client, headers, trip_id, offer["id"], 1)
    before = itinerary(client, headers, trip_id)
    budget_before = client.get(f"/trips/{trip_id}/budget", headers=headers).json()

    control("POST", f"/offers/{offer['id']}", price="1.00")
    assert httpx.get(f"{MOCK}/v1/offers/{offer['id']}", headers={"Authorization": "Bearer travel-demo-token"}).json()["price"]["amount"] == "1.00"

    assert itinerary(client, headers, trip_id) == before
    assert client.get(f"/trips/{trip_id}/budget", headers=headers).json() == budget_before
