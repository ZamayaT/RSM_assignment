"""Control interface (outside the contract). Run inside the container: it uses the database."""
import time
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from conftest import AUTH
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.clock import get_clock
from app.db import get_engine
from app.main import app
from app.models import Booking, Offer

client = TestClient(app)


def _book(offer_id, reference=None, revision="r1", amount="100.00"):
    body = {
        "clientReference": reference or f"ref-{uuid.uuid4().hex[:10]}",
        "offerId": offer_id,
        "expectedOfferRevision": revision,
        "expectedPrice": {"amount": amount, "currency": "USD"},
    }
    return client.post("/v1/bookings", json=body, headers={**AUTH, "Idempotency-Key": uuid.uuid4().hex})


def _search_lisbon():
    with Session(get_engine()) as session:
        rows = session.scalars(select(Offer).where(Offer.destination == "Lisbon", Offer.category == "accommodation")).all()
    body = {
        "category": "accommodation", "destination": "Lisbon", "travelers": 2,
        "startsOn": min(r.starts_at for r in rows).date().isoformat(),
        "endsOn": (max(r.ends_at for r in rows) + timedelta(days=1)).date().isoformat(),
    }
    return client.post("/v1/offers/search", json=body, headers=AUTH)


# ---- clock ------------------------------------------------------------------------------------------

def test_clock_freeze_advance_offset_and_real_time():
    frozen = client.post("/control/clock", json={"frozenAt": "2030-01-15T09:00:00Z"}).json()
    assert frozen["frozen"] is True and get_clock().now() == datetime(2030, 1, 15, 9, tzinfo=timezone.utc)

    client.post("/control/clock", json={"advanceSeconds": 3600})
    assert get_clock().now() == datetime(2030, 1, 15, 10, tzinfo=timezone.utc)

    client.post("/control/clock", json={"offsetSeconds": 86400})
    assert not client.get("/control/state").json()["clock"]["frozen"]
    assert abs(get_clock().now() - (datetime.now(timezone.utc) + timedelta(days=1))) < timedelta(seconds=2)

    client.post("/control/clock", json={"advanceSeconds": 3600})
    assert client.get("/control/state").json()["clock"]["offsetSeconds"] == 90000

    client.post("/control/clock", json={"freeze": True})
    first = get_clock().now()
    time.sleep(0.05)
    assert get_clock().now() == first

    client.post("/control/clock", json={"realTime": True})
    assert abs(get_clock().now() - datetime.now(timezone.utc)) < timedelta(seconds=2)


@pytest.mark.parametrize(
    "body",
    [{}, {"freeze": True, "realTime": True}, {"frozenAt": "2030-01-15T09:00:00"}, {"freeze": False}, {"x": 1}],
)
def test_clock_requires_exactly_one_valid_field(body):
    response = client.post("/control/clock", json=body)
    assert response.status_code == 400 and response.json()["code"] == "BAD_REQUEST"


def test_moving_the_clock_expires_quotes(make_offer):
    offer_id = make_offer()  # valid for one day
    client.post("/control/clock", json={"advanceSeconds": 2 * 86400})
    response = _book(offer_id)
    assert response.status_code == 409 and response.json()["code"] == "OFFER_CHANGED"
    refreshed = client.get(f"/v1/offers/{offer_id}", headers=AUTH).json()
    assert refreshed["revision"] == "r2"
    assert _book(offer_id, revision="r2").status_code == 201


# ---- supplier failures and latency ------------------------------------------------------------------

def test_supplier_failure_can_be_set_and_reverted():
    assert client.put("/control/suppliers/supplier-b/failure", json={"mode": "timeout"}).status_code == 204
    body = _search_lisbon().json()
    assert body["partial"] is True and body["warnings"][0]["code"] == "PROVIDER_TIMEOUT"
    assert client.get("/control/state").json()["supplierFailures"]["supplier-b"]["mode"] == "timeout"

    assert client.delete("/control/suppliers/supplier-b/failure").status_code == 204
    body = _search_lisbon().json()
    assert body["partial"] is False and {o["providerId"] for o in body["offers"]} >= {"supplier-b"}


def test_rate_limited_failure_carries_retry_after():
    client.put("/control/suppliers/supplier-a/failure", json={"mode": "rate_limited", "retryAfterSeconds": 9})
    body = {"category": "accommodation", "destination": "Lisbon", "startsOn": "2000-01-01", "endsOn": "2100-01-01",
            "travelers": 2, "providerId": "supplier-a"}
    response = client.post("/v1/offers/search", json=body, headers=AUTH)
    assert response.status_code == 429 and response.headers["Retry-After"] == "9"


def test_invalid_supplier_control_requests():
    assert client.put("/control/suppliers/nope/failure", json={"mode": "unavailable"}).status_code == 404
    assert client.put("/control/suppliers/supplier-a/failure", json={"mode": "explode"}).status_code == 400
    assert client.put("/control/suppliers/supplier-a/failure", json={"mode": "unavailable", "retryAfterSeconds": 0}
                      ).status_code == 400
    assert client.delete("/control/suppliers/nope/failure").status_code == 404
    assert client.put("/control/suppliers/supplier-a/latency", json={"milliseconds": -1}).status_code == 400


def test_latency_slows_responses_until_removed(make_offer):
    offer_id = make_offer(provider_id="supplier-c")
    client.put("/control/suppliers/supplier-c/latency", json={"milliseconds": 300})
    assert client.get("/control/state").json()["supplierLatencyMs"] == {"supplier-c": 300}
    started = time.monotonic()
    client.get(f"/v1/offers/{offer_id}", headers=AUTH)
    assert time.monotonic() - started >= 0.3

    client.put("/control/suppliers/supplier-c/latency", json={"milliseconds": 0})
    started = time.monotonic()
    client.get(f"/v1/offers/{offer_id}", headers=AUTH)
    assert time.monotonic() - started < 0.3


# ---- offers -----------------------------------------------------------------------------------------

def test_price_change_creates_a_new_revision_and_rejects_the_old_one(make_offer):
    offer_id = make_offer()
    changed = client.post(f"/control/offers/{offer_id}", json={"price": "120.50"})
    assert changed.status_code == 200
    assert changed.json()["price"]["amount"] == "120.50" and changed.json()["revision"] == "r2"
    assert client.get(f"/v1/offers/{offer_id}", headers=AUTH).json()["revision"] == "r2"
    assert _book(offer_id).json()["code"] == "OFFER_CHANGED"
    assert _book(offer_id, revision="r2", amount="120.50").status_code == 201


def test_sold_out_offer_is_unavailable_and_can_be_restored(make_offer):
    offer_id = make_offer()
    client.post(f"/control/offers/{offer_id}", json={"available": False})
    assert client.get(f"/v1/offers/{offer_id}", headers=AUTH).json()["available"] is False
    assert _book(offer_id).json()["code"] == "OFFER_UNAVAILABLE"
    client.post(f"/control/offers/{offer_id}", json={"available": True})
    assert _book(offer_id, revision="r3").status_code == 201


def test_unchanged_values_keep_the_revision_and_bookings_keep_their_snapshot(make_offer):
    offer_id = make_offer()
    assert client.post(f"/control/offers/{offer_id}", json={"price": "100.00"}).json()["revision"] == "r1"
    booking = _book(offer_id).json()
    client.post(f"/control/offers/{offer_id}", json={"price": "1.00"})
    with Session(get_engine()) as session:
        stored = session.get(Booking, booking["id"])
        assert stored.offer_snapshot["price"]["amount"] == "100.00" and str(stored.price_amount) == "100.00"


def test_invalid_offer_changes():
    assert client.post("/control/offers/whatever", json={}).status_code == 400
    assert client.post("/control/offers/whatever", json={"price": "12.5"}).status_code == 400
    assert client.post("/control/offers/does-not-exist", json={"price": "1.00"}).status_code == 404


# ---- booking outcomes -------------------------------------------------------------------------------

def test_outcomes_apply_to_the_next_bookings_in_order_then_default_to_confirmed(make_offer):
    offer_id = make_offer()
    client.put("/control/booking-outcomes", json={"outcome": "failed"})
    client.put("/control/booking-outcomes", json={"outcome": "pending", "count": 2})
    assert client.get("/control/state").json()["nextBookingOutcomes"] == ["failed", "pending", "pending"]
    statuses = [_book(offer_id).json()["status"] for _ in range(4)]
    assert statuses == ["failed", "pending", "pending", "confirmed"]


def test_rejected_requests_do_not_consume_outcomes(make_offer):
    offer_id = make_offer()
    client.put("/control/booking-outcomes", json={"outcome": "failed"})
    assert _book(offer_id, revision="r9").status_code == 409
    assert _book(offer_id).json()["status"] == "failed"


def test_queued_outcomes_can_be_cleared():
    client.put("/control/booking-outcomes", json={"outcome": "failed", "count": 3})
    assert client.delete("/control/booking-outcomes").status_code == 204
    assert client.get("/control/state").json()["nextBookingOutcomes"] == []


def test_pending_booking_can_be_forced_to_a_terminal_outcome(make_offer):
    offer_id = make_offer()
    client.put("/control/booking-outcomes", json={"outcome": "pending", "count": 2})
    first, second = _book(offer_id).json(), _book(offer_id).json()

    confirmed = client.post(f"/control/bookings/{first['id']}/resolve", json={"outcome": "confirmed"}).json()
    assert confirmed["status"] == "confirmed" and "failure" not in confirmed
    assert confirmed["offer"] == first["offer"] and confirmed["createdAt"] == first["createdAt"]
    assert confirmed["updatedAt"] >= confirmed["createdAt"]

    failed = client.post(f"/control/bookings/{second['id']}/resolve", json={"outcome": "failed"}).json()
    assert failed["status"] == "failed" and failed["failure"]["code"]


def test_terminal_booking_cannot_be_resolved_again(make_offer):
    offer_id = make_offer()
    booking = _book(offer_id).json()  # confirmed
    response = client.post(f"/control/bookings/{booking['id']}/resolve", json={"outcome": "failed"})
    assert response.status_code == 409
    assert client.post("/control/bookings/nope/resolve", json={"outcome": "failed"}).status_code == 404
    assert client.post(f"/control/bookings/{booking['id']}/resolve", json={"outcome": "pending"}).status_code == 400


# ---- reset ------------------------------------------------------------------------------------------

def test_reset_clears_data_and_settings_and_reloads_fixtures(make_offer):
    offer_id = make_offer()
    assert _book(offer_id).status_code == 201
    client.put("/control/suppliers/supplier-a/failure", json={"mode": "unavailable"})
    client.put("/control/suppliers/supplier-a/latency", json={"milliseconds": 100})
    client.put("/control/booking-outcomes", json={"outcome": "failed"})
    client.post("/control/clock", json={"frozenAt": "2030-01-15T09:00:00Z"})

    result = client.post("/control/reset")
    assert result.status_code == 200 and result.json()["offersLoaded"] == 117
    state = client.get("/control/state").json()
    assert state["supplierFailures"] == {} and state["supplierLatencyMs"] == {}
    assert state["nextBookingOutcomes"] == [] and state["clock"]["frozen"] is False
    assert not result.json()["clock"]["frozen"]
    with Session(get_engine()) as session:
        assert session.scalar(select(func.count()).select_from(Booking)) == 0
        assert session.scalar(select(func.count()).select_from(Offer)) == 117
        assert session.get(Offer, offer_id) is None


def test_reset_returns_the_clock_to_real_time_before_loading_fixtures():
    client.post("/control/clock", json={"frozenAt": "2040-01-15T09:00:00Z"})
    client.post("/control/reset")  # also returns the clock to its configured value
    with Session(get_engine()) as session:
        assert session.scalar(select(func.min(Offer.starts_at))) > datetime.now(timezone.utc)


def test_restrictions_change_creates_a_new_revision_and_is_returned(make_offer):
    offer_id = make_offer(restrictions=["Minimum age 18"])
    changed = client.post(f"/control/offers/{offer_id}", json={"restrictions": ["Photo ID required at check-in"]})
    assert changed.status_code == 200
    body = client.get(f"/v1/offers/{offer_id}", headers=AUTH).json()
    assert body["restrictions"] == ["Photo ID required at check-in"] and body["revision"] == "r2"
    same = client.post(f"/control/offers/{offer_id}", json={"restrictions": ["Photo ID required at check-in"]})
    assert same.json()["revision"] == "r2"  # nothing changed: no new revision
