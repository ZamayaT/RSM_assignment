"""Idempotency and recovery: no duplicate bookings, and an unknown outcome is settled by asking the provider."""
import uuid

import httpx
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import get_engine
from app.models import BookingAttempt
from app.worker import process_next_due, run_once
from tests.booking_helpers import (  # noqa: F401
    MOCK,
    attempt_count,
    book_current,
    book_request,
    control,
    fresh_item,
    latest_attempt,
    mock,
    no_waiting,
    provider_booking,
    reference_of,
)


def make_initiated(attempt_id: str) -> None:
    """Put an attempt back into the state of 'saved, then the backend died': no outcome recorded, due now."""
    with get_engine().begin() as connection:
        connection.execute(
            text(
                "UPDATE booking_attempts SET status='initiated', provider_booking_id=NULL, accepted_offer=NULL, "
                "accepted_amount=NULL, failure_code=NULL, failure_message=NULL, next_check_at=now() WHERE id=:i"
            ),
            {"i": attempt_id},
        )


def test_same_intent_twice_creates_one_attempt_and_one_provider_booking(client):
    headers, trip_id, offer, item = fresh_item(client)
    intent = str(uuid.uuid4())

    first = book_request(client, headers, trip_id, item, intent=intent)
    second = book_request(client, headers, trip_id, item, intent=intent)

    assert first.status_code == 201 and second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    assert first.json()["providerBookingId"] == second.json()["providerBookingId"]
    assert attempt_count(trip_id) == 1
    assert provider_booking(reference_of(first.json()["id"]))["id"] == first.json()["providerBookingId"]


def test_same_intent_with_different_terms_is_refused_not_rebooked(client):
    headers, trip_id, offer, item = fresh_item(client)
    intent = str(uuid.uuid4())
    book_request(client, headers, trip_id, item, intent=intent)

    other = book_request(client, headers, trip_id, item, intent=intent, price={"amount": "1.00", "currency": "USD"})

    assert other.status_code == 409 and other.json()["code"] == "INTENT_CONFLICT"
    assert attempt_count(trip_id) == 1


def test_lost_response_is_unknown_then_reconciled_to_the_real_status_by_reference(client, no_waiting):
    headers, trip_id, offer, item = fresh_item(client)
    control("PUT", f"/suppliers/{offer['providerId']}/latency", milliseconds=8000)  # slower than the 5 s timeout
    control("PUT", "/booking-outcomes", outcome="failed", count=1)

    attempt = book_request(client, headers, trip_id, item).json()

    assert attempt["status"] == "unknown"  # not failed, not confirmed
    control("PUT", f"/suppliers/{offer['providerId']}/latency", milliseconds=0)
    assert run_once() == 1
    settled = latest_attempt(client, headers, trip_id)
    # the provider did accept it and its real outcome (forced to failed above) is what we now show
    assert settled["status"] == "failed" and settled["unresolved"] is False
    assert provider_booking(reference_of(attempt["id"]))["status"] == "failed"
    assert attempt_count(trip_id) == 1


def test_lost_response_that_ended_confirmed_is_not_booked_twice(client, no_waiting):
    headers, trip_id, offer, item = fresh_item(client)
    control("PUT", f"/suppliers/{offer['providerId']}/latency", milliseconds=8000)
    attempt = book_request(client, headers, trip_id, item).json()
    assert attempt["status"] == "unknown"
    control("PUT", f"/suppliers/{offer['providerId']}/latency", milliseconds=0)

    run_once()

    settled = latest_attempt(client, headers, trip_id)
    assert settled["status"] == "confirmed"
    assert settled["providerBookingId"] == provider_booking(reference_of(attempt["id"]))["id"]


def test_booking_the_provider_never_received_is_replayed_with_the_same_key(client, no_waiting):
    headers, trip_id, offer, item = fresh_item(client)
    control("PUT", f"/suppliers/{offer['providerId']}/failure", mode="unavailable")
    attempt = book_request(client, headers, trip_id, item).json()
    assert attempt["status"] == "unknown"
    reference = reference_of(attempt["id"])
    assert provider_booking(reference) is None
    with get_engine().connect() as connection:
        key_before = connection.execute(
            text("SELECT idempotency_key FROM booking_attempts WHERE id=:i"), {"i": attempt["id"]}
        ).scalar_one()
    control("DELETE", f"/suppliers/{offer['providerId']}/failure")

    run_once()

    settled = latest_attempt(client, headers, trip_id)
    assert settled["status"] == "confirmed" and provider_booking(reference)["id"] == settled["providerBookingId"]
    with get_engine().connect() as connection:
        key_after = connection.execute(
            text("SELECT idempotency_key FROM booking_attempts WHERE id=:i"), {"i": attempt["id"]}
        ).scalar_one()
    assert key_before == key_after and key_before.startswith("booking-intent-")


def test_replay_of_a_booking_whose_offer_changed_meanwhile_ends_failed_not_booked(client, no_waiting):
    headers, trip_id, offer, item = fresh_item(client)
    control("PUT", f"/suppliers/{offer['providerId']}/failure", mode="unavailable")
    attempt = book_request(client, headers, trip_id, item).json()
    assert attempt["status"] == "unknown"
    control("DELETE", f"/suppliers/{offer['providerId']}/failure")
    control("POST", f"/offers/{offer['id']}", price="888.00")

    run_once()

    settled = latest_attempt(client, headers, trip_id)
    assert settled["status"] == "failed" and settled["failure"]["code"] == "OFFER_CHANGED"
    assert provider_booking(reference_of(attempt["id"])) is None


def test_unreachable_provider_ends_unresolved_never_failed_or_confirmed(client, no_waiting, monkeypatch):
    headers, trip_id, offer, item = fresh_item(client)
    control("PUT", f"/suppliers/{offer['providerId']}/failure", mode="unavailable")
    attempt = book_request(client, headers, trip_id, item).json()
    assert attempt["status"] == "unknown"
    monkeypatch.setattr(no_waiting, "booking_unresolved_after_seconds", 0)

    assert run_once() == 1

    flagged = latest_attempt(client, headers, trip_id)
    assert flagged["status"] == "unknown" and flagged["unresolved"] is True
    assert run_once() == 0  # the worker stops on its own; only "check again" tries from here
    control("DELETE", f"/suppliers/{offer['providerId']}/failure")
    checked = client.post(f"/trips/{trip_id}/bookings/{attempt['id']}/check", headers=headers).json()
    assert checked["status"] == "confirmed" and checked["unresolved"] is False


def test_check_again_while_the_provider_is_still_down_changes_nothing(client, no_waiting):
    headers, trip_id, offer, item = fresh_item(client)
    control("PUT", f"/suppliers/{offer['providerId']}/failure", mode="unavailable")
    attempt = book_request(client, headers, trip_id, item).json()

    checked = client.post(f"/trips/{trip_id}/bookings/{attempt['id']}/check", headers=headers)

    assert checked.status_code == 200 and checked.json()["status"] == "unknown"
    assert attempt_count(trip_id) == 1


def test_stuck_initiated_attempt_is_recovered_by_reference(client, no_waiting, monkeypatch):
    headers, trip_id, offer, item = fresh_item(client)
    attempt = book_current(client, headers, trip_id, item).json()
    monkeypatch.setattr(no_waiting, "booking_stale_initiated_seconds", 0)
    make_initiated(attempt["id"])  # the provider did get it, but the backend never recorded the answer

    run_once()

    settled = latest_attempt(client, headers, trip_id)
    assert settled["status"] == "confirmed" and settled["providerBookingId"] == attempt["providerBookingId"]
    assert attempt_count(trip_id) == 1


def test_young_initiated_attempt_is_left_alone(client, no_waiting):
    headers, trip_id, offer, item = fresh_item(client)
    attempt = book_current(client, headers, trip_id, item).json()
    make_initiated(attempt["id"])  # stale threshold is still 60 s: the creating request may still be running

    process_next_due()

    assert latest_attempt(client, headers, trip_id)["status"] == "initiated"


def test_pending_booking_is_polled_to_its_final_status(client, no_waiting):
    headers, trip_id, offer, item = fresh_item(client)
    control("PUT", "/booking-outcomes", outcome="pending", count=1)
    attempt = book_current(client, headers, trip_id, item).json()
    assert attempt["status"] == "pending"

    assert process_next_due() is True  # still pending: read again, nothing changes
    assert latest_attempt(client, headers, trip_id)["status"] == "pending"
    httpx.post(f"{MOCK}/control/bookings/{attempt['providerBookingId']}/resolve", json={"outcome": "confirmed"}).raise_for_status()
    assert process_next_due() is True

    assert latest_attempt(client, headers, trip_id)["status"] == "confirmed"
    assert process_next_due() is False  # final: nothing more to do


def test_a_restart_loses_and_duplicates_nothing(client, no_waiting):
    headers, trip_id, offer, item = fresh_item(client)
    control("PUT", f"/suppliers/{offer['providerId']}/latency", milliseconds=8000)
    attempt = book_request(client, headers, trip_id, item).json()
    assert attempt["status"] == "unknown"
    control("PUT", f"/suppliers/{offer['providerId']}/latency", milliseconds=0)

    get_engine().dispose()  # every connection is gone, as after a restart; the attempt lives in the database

    assert run_once() == 1
    assert run_once() == 0
    assert latest_attempt(client, headers, trip_id)["status"] == "confirmed"
    assert attempt_count(trip_id) == 1


def test_an_attempt_being_processed_is_skipped_by_another_worker(client, no_waiting):
    headers, trip_id, offer, item = fresh_item(client)
    control("PUT", "/booking-outcomes", outcome="pending", count=1)
    book_current(client, headers, trip_id, item)

    with Session(get_engine()) as holder:  # another worker holds the row
        holder.execute(text("SELECT id FROM booking_attempts WHERE next_check_at IS NOT NULL FOR UPDATE"))
        assert process_next_due() is False
    assert process_next_due() is True
