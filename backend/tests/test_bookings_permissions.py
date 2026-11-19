"""Who may book, and the concurrency guarantees: one attempt per item, and a booked item cannot disappear."""
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

from tests.booking_helpers import (  # noqa: F401
    add,
    attempt_count,
    book_current,
    book_request,
    fresh_item,
    itinerary,
    make_trip,
    mock,
    offers,
    provider_booking,
    reference_of,
    share,
)
from tests.conftest import login


def trip_with_roles(client):
    owner, trip_id, offer, item = fresh_item(client)
    share(client, owner, trip_id, "bob", "viewer")
    share(client, owner, trip_id, "carol", "editor")
    return owner, login(client, "bob"), login(client, "carol"), trip_id, offer, item


def test_viewer_may_read_bookings_but_not_book_check_or_quote(client):
    owner, viewer, editor, trip_id, offer, item = trip_with_roles(client)
    attempt = book_current(client, owner, trip_id, item).json()

    assert client.get(f"/trips/{trip_id}/bookings", headers=viewer).status_code == 200
    assert book_request(client, viewer, trip_id, item).status_code == 403
    assert client.post(f"/trips/{trip_id}/bookings/{attempt['id']}/check", headers=viewer).status_code == 403
    assert client.get(f"/trips/{trip_id}/itinerary/{item['id']}/quote", headers=viewer).status_code == 403
    assert client.post(f"/trips/{trip_id}/itinerary/{item['id']}/refresh", json={"version": 2}, headers=viewer).status_code == 403
    assert attempt_count(trip_id) == 1


def test_editor_can_book_and_check(client):
    owner, viewer, editor, trip_id, offer, item = trip_with_roles(client)

    attempt = book_current(client, editor, trip_id, item)

    assert attempt.status_code == 201 and attempt.json()["status"] == "confirmed"
    assert client.post(f"/trips/{trip_id}/bookings/{attempt.json()['id']}/check", headers=editor).status_code == 200


def test_non_participant_gets_404_and_no_login_gets_401(client):
    owner, trip_id, offer, item = fresh_item(client)
    attempt = book_current(client, owner, trip_id, item).json()
    stranger = login(client, "bob")
    check = f"/trips/{trip_id}/bookings/{attempt['id']}/check"

    assert book_request(client, stranger, trip_id, item).status_code == 404
    assert client.get(f"/trips/{trip_id}/bookings", headers=stranger).status_code == 404
    assert client.post(check, headers=stranger).status_code == 404
    assert client.get(f"/trips/{trip_id}/itinerary/{item['id']}/quote", headers=stranger).status_code == 404
    assert client.get(f"/trips/{trip_id}/bookings").status_code == 401
    assert client.post(f"/trips/{trip_id}/bookings", json={}).status_code == 401
    assert client.post(check).status_code == 401
    assert attempt_count(trip_id) == 1


def test_check_of_an_unknown_attempt_or_one_from_another_trip_is_404(client):
    owner, trip_id, offer, item = fresh_item(client)
    other_headers, other_trip, _, other_item = fresh_item(client)
    other_attempt = book_current(client, other_headers, other_trip, other_item).json()

    assert client.post(f"/trips/{trip_id}/bookings/{uuid.uuid4()}/check", headers=owner).status_code == 404
    assert client.post(f"/trips/{trip_id}/bookings/{other_attempt['id']}/check", headers=owner).status_code == 404


def test_booking_an_item_that_is_not_in_the_trip_is_404_and_invalid_terms_are_400(client):
    owner, trip_id, offer, item = fresh_item(client)

    assert book_request(client, owner, trip_id, {**item, "id": str(uuid.uuid4())}).status_code == 404
    assert book_request(client, owner, trip_id, item, price={"amount": "-1", "currency": "USD"}).status_code == 400
    assert book_request(client, owner, trip_id, item, price={"amount": "10.00", "currency": "US"}).status_code == 400
    assert attempt_count(trip_id) == 0


def test_booked_item_cannot_be_removed_or_refreshed(client):
    owner, trip_id, offer, item = fresh_item(client)
    book_current(client, owner, trip_id, item)
    version = itinerary(client, owner, trip_id)["version"]

    removed = client.delete(f"/trips/{trip_id}/itinerary/{item['id']}", params={"version": version}, headers=owner)
    refreshed = client.post(f"/trips/{trip_id}/itinerary/{item['id']}/refresh", json={"version": version}, headers=owner)

    assert (removed.status_code, refreshed.status_code) == (409, 409)
    assert removed.json()["code"] == refreshed.json()["code"] == "ITEM_BOOKED"
    after = itinerary(client, owner, trip_id)
    assert len(after["items"]) == 1 and after["version"] == version  # nothing changed, version not bumped


def test_second_booking_for_a_booked_item_is_refused_with_the_existing_attempt(client):
    owner, trip_id, offer, item = fresh_item(client)
    first = book_current(client, owner, trip_id, item).json()

    second = book_current(client, owner, trip_id, item)

    assert second.status_code == 409 and second.json()["code"] == "BOOKING_EXISTS"
    assert second.json()["details"]["attempt"]["id"] == first["id"]
    assert attempt_count(trip_id) == 1


def test_two_simultaneous_bookings_for_one_item_create_one_attempt_and_one_provider_booking(client):
    owner, trip_id, offer, item = fresh_item(client)
    barrier = threading.Barrier(2)

    def attempt():
        barrier.wait()
        return book_request(client, owner, trip_id, item)

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: attempt(), range(2)))

    assert sorted(r.status_code for r in results) == [201, 409]
    assert attempt_count(trip_id) == 1
    winner = next(r for r in results if r.status_code == 201).json()
    assert provider_booking(reference_of(winner["id"]))["id"] == winner["providerBookingId"]


def test_two_simultaneous_requests_with_the_same_intent_return_the_same_attempt(client):
    owner, trip_id, offer, item = fresh_item(client)
    intent = str(uuid.uuid4())
    barrier = threading.Barrier(2)

    def attempt():
        barrier.wait()
        return book_request(client, owner, trip_id, item, intent=intent)

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: attempt(), range(2)))

    assert sorted(r.status_code for r in results) == [200, 201]
    assert results[0].json()["id"] == results[1].json()["id"] and attempt_count(trip_id) == 1


def test_a_removal_and_a_booking_racing_never_both_succeed(client):
    for _ in range(4):
        owner, trip_id, offer, item = fresh_item(client)
        version = itinerary(client, owner, trip_id)["version"]
        barrier = threading.Barrier(2)

        def remove():
            barrier.wait()
            return client.delete(f"/trips/{trip_id}/itinerary/{item['id']}", params={"version": version}, headers=owner)

        def book():
            barrier.wait()
            return book_request(client, owner, trip_id, item)

        with ThreadPoolExecutor(2) as pool:
            removing, booking = pool.submit(remove), pool.submit(book)
            removed, booked = removing.result(), booking.result()

        assert not (removed.status_code == 200 and booked.status_code == 201)
        remaining = itinerary(client, owner, trip_id)["items"]
        if removed.status_code == 200:
            assert booked.status_code == 404 and remaining == [] and attempt_count(trip_id) == 0
        else:
            assert removed.json()["code"] == "ITEM_BOOKED" and booked.status_code == 201
            assert len(remaining) == 1 and attempt_count(trip_id) == 1
