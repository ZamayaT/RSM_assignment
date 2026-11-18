"""Booking lookups (5.3), lifecycle (5.4) and persistence. Run inside the container: they use the database."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from conftest import AUTH, OTHER_AUTH
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app import failures, outcomes
from app.clock import get_clock
from app.db import get_engine
from app.main import app
from test_bookings import _body, _post

client = TestClient(app)


# ---- 5.3 lookups ------------------------------------------------------------------------------------

def test_booking_can_be_read_by_id_and_by_reference(make_offer):
    offer_id = make_offer()
    created = _post(_body(offer_id, "ref-find")).json()
    by_id = client.get(f"/v1/bookings/{created['id']}", headers=AUTH)
    by_reference = client.get("/v1/bookings/by-reference/ref-find", headers=AUTH)
    assert by_id.status_code == 200 and by_reference.status_code == 200
    assert by_id.json() == created and by_reference.json() == created


def test_bookings_are_visible_only_to_the_creating_caller(make_offer):
    offer_id = make_offer()
    created = _post(_body(offer_id, "ref-private")).json()
    for path in (f"/v1/bookings/{created['id']}", "/v1/bookings/by-reference/ref-private"):
        response = client.get(path, headers=OTHER_AUTH)
        assert response.status_code == 404 and response.json()["code"] == "NOT_FOUND"


def test_the_same_reference_of_two_callers_resolves_to_each_callers_own_booking(make_offer):
    offer_id = make_offer()
    mine = _post(_body(offer_id, "ref-shared")).json()
    theirs = _post(_body(offer_id, "ref-shared"), headers=OTHER_AUTH).json()
    assert client.get("/v1/bookings/by-reference/ref-shared", headers=AUTH).json()["id"] == mine["id"]
    assert client.get("/v1/bookings/by-reference/ref-shared", headers=OTHER_AUTH).json()["id"] == theirs["id"]


def test_unknown_bookings_are_404_and_lookups_need_a_token():
    assert client.get("/v1/bookings/nope", headers=AUTH).status_code == 404
    assert client.get("/v1/bookings/by-reference/nope", headers=AUTH).status_code == 404
    assert client.get("/v1/bookings/nope").status_code == 401
    assert client.get("/v1/bookings/by-reference/nope").status_code == 401


def test_a_rejected_request_leaves_nothing_to_find(make_offer):
    offer_id = make_offer()
    _post(_body(offer_id, "ref-none", revision="r9"))
    assert client.get("/v1/bookings/by-reference/ref-none", headers=AUTH).status_code == 404


# ---- 5.4 lifecycle ----------------------------------------------------------------------------------

def _pending_booking(offer_id):
    outcomes.enqueue("pending")
    return _post(_body(offer_id)).json()


def test_pending_booking_resolves_to_confirmed_after_the_delay(make_offer):
    clock = get_clock()
    clock.freeze()
    pending = _pending_booking(make_offer())
    assert pending["status"] == "pending"

    clock.advance(timedelta(seconds=29))
    assert client.get(f"/v1/bookings/{pending['id']}", headers=AUTH).json()["status"] == "pending"

    clock.advance(timedelta(seconds=1))
    resolved = client.get(f"/v1/bookings/{pending['id']}", headers=AUTH).json()
    assert resolved["status"] == "confirmed" and "failure" not in resolved
    assert resolved["updatedAt"] > resolved["createdAt"] and resolved["createdAt"] == pending["createdAt"]
    assert resolved["offer"] == pending["offer"]


def test_resolution_is_also_seen_through_reference_lookup_and_replay(make_offer):
    clock = get_clock()
    clock.freeze()
    offer_id = make_offer()
    outcomes.enqueue("pending", 2)
    _post(_body(offer_id, "ref-1"), key="k1")
    second_body = _body(offer_id, "ref-2")
    second = _post(second_body, key="k2").json()
    clock.advance(timedelta(minutes=5))
    assert client.get("/v1/bookings/by-reference/ref-1", headers=AUTH).json()["status"] == "confirmed"
    replay = _post(second_body, key="k2")
    assert replay.status_code == 200 and replay.json()["id"] == second["id"] and replay.json()["status"] == "confirmed"


def test_terminal_outcomes_never_reverse(make_offer):
    clock = get_clock()
    clock.freeze()
    offer_id = make_offer()
    outcomes.enqueue("failed")
    failed = _post(_body(offer_id)).json()
    confirmed = _post(_body(offer_id)).json()
    clock.advance(timedelta(days=1))
    clock.advance(timedelta(days=-3))  # even moving the clock back changes nothing
    for before in (failed, confirmed):
        assert client.get(f"/v1/bookings/{before['id']}", headers=AUTH).json() == before


def test_a_pending_booking_resolved_through_control_stays_resolved(make_offer):
    pending = _pending_booking(make_offer())
    client.post(f"/control/bookings/{pending['id']}/resolve", json={"outcome": "failed"})
    get_clock().advance(timedelta(days=1))
    again = client.get(f"/v1/bookings/{pending['id']}", headers=AUTH).json()
    assert again["status"] == "failed" and again["failure"]["code"]


def test_concurrent_reads_resolve_a_pending_booking_once(make_offer):
    clock = get_clock()
    clock.freeze()
    pending = _pending_booking(make_offer())
    clock.advance(timedelta(minutes=1))

    def read(_):
        return TestClient(app).get(f"/v1/bookings/{pending['id']}", headers=AUTH).json()

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(read, range(6)))
    assert {r["status"] for r in results} == {"confirmed"}
    assert len({r["updatedAt"] for r in results}) == 1


def test_database_refuses_to_change_a_snapshot_total_or_terminal_outcome(make_offer):
    offer_id = make_offer()
    confirmed = _post(_body(offer_id)).json()
    pending = _pending_booking(offer_id)

    def update(booking_id, assignment):
        with Session(get_engine()) as session:
            session.execute(text(f"UPDATE mock_provider.bookings SET {assignment} WHERE id = :id"), {"id": booking_id})
            session.commit()

    for assignment in ("price_amount = 1", "offer_snapshot = '{}'", "currency = 'EUR'", "client_reference = 'x'"):
        with pytest.raises(DBAPIError, match="immutable"):
            update(pending["id"], assignment)
    with pytest.raises(DBAPIError, match="never changes"):
        update(confirmed["id"], "status = 'pending', updated_at = created_at")
    with pytest.raises(DBAPIError, match="never changes"):
        update(confirmed["id"], "updated_at = updated_at + interval '1 second'")
    update(pending["id"], "status = 'confirmed', updated_at = now()")  # pending may still become terminal


# ---- persistence ------------------------------------------------------------------------------------

def test_bookings_and_idempotency_survive_a_restart(make_offer):
    """Everything lives in PostgreSQL. A restart is simulated by dropping the engine and every in-memory
    setting; the real container restart is the recipe in mock_provider/README.md."""
    offer_id = make_offer()
    body = _body(offer_id, "ref-persist")
    created = _post(body, key="k-persist").json()

    get_engine().dispose()
    get_engine.cache_clear()
    failures.clear_all()
    outcomes.clear()
    restarted = TestClient(app)

    assert restarted.get(f"/v1/bookings/{created['id']}", headers=AUTH).json() == created
    replay = restarted.post("/v1/bookings", json=body, headers={**AUTH, "Idempotency-Key": "k-persist"})
    assert replay.status_code == 200 and replay.json() == created
    other_key = restarted.post("/v1/bookings", json=body, headers={**AUTH, "Idempotency-Key": "other-key"})
    assert other_key.status_code == 409 and other_key.json()["code"] == "REFERENCE_CONFLICT"
