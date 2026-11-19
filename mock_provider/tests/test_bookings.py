"""Booking creation (new requests and idempotency). Run inside the container: they use the database."""
import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from conftest import AUTH, OTHER_AUTH
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import failures, outcomes
from app.clock import get_clock
from app.db import get_engine
from app.main import app
from app.models import Booking, IdempotencyRecord, Offer

client = TestClient(app)


def _body(offer_id, reference=None, revision="r1", amount="100.00"):
    return {
        "clientReference": reference or f"ref-{uuid.uuid4().hex[:10]}",
        "offerId": offer_id,
        "expectedOfferRevision": revision,
        "expectedPrice": {"amount": amount, "currency": "USD"},
    }


def _post(body, key=None, headers=AUTH):
    return client.post("/v1/bookings", json=body, headers={**headers, "Idempotency-Key": key or uuid.uuid4().hex})


def _count(offer_id):
    with Session(get_engine()) as session:
        return session.scalar(select(func.count()).select_from(Booking).where(Booking.offer_id == offer_id))


def _update_offer(offer_id, **values):
    with Session(get_engine()) as session:
        for name, value in values.items():
            setattr(session.get(Offer, offer_id), name, value)
        session.commit()


# ---- 5.1 new bookings -------------------------------------------------------------------------------

def test_accepted_booking_is_created_with_an_offer_snapshot(make_offer):
    offer_id = make_offer()
    response = _post(_body(offer_id, "ref-1"))
    assert response.status_code == 201
    booking = response.json()
    assert booking["id"] and booking["clientReference"] == "ref-1" and booking["status"] == "confirmed"
    assert booking["createdAt"] == booking["updatedAt"] and "failure" not in booking
    snapshot = booking["offer"]
    assert snapshot["id"] == offer_id and snapshot["revision"] == "r1" and snapshot["price"]["amount"] == "100.00"
    assert _count(offer_id) == 1


@pytest.mark.parametrize(
    "overrides",
    [{"revision": "r9"}, {"amount": "99.99"}],
    ids=["revision", "price"],
)
def test_changed_terms_are_rejected_and_create_nothing(make_offer, overrides):
    offer_id = make_offer()
    response = _post(_body(offer_id, **overrides))
    assert response.status_code == 409 and response.json()["code"] == "OFFER_CHANGED"
    assert _count(offer_id) == 0


def test_expired_quote_is_rejected(make_offer):
    offer_id = make_offer(valid_until=get_clock().now() - timedelta(seconds=1))
    response = _post(_body(offer_id))
    assert response.status_code == 409 and response.json()["code"] == "OFFER_CHANGED"
    assert _count(offer_id) == 0


def test_quote_expiring_exactly_now_is_rejected(make_offer):
    get_clock().freeze()
    offer_id = make_offer(valid_until=get_clock().now())
    assert _post(_body(offer_id)).json()["code"] == "OFFER_CHANGED"


def test_unavailable_offer_is_rejected_even_with_a_stale_revision(make_offer):
    offer_id = make_offer(available=False, revision="r2")
    response = _post(_body(offer_id, revision="r1"))
    assert response.status_code == 409 and response.json()["code"] == "OFFER_UNAVAILABLE"
    assert _count(offer_id) == 0


def test_unknown_offer_is_404():
    response = _post(_body("does-not-exist"))
    assert response.status_code == 404 and response.json()["code"] == "NOT_FOUND"


def test_a_rejection_does_not_consume_the_reference(make_offer):
    offer_id = make_offer()
    assert _post(_body(offer_id, "ref-x", revision="r9")).status_code == 409
    assert _post(_body(offer_id, "ref-x")).status_code == 201


def test_request_validation_and_authentication(make_offer):
    offer_id = make_offer()
    assert client.post("/v1/bookings", json=_body(offer_id), headers=AUTH).status_code == 400  # no key
    assert _post({**_body(offer_id), "extra": 1}).status_code == 400
    assert _post({**_body(offer_id), "expectedPrice": {"amount": "100", "currency": "USD"}}).status_code == 400
    assert _post(_body(offer_id), key="k" * 129).status_code == 400
    unauthenticated = client.post("/v1/bookings", json=_body(offer_id), headers={"Idempotency-Key": "k"})
    assert unauthenticated.status_code == 401
    assert _count(offer_id) == 0


def test_failing_supplier_blocks_new_bookings(make_offer):
    offer_id = make_offer(provider_id="supplier-b")
    failures.set_failure("supplier-b", "unavailable")
    assert _post(_body(offer_id)).status_code == 503
    failures.set_failure("supplier-b", "rate_limited", retry_after=4)
    response = _post(_body(offer_id))
    assert response.status_code == 429 and response.headers["Retry-After"] == "4"
    assert _count(offer_id) == 0


# ---- 5.2 idempotency --------------------------------------------------------------------------------

def test_same_key_and_body_replays_the_same_booking_with_200(make_offer):
    offer_id = make_offer()
    body = _body(offer_id)
    first = _post(body, key="k1")
    second = _post(body, key="k1")
    assert first.status_code == 201 and second.status_code == 200
    assert second.json() == first.json()
    assert _count(offer_id) == 1


def test_replay_works_after_the_quote_expired_or_changed(make_offer):
    offer_id = make_offer()
    body = _body(offer_id)
    first = _post(body, key="k1").json()
    _update_offer(offer_id, valid_until=get_clock().now() - timedelta(hours=1), revision="r2", available=False)
    replay = _post(body, key="k1")
    assert replay.status_code == 200 and replay.json() == first
    assert replay.json()["offer"]["revision"] == "r1"  # the snapshot never changes


def test_property_order_does_not_matter(make_offer):
    offer_id = make_offer()
    body = _body(offer_id, "ref-order")
    first = _post(body, key="k1")
    reordered = {
        "expectedPrice": {"currency": "USD", "amount": "100.00"},
        "expectedOfferRevision": "r1",
        "offerId": offer_id,
        "clientReference": "ref-order",
    }
    second = client.post(
        "/v1/bookings", content=json.dumps(reordered),
        headers={**AUTH, "Idempotency-Key": "k1", "Content-Type": "application/json"},
    )
    assert second.status_code == 200 and second.json()["id"] == first.json()["id"]


def test_same_key_with_a_different_body_conflicts(make_offer):
    offer_id = make_offer()
    _post(_body(offer_id, "ref-a"), key="k1")
    for changed in (_body(offer_id, "ref-b"), _body(offer_id, "ref-a", amount="1.00")):
        response = _post(changed, key="k1")
        assert response.status_code == 409 and response.json()["code"] == "IDEMPOTENCY_CONFLICT"
    assert _count(offer_id) == 1


def test_new_key_with_an_existing_reference_conflicts(make_offer):
    offer_id = make_offer()
    _post(_body(offer_id, "ref-a"), key="k1")
    response = _post(_body(offer_id, "ref-a"), key="k2")
    assert response.status_code == 409 and response.json()["code"] == "REFERENCE_CONFLICT"
    assert _count(offer_id) == 1


def test_reference_conflict_is_reported_before_changed_terms(make_offer):
    offer_id = make_offer()
    _post(_body(offer_id, "ref-a"), key="k1")
    response = _post(_body(offer_id, "ref-a", revision="r9"), key="k2")
    assert response.json()["code"] == "REFERENCE_CONFLICT"


def test_keys_and_references_are_scoped_to_the_caller(make_offer):
    offer_id = make_offer()
    body = _body(offer_id, "ref-a")
    mine = _post(body, key="k1")
    theirs = _post(body, key="k1", headers=OTHER_AUTH)
    assert mine.status_code == 201 and theirs.status_code == 201
    assert mine.json()["id"] != theirs.json()["id"]
    assert _count(offer_id) == 2


def test_failed_and_pending_outcomes_are_replayed_unchanged(make_offer):
    offer_id = make_offer()
    outcomes.enqueue("failed")
    outcomes.enqueue("pending")
    failed_body, pending_body = _body(offer_id), _body(offer_id)
    failed = _post(failed_body, key="kf")
    pending = _post(pending_body, key="kp")
    assert failed.status_code == 201 and failed.json()["status"] == "failed"
    assert failed.json()["failure"]["code"] and failed.json()["failure"]["message"]
    assert pending.status_code == 201 and pending.json()["status"] == "pending" and "failure" not in pending.json()
    assert _post(failed_body, key="kf").json() == failed.json()
    assert _post(pending_body, key="kp").json() == pending.json()
    assert _count(offer_id) == 2  # a failed acceptance is never replaced by a new booking


def test_concurrent_identical_requests_create_exactly_one_booking(make_offer):
    offer_id = make_offer()
    body = _body(offer_id, "ref-race")

    def send(_):
        return TestClient(app).post("/v1/bookings", json=body, headers={**AUTH, "Idempotency-Key": "race"})

    with ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(pool.map(send, range(8)))
    assert sorted(r.status_code for r in responses) == [200] * 7 + [201]
    assert len({r.json()["id"] for r in responses}) == 1
    assert _count(offer_id) == 1
    with Session(get_engine()) as session:
        assert session.scalar(
            select(func.count()).select_from(IdempotencyRecord).where(IdempotencyRecord.idempotency_key == "race")
        ) == 1


def test_concurrent_requests_with_different_keys_and_one_reference_create_one_booking(make_offer):
    offer_id = make_offer()
    body = _body(offer_id, "ref-race-2")

    def send(number):
        return TestClient(app).post("/v1/bookings", json=body, headers={**AUTH, "Idempotency-Key": f"key-{number}"})

    with ThreadPoolExecutor(max_workers=6) as pool:
        responses = list(pool.map(send, range(6)))
    assert sorted(r.status_code for r in responses) == [201] + [409] * 5
    assert {r.json()["code"] for r in responses if r.status_code == 409} == {"REFERENCE_CONFLICT"}
    assert _count(offer_id) == 1
