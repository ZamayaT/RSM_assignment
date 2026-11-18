"""Shared helpers for the booking tests (real provider mock over HTTP; the mock is reset around every test)."""
import uuid

import httpx
import pytest
from sqlalchemy import text

from app.config import get_settings
from app.db import get_engine
from tests.itinerary_helpers import MOCK, add, control, itinerary, make_trip, mock, offers, share  # noqa: F401


def provider_get(path: str) -> httpx.Response:
    """Ask the mock directly (as the provider contract allows) what it holds."""
    return httpx.get(f"{MOCK}/v1{path}", headers={"Authorization": f"Bearer {get_settings().provider_token}"})


def provider_booking(reference: str) -> dict | None:
    response = provider_get(f"/bookings/by-reference/{reference}")
    return response.json() if response.status_code == 200 else None


def fresh_item(client, owner="alice"):
    """A trip with one accommodation in its itinerary: (headers, trip_id, offer, item)."""
    headers, trip_id = make_trip(client, owner=owner)
    offer = offers(client, headers, trip_id)[0]
    item = add(client, headers, trip_id, offer["id"], 1).json()["items"][0]
    return headers, trip_id, offer, item


def book_request(client, headers, trip_id, item, intent=None, revision=None, price=None):
    """POST a booking; by default the item's saved terms are the ones 'shown' to the user."""
    return client.post(
        f"/trips/{trip_id}/bookings",
        headers=headers,
        json={
            "itemId": item["id"],
            "intentId": intent or str(uuid.uuid4()),
            "expectedRevision": revision or item["revision"],
            "expectedPrice": price or item["price"],
        },
    )


def quote(client, headers, trip_id, item) -> dict:
    response = client.get(f"/trips/{trip_id}/itinerary/{item['id']}/quote", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def book_current(client, headers, trip_id, item, **kwargs):
    """Book on the provider's current terms, as the confirmation dialog does."""
    current = quote(client, headers, trip_id, item)["current"]
    return book_request(client, headers, trip_id, item, revision=current["revision"], price=current["price"], **kwargs)


def bookings(client, headers, trip_id) -> dict:
    response = client.get(f"/trips/{trip_id}/bookings", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def latest_attempt(client, headers, trip_id) -> dict:
    return bookings(client, headers, trip_id)["attempts"][0]


def attempt_count(trip_id: str) -> int:
    with get_engine().connect() as connection:
        return connection.execute(text("SELECT count(*) FROM booking_attempts WHERE trip_id = :t"), {"t": trip_id}).scalar_one()


def reference_of(attempt_id: str) -> str:
    with get_engine().connect() as connection:
        return connection.execute(
            text("SELECT client_reference FROM booking_attempts WHERE id = :i"), {"i": attempt_id}
        ).scalar_one()


@pytest.fixture
def no_waiting(monkeypatch):
    """Worker intervals of zero seconds, so every step is due immediately and tests never sleep."""
    settings = get_settings()
    for name in ("booking_first_check_seconds", "booking_poll_fast_seconds", "booking_poll_slow_seconds"):
        monkeypatch.setattr(settings, name, 0)
    return settings
