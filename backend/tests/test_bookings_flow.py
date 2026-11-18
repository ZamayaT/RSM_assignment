"""Booking outcomes against the real mock: what the user sees for each definite answer."""
import httpx

from tests.booking_helpers import (  # noqa: F401
    MOCK,
    attempt_count,
    book_current,
    book_request,
    bookings,
    control,
    fresh_item,
    itinerary,
    latest_attempt,
    mock,
    provider_booking,
    quote,
    reference_of,
)
from tests.conftest import login  # noqa: F401


def test_confirmed_booking_keeps_the_accepted_offer_and_price(client):
    headers, trip_id, offer, item = fresh_item(client)

    response = book_current(client, headers, trip_id, item)

    assert response.status_code == 201
    attempt = response.json()
    assert attempt["status"] == "confirmed" and attempt["failure"] is None
    assert attempt["acceptedPrice"] == item["price"] and attempt["providerBookingId"]
    held = provider_booking(reference_of(attempt["id"]))
    assert held["status"] == "confirmed" and held["offer"]["id"] == offer["id"]
    assert itinerary(client, headers, trip_id)["items"][0]["status"] == "confirmed"


def test_pending_booking_becomes_confirmed_when_checked(client):
    headers, trip_id, offer, item = fresh_item(client)
    control("PUT", "/booking-outcomes", outcome="pending", count=1)

    attempt = book_current(client, headers, trip_id, item).json()

    assert attempt["status"] == "pending"
    assert itinerary(client, headers, trip_id)["items"][0]["status"] == "booking_pending"
    httpx.post(f"{MOCK}/control/bookings/{attempt['providerBookingId']}/resolve", json={"outcome": "confirmed"}).raise_for_status()
    checked = client.post(f"/trips/{trip_id}/bookings/{attempt['id']}/check", headers=headers).json()
    assert checked["status"] == "confirmed"
    assert itinerary(client, headers, trip_id)["items"][0]["status"] == "confirmed"


def test_failure_forced_by_the_provider_is_shown_with_its_reason_and_the_item_can_be_retried(client):
    headers, trip_id, offer, item = fresh_item(client)
    control("PUT", "/booking-outcomes", outcome="failed", count=1)

    attempt = book_current(client, headers, trip_id, item).json()

    assert attempt["status"] == "failed" and attempt["failure"]["code"] and attempt["failure"]["message"]
    assert itinerary(client, headers, trip_id)["items"][0]["status"] == "failed"
    retry = book_current(client, headers, trip_id, item)  # a new decision: new intent, reference and key
    assert retry.status_code == 201 and retry.json()["status"] == "confirmed"
    assert attempt_count(trip_id) == 2


def test_price_changed_before_booking_is_a_recorded_failure_and_nothing_is_booked(client):
    headers, trip_id, offer, item = fresh_item(client)
    control("POST", f"/offers/{offer['id']}", price="999.00")
    shown = quote(client, headers, trip_id, item)
    assert "price" in shown["changes"] and shown["current"]["price"]["amount"] == "999.00"

    stale = book_request(client, headers, trip_id, item).json()  # the saved, now outdated terms

    assert stale["status"] == "failed" and stale["failure"]["code"] == "OFFER_CHANGED"
    assert provider_booking(reference_of(stale["id"])) is None
    confirmed = book_current(client, headers, trip_id, item).json()
    assert confirmed["status"] == "confirmed" and confirmed["acceptedPrice"]["amount"] == "999.00"


def test_sold_out_offer_is_not_bookable_and_is_refused(client):
    headers, trip_id, offer, item = fresh_item(client)
    control("POST", f"/offers/{offer['id']}", available=False)
    shown = quote(client, headers, trip_id, item)
    assert shown["bookable"] is False and "availability" in shown["changes"] and shown["reason"]

    attempt = book_current(client, headers, trip_id, item).json()

    assert attempt["status"] == "failed" and attempt["failure"]["code"] == "OFFER_UNAVAILABLE"
    assert provider_booking(reference_of(attempt["id"])) is None
    assert itinerary(client, headers, trip_id)["items"][0]["status"] != "confirmed"


def test_expired_quote_is_refused_by_the_provider(client):
    headers, trip_id, offer, item = fresh_item(client)
    control("POST", "/clock", advanceSeconds=10 * 24 * 3600)  # far past the quote's validUntil

    attempt = book_request(client, headers, trip_id, item).json()

    assert attempt["status"] == "failed" and attempt["failure"]["code"] == "OFFER_CHANGED"
    assert provider_booking(reference_of(attempt["id"])) is None


def test_accepted_price_and_budget_do_not_change_when_the_provider_changes_the_price_later(client):
    headers, trip_id, offer, item = fresh_item(client)
    price = item["price"]["amount"]
    assert book_current(client, headers, trip_id, item).json()["status"] == "confirmed"

    control("POST", f"/offers/{offer['id']}", price="1.00")

    assert latest_attempt(client, headers, trip_id)["acceptedPrice"]["amount"] == price
    budget = client.get(f"/trips/{trip_id}/budget", headers=headers).json()
    assert budget["confirmedTotal"] == price and budget["estimatedTotal"] == "0.00"
    line = budget["lines"][0]
    assert line["kind"] == "confirmed" and line["amount"] == price and line["status"] == "confirmed"


def test_budget_separates_confirmed_from_estimates_and_flags_other_states(client):
    headers, trip_id, offer, first = fresh_item(client)
    second_offer = [o for o in client.post(
        f"/trips/{trip_id}/search", json={"category": "accommodation", "destination": "Lisbon"}, headers=headers
    ).json()["offers"] if o["id"] != offer["id"]][0]
    version = itinerary(client, headers, trip_id)["version"]
    items = client.post(
        f"/trips/{trip_id}/itinerary", json={"offerId": second_offer["id"], "version": version}, headers=headers
    ).json()["items"]
    second = next(i for i in items if i["offerId"] == second_offer["id"])
    assert book_current(client, headers, trip_id, first).json()["status"] == "confirmed"
    control("PUT", "/booking-outcomes", outcome="pending", count=1)
    assert book_current(client, headers, trip_id, second).json()["status"] == "pending"

    budget = client.get(f"/trips/{trip_id}/budget", headers=headers).json()

    kinds = {line["itemId"]: (line["kind"], line["status"]) for line in budget["lines"]}
    assert kinds[first["id"]] == ("confirmed", "confirmed") and kinds[second["id"]] == ("estimate", "booking_pending")
    assert budget["confirmedTotal"] == first["price"]["amount"] and budget["estimatedTotal"] == second["price"]["amount"]


def test_bookings_list_counts_the_latest_attempt_of_each_item(client):
    headers, trip_id, offer, item = fresh_item(client)
    control("PUT", "/booking-outcomes", outcome="failed", count=1)
    book_current(client, headers, trip_id, item)
    book_current(client, headers, trip_id, item)

    listing = bookings(client, headers, trip_id)

    assert len(listing["attempts"]) == 2 and listing["attempts"][0]["status"] == "confirmed"
    assert listing["counts"] == {"pending": 0, "confirmed": 1, "failed": 0, "unknown": 0}
