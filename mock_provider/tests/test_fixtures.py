from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_engine
from app.fixtures import build_offers, seed_if_empty
from app.models import Offer

NOW = datetime(2030, 1, 15, 9, 0, tzinfo=timezone.utc)


def test_catalogue_covers_destinations_origins_categories_and_suppliers():
    offers = build_offers(NOW)
    assert {o["destination"] for o in offers} == {"Lisbon", "Paris", "Rome"}
    assert {o["origin"] for o in offers if o["category"] == "transport"} == {"London", "New York", "Madrid"}
    assert {o["provider_id"] for o in offers} == {"supplier-a", "supplier-b", "supplier-c"}

    suppliers = defaultdict(set)
    for o in offers:
        suppliers[o["category"]].add(o["provider_id"])
    assert set(suppliers) == {"transport", "accommodation", "activity"}
    assert all(len(found) >= 2 for found in suppliers.values())


def test_every_destination_has_every_category():
    offers = build_offers(NOW)
    for destination in ("Lisbon", "Paris", "Rome"):
        assert {o["category"] for o in offers if o["destination"] == destination} == {
            "transport", "accommodation", "activity",
        }


def test_dates_are_in_the_future_of_the_clock():
    for o in build_offers(NOW):
        assert o["starts_at"] > NOW
        assert o["ends_at"] > o["starts_at"]
        assert o["valid_until"] > NOW
        assert o["starts_at"].tzinfo is not None


def test_catalogue_follows_the_clock():
    later = datetime(2031, 6, 1, 9, 0, tzinfo=timezone.utc)
    assert min(o["starts_at"] for o in build_offers(later)) > later
    assert build_offers(NOW) == build_offers(NOW)  # deterministic


def test_prices_availability_and_expiries_vary():
    offers = build_offers(NOW)
    assert len({o["price_amount"] for o in offers}) > 10
    assert {o["available"] for o in offers} == {True, False}
    assert len({o["valid_until"] - NOW for o in offers}) >= 3
    assert len({o["id"] for o in offers}) == len(offers)


def test_prices_have_cents_and_two_decimals():
    prices = [o["price_amount"] for o in build_offers(NOW)]
    assert all(p == p.quantize(Decimal("0.01")) for p in prices)
    assert sum(p != p.to_integral_value() for p in prices) > len(prices) * 0.8


def test_seed_if_empty_does_not_duplicate():
    # The container seeds on startup, so the table is already populated here.
    with Session(get_engine()) as session:
        before = session.scalar(select(func.count()).select_from(Offer))
    assert before > 0
    assert seed_if_empty() is False
    with Session(get_engine()) as session:
        assert session.scalar(select(func.count()).select_from(Offer)) == before
