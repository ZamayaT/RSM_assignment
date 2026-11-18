"""Search endpoint against the real provider mock over HTTP (the stack must be running).

The mock is reset before and after every test; its /control endpoints are used only here.
"""
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
}


@pytest.fixture(autouse=True)
def mock():
    httpx.post(f"{MOCK}/control/reset").raise_for_status()
    yield
    httpx.post(f"{MOCK}/control/reset")


def fail_supplier(supplier: str, mode: str = "unavailable", **extra) -> None:
    httpx.put(f"{MOCK}/control/suppliers/{supplier}/failure", json={"mode": mode, **extra}).raise_for_status()


def make_trip(client, trip=TRIP, owner="alice"):
    headers = login(client, owner)
    return headers, client.post("/trips", json=trip, headers=headers).json()["id"]


def search(client, headers, trip_id, **body):
    return client.post(f"/trips/{trip_id}/search", json=body, headers=headers)


# --- options ---


def test_options_list_the_supported_values_and_need_login(client):
    assert client.get("/search/options").status_code == 401

    options = client.get("/search/options", headers=login(client, "alice")).json()

    assert options["categories"] == ["transport", "accommodation", "activity"]
    assert options["origins"] == ["London", "New York", "Madrid"]
    assert options["suppliers"] == ["supplier-a", "supplier-b", "supplier-c"]


# --- results and states ---


@pytest.mark.parametrize(
    "extra",
    [{"category": "accommodation"}, {"category": "activity"}, {"category": "transport", "origin": "London"}],
    ids=["accommodation", "activity", "transport"],
)
def test_complete_search_per_category(client, extra):
    headers, trip_id = make_trip(client)

    response = search(client, headers, trip_id, destination="Lisbon", **extra)

    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "complete" and body["warnings"] == []
    assert body["searchedAt"]
    offer = body["offers"][0]
    assert offer["category"] == extra["category"] and offer["destination"] == "Lisbon"
    assert offer["price"]["currency"] == "USD" and len(offer["price"]["amount"].split(".")[1]) == 2
    assert {"id", "providerId", "title", "description", "startsAt", "endsAt", "available", "revision", "validUntil"} <= offer.keys()


def test_search_with_no_match_is_empty(client):
    headers, trip_id = make_trip(client)

    # A window in the past contains none of the mock's fixture offers.
    response = search(
        client, headers, trip_id, category="accommodation", destination="Lisbon", startsOn="2000-01-01", endsOn="2000-01-05"
    )

    assert response.status_code == 200
    assert response.json()["state"] == "empty" and response.json()["offers"] == []


def test_dates_and_travelers_default_from_the_trip(client):
    headers, trip_id = make_trip(client, {**TRIP, "travelers": 4})

    body = search(client, headers, trip_id, category="accommodation", destination="Lisbon").json()

    assert body["offers"] and {o["travelers"] for o in body["offers"]} == {4}


def test_supplier_filter_limits_the_results(client):
    headers, trip_id = make_trip(client)

    body = search(client, headers, trip_id, category="accommodation", destination="Lisbon", providerId="supplier-c").json()

    assert body["offers"] and {o["providerId"] for o in body["offers"]} == {"supplier-c"}


# --- validation ---


def test_destination_outside_the_trip_is_refused(client):
    headers, trip_id = make_trip(client)

    response = search(client, headers, trip_id, category="accommodation", destination="Paris")

    assert response.status_code == 400
    assert "destination" in response.json()["details"]["fields"]


def test_transport_requires_an_origin(client):
    headers, trip_id = make_trip(client)

    response = search(client, headers, trip_id, category="transport", destination="Lisbon")

    assert response.status_code == 400
    assert "origin" in response.json()["details"]["fields"]


def test_invalid_dates_and_travelers_are_refused(client):
    headers, trip_id = make_trip(client)

    reversed_dates = search(
        client, headers, trip_id, category="accommodation", destination="Lisbon", startsOn="2030-02-01", endsOn="2030-01-01"
    )
    too_many = search(client, headers, trip_id, category="accommodation", destination="Lisbon", travelers=21)

    assert reversed_dates.status_code == 400 and "endsOn" in reversed_dates.json()["details"]["fields"]
    assert too_many.status_code == 400 and "travelers" in too_many.json()["details"]["fields"]


def test_unknown_supplier_is_reported_on_provider_id(client):
    headers, trip_id = make_trip(client)

    response = search(client, headers, trip_id, category="accommodation", destination="Lisbon", providerId="supplier-z")

    assert response.status_code == 400
    assert "providerId" in response.json()["details"]["fields"]


# --- supplier failures ---


def test_one_supplier_down_gives_partial_results_with_a_warning(client):
    headers, trip_id = make_trip(client)
    fail_supplier("supplier-b")

    body = search(client, headers, trip_id, category="accommodation", destination="Lisbon").json()

    assert body["state"] == "partial"
    assert body["offers"], "offers from the suppliers that answered are kept"
    assert {o["providerId"] for o in body["offers"]} == {"supplier-a", "supplier-c"}
    assert [w["providerId"] for w in body["warnings"]] == ["supplier-b"]
    assert body["warnings"][0]["code"] == "PROVIDER_UNAVAILABLE"
    assert "supplier-b" in body["warnings"][0]["message"]


def test_all_suppliers_down_fails_with_503(client):
    headers, trip_id = make_trip(client)
    for supplier in ("supplier-a", "supplier-b", "supplier-c"):
        fail_supplier(supplier)

    response = search(client, headers, trip_id, category="accommodation", destination="Lisbon")

    assert response.status_code == 503
    assert response.json()["code"] == "PROVIDER_UNAVAILABLE"
    assert response.json()["requestId"]


def test_rate_limited_supplier_returns_429_with_retry_after(client):
    headers, trip_id = make_trip(client)
    fail_supplier("supplier-a", "rate_limited", retryAfterSeconds=2)

    response = search(client, headers, trip_id, category="accommodation", destination="Lisbon", providerId="supplier-a")

    assert response.status_code == 429
    assert response.json()["code"] == "RATE_LIMITED"
    assert response.headers["Retry-After"] == "2"


# --- access ---


def test_viewer_can_search(client):
    headers, trip_id = make_trip(client)
    client.post(f"/trips/{trip_id}/participants", json={"username": "bob", "role": "viewer"}, headers=headers)

    response = search(client, login(client, "bob"), trip_id, category="accommodation", destination="Lisbon")

    assert response.status_code == 200 and response.json()["state"] == "complete"


def test_non_participant_gets_404(client):
    _, trip_id = make_trip(client)

    response = search(client, login(client, "carol"), trip_id, category="accommodation", destination="Lisbon")

    assert response.status_code == 404


def test_search_needs_login(client):
    _, trip_id = make_trip(client)

    response = client.post(f"/trips/{trip_id}/search", json={"category": "accommodation", "destination": "Lisbon"})

    assert response.status_code == 401
