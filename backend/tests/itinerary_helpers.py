"""Shared helpers for the itinerary tests (real provider mock over HTTP; reset before and after each test)."""
from datetime import date, timedelta

import httpx
import pytest

from app.config import get_settings
from tests.conftest import VALID_TRIP, login

MOCK = get_settings().provider_base_url.removesuffix("/v1")
TODAY = date.today()
# A window around the mock's fixture dates (they are generated relative to its clock).
TRIP = {
    **VALID_TRIP,
    "destinations": ["Lisbon", "Rome"],
    "startDate": TODAY.isoformat(),
    "endDate": (TODAY + timedelta(days=365)).isoformat(),
    "travelers": 2,
    "budget": "1000.00",
}


@pytest.fixture(autouse=True)
def mock():
    httpx.post(f"{MOCK}/control/reset").raise_for_status()
    yield
    httpx.post(f"{MOCK}/control/reset")


def control(method: str, path: str, **body) -> None:
    httpx.request(method, f"{MOCK}/control{path}", json=body or None).raise_for_status()


def make_trip(client, trip=TRIP, owner="alice"):
    headers = login(client, owner)
    return headers, client.post("/trips", json=trip, headers=headers).json()["id"]


def share(client, headers, trip_id, username, role):
    response = client.post(f"/trips/{trip_id}/participants", json={"username": username, "role": role}, headers=headers)
    assert response.status_code == 201, response.text


def offers(client, headers, trip_id, category="accommodation", destination="Lisbon", **extra) -> list[dict]:
    """Search results, earliest start first (the mock's order)."""
    response = client.post(
        f"/trips/{trip_id}/search", json={"category": category, "destination": destination, **extra}, headers=headers
    )
    assert response.status_code == 200, response.text
    return response.json()["offers"]


def add(client, headers, trip_id, offer_id, version):
    return client.post(f"/trips/{trip_id}/itinerary", json={"offerId": offer_id, "version": version}, headers=headers)


def itinerary(client, headers, trip_id) -> dict:
    response = client.get(f"/trips/{trip_id}/itinerary", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def offer_ids(body: dict) -> list[str]:
    return [i["offerId"] for i in body["items"]]
