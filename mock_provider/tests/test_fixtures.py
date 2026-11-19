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
    assert {o["provider_id"] for o in offers} == {"supplier-alamo", "supplier-boots", "supplier-croc"}

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


def test_catalogue_fills_november_december_and_january():
    clock = datetime(2026, 11, 19, 9, 0, tzinfo=timezone.utc)
    offers = build_offers(clock)
    months = defaultdict(int)
    for o in offers:
        months[o["starts_at"].strftime("%Y-%m")] += 1
    assert {"2026-11", "2026-12", "2027-01"} <= set(months)
    assert all(count > 100 for count in months.values())
    assert min(o["starts_at"] for o in offers).date().isoformat() >= "2026-11-20"
    assert max(o["starts_at"] for o in offers).date().isoformat() <= "2027-02-01"
    # every category has offers in every month, so a trip in any of those months finds options
    for category in ("transport", "accommodation", "activity"):
        assert {o["starts_at"].strftime("%Y-%m") for o in offers if o["category"] == category} >= {"2026-11", "2026-12", "2027-01"}


def test_a_clock_past_the_window_gets_the_next_months_instead():
    later = datetime(2031, 6, 1, 9, 0, tzinfo=timezone.utc)
    offers = build_offers(later)
    assert min(o["starts_at"] for o in offers) > later
    assert (max(o["starts_at"] for o in offers) - later).days <= 100


def test_museum_food_and_other_activities_exist_for_every_destination():
    offers = build_offers(NOW)
    for destination in ("Lisbon", "Paris", "Rome"):
        titles = {o["title"] for o in offers if o["destination"] == destination and o["category"] == "activity"}
        assert any(t.startswith("Museum tour") for t in titles)
        assert any(t.startswith("Food places tour") for t in titles)
        assert len(titles) >= 8  # the two base activities, museum, food and other tours


def test_base_offer_ids_and_prices_stay_stable():
    by_id = {o["id"]: o for o in build_offers(NOW)}
    assert by_id["rome-activity-supplier-boots-1-p2"]["price_amount"] == Decimal("107.64")
    assert by_id["lisbon-accommodation-supplier-alamo-p2"]["title"] == "3-night stay in Lisbon (Supplier Alamo)"


def test_season_changes_the_price_of_repeated_listings():
    from datetime import date

    from app.fixtures import season_factor

    assert season_factor(date(2026, 11, 25)) == Decimal("1.00")
    assert season_factor(date(2026, 12, 10)) == Decimal("1.10")
    assert season_factor(date(2026, 12, 24)) == Decimal("1.25")
    assert season_factor(date(2027, 1, 2)) == Decimal("1.25")
    assert season_factor(date(2027, 1, 20)) == Decimal("0.90")
