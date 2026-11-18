import os

# Defaults so settings load outside Docker; inside the container the real environment wins.
os.environ.setdefault("POSTGRES_DB", "test")
os.environ.setdefault("POSTGRES_USER", "test")
os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("POSTGRES_HOST", "localhost")


# ---- shared helpers for booking and control tests (need the database: run inside the container) ----------
import uuid  # noqa: E402
from datetime import timedelta  # noqa: E402
from decimal import Decimal  # noqa: E402

import pytest  # noqa: E402
from sqlalchemy import delete  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

AUTH = {"Authorization": "Bearer travel-demo-token"}
OTHER_AUTH = {"Authorization": "Bearer other-demo-token"}


@pytest.fixture(autouse=True)
def _clean_control_state():
    """Every test starts and ends with no failure modes, no queued outcomes, and the configured clock."""
    from app import failures, outcomes
    from app.clock import get_clock

    def clean():
        failures.clear_all()
        outcomes.clear()
        get_clock().reset()

    clean()
    yield
    clean()


@pytest.fixture
def make_offer():
    """Create dedicated offers (price 100.00, revision r1, valid for a day); removed with their bookings after."""
    from app.clock import get_clock
    from app.db import get_engine
    from app.models import Booking, IdempotencyRecord, Offer

    created: list[str] = []

    def _make(provider_id="supplier-a", **overrides) -> str:
        now = get_clock().now()
        offer_id = f"test-{uuid.uuid4().hex[:12]}"
        values = dict(
            id=offer_id, provider_id=provider_id, category="activity", title="Test offer", description="d",
            destination="Rome", starts_at=now + timedelta(days=5), ends_at=now + timedelta(days=5, hours=2),
            travelers=2, price_amount=Decimal("100.00"), currency="USD", revision="r1", available=True,
            valid_until=now + timedelta(days=1), updated_at=now,
        )
        values.update(overrides)
        with Session(get_engine()) as session:
            session.add(Offer(**values))
            session.commit()
        created.append(offer_id)
        return offer_id

    yield _make

    with Session(get_engine()) as session:
        for offer_id in created:
            booking_ids = [b for (b,) in session.query(Booking.id).filter(Booking.offer_id == offer_id)]
            session.execute(delete(IdempotencyRecord).where(IdempotencyRecord.booking_id.in_(booking_ids)))
            session.execute(delete(Booking).where(Booking.offer_id == offer_id))
            session.execute(delete(Offer).where(Offer.id == offer_id))
        session.commit()
