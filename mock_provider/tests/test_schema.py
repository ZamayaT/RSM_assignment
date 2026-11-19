"""Schema tests. They need the database: run them with `docker compose exec mock_provider pytest`."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from app.db import SCHEMA, get_engine


@pytest.fixture
def conn():
    with get_engine().connect() as connection:
        transaction = connection.begin()
        yield connection
        transaction.rollback()


def _offer(conn, offer_id="o1"):
    now = datetime.now(timezone.utc)
    conn.execute(
        text(
            f"INSERT INTO {SCHEMA}.offers (id, provider_id, category, title, description, destination, starts_at,"
            " ends_at, travelers, price_amount, currency, revision, available, valid_until)"
            " VALUES (:id, 'supplier-a', 'activity', 't', 'd', 'Rome', :s, :e, 2, '10.00', 'USD', 'r1', true, :v)"
        ),
        {"id": offer_id, "s": now, "e": now + timedelta(hours=1), "v": now + timedelta(hours=1)},
    )


def _booking(conn, booking_id, caller="a", reference="ref", status="confirmed"):
    now = datetime.now(timezone.utc)
    conn.execute(
        text(
            f"INSERT INTO {SCHEMA}.bookings (id, caller, client_reference, offer_id, offer_snapshot, price_amount,"
            " currency, status, created_at, updated_at)"
            " VALUES (:id, :c, :r, 'o1', '{}', '10.00', 'USD', :st, :now, :now)"
        ),
        {"id": booking_id, "c": caller, "r": reference, "st": status, "now": now},
    )


def test_tables_exist_in_mock_schema():
    tables = set(inspect(get_engine()).get_table_names(schema=SCHEMA))
    assert {"offers", "bookings", "idempotency_records"} <= tables


def test_reference_unique_per_caller(conn):
    _offer(conn)
    _booking(conn, "b1")
    _booking(conn, "b2", caller="other")  # same reference, different caller: allowed
    with pytest.raises(IntegrityError):
        _booking(conn, "b3")


def test_idempotency_key_unique_per_caller(conn):
    _offer(conn)
    _booking(conn, "b1")
    _booking(conn, "b2", reference="ref2")
    insert = text(
        f"INSERT INTO {SCHEMA}.idempotency_records (caller, idempotency_key, request_fingerprint, booking_id)"
        " VALUES ('a', 'k', 'f', :b)"
    )
    conn.execute(insert, {"b": "b1"})
    with pytest.raises(IntegrityError):
        conn.execute(insert, {"b": "b2"})


def test_failed_booking_requires_failure(conn):
    _offer(conn)
    with pytest.raises(IntegrityError):
        _booking(conn, "b1", status="failed")
