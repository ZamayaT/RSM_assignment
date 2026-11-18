"""Budget calculations (pure) and the read endpoints, with items inserted directly in the database."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.budget import CONFIRMED, ESTIMATE, BudgetLine, compute_totals, money
from app.db import get_session
from app.models import ItineraryItem
from tests.conftest import VALID_TRIP, login


def line(amount, kind=ESTIMATE):
    return BudgetLine("x", "item", "activity", None if amount is None else Decimal(amount), kind)


# --- pure calculation ---


def test_totals_are_exact_sums_and_remaining_is_budget_minus_combined():
    totals = compute_totals([line("100.10"), line("0.20"), line("50.00", CONFIRMED)], Decimal("200.00"))

    assert totals.estimated == Decimal("100.30")
    assert totals.confirmed == Decimal("50.00")
    assert totals.combined == Decimal("150.30")
    assert totals.remaining == Decimal("49.70") and not totals.over_budget


def test_over_budget_gives_a_negative_remaining():
    totals = compute_totals([line("120.00")], Decimal("100.00"))

    assert totals.remaining == Decimal("-20.00") and totals.over_budget


def test_exactly_on_budget_is_not_over():
    totals = compute_totals([line("100.00")], Decimal("100.00"))

    assert totals.remaining == Decimal("0.00") and not totals.over_budget


def test_items_without_price_are_left_out():
    totals = compute_totals([line(None), line("10.00")], Decimal("50.00"))

    assert totals.estimated == Decimal("10.00")


def test_empty_itinerary():
    totals = compute_totals([], Decimal("500"))

    assert (totals.estimated, totals.confirmed, totals.combined, totals.remaining) == (
        Decimal("0.00"),
        Decimal("0.00"),
        Decimal("0.00"),
        Decimal("500.00"),
    )


def test_rounding_is_half_up_to_the_cent():
    assert money(Decimal("0.005")) == Decimal("0.01")
    assert money(Decimal("2.675")) == Decimal("2.68")
    assert money(Decimal("2.674")) == Decimal("2.67")


# --- endpoints ---


def add_item(trip_id, offer_id, price, position, valid_until=None, **overrides):
    now = datetime.now(timezone.utc)
    values = dict(
        trip_id=trip_id,
        position=position,
        offer_id=offer_id,
        provider_id="supplier-a",
        category="activity",
        title=f"Offer {offer_id}",
        description="d",
        destination="Lisbon",
        starts_at=now + timedelta(days=1),
        ends_at=now + timedelta(days=1, hours=2),
        travelers=2,
        price_amount=Decimal(price),
        currency="USD",
        revision="r1",
        available=True,
        valid_until=valid_until or now + timedelta(days=1),
    )
    values.update(overrides)
    session = next(get_session())
    try:
        session.add(ItineraryItem(**values))
        session.commit()
    finally:
        session.close()


def make_trip(client, **overrides):
    headers = login(client, "alice")
    trip = client.post("/trips", json={**VALID_TRIP, **overrides}, headers=headers).json()
    return headers, trip


def test_itinerary_is_empty_for_a_new_trip(client):
    headers, trip = make_trip(client)

    body = client.get(f"/trips/{trip['id']}/itinerary", headers=headers).json()

    assert body == {"version": 1, "items": []}


def test_itinerary_lists_items_in_stored_order_with_status_and_warnings(client):
    headers, trip = make_trip(client)
    add_item(trip["id"], "second", "20.00", position=2)
    add_item(trip["id"], "first", "10.50", position=1, valid_until=datetime.now(timezone.utc) - timedelta(hours=1))

    body = client.get(f"/trips/{trip['id']}/itinerary", headers=headers).json()

    assert [i["offerId"] for i in body["items"]] == ["first", "second"]
    first = body["items"][0]
    assert first["price"] == {"amount": "10.50", "currency": "USD"}
    assert first["status"] == "expired_quote"
    assert "EXPIRED_QUOTE" in [w["code"] for w in first["warnings"]]
    assert body["items"][1]["status"] == "estimate"


def test_budget_totals_and_lines(client):
    headers, trip = make_trip(client, budget="100.00")
    add_item(trip["id"], "a", "60.00", position=1)
    add_item(trip["id"], "b", "55.25", position=2, valid_until=datetime.now(timezone.utc) - timedelta(hours=1))

    body = client.get(f"/trips/{trip['id']}/budget", headers=headers).json()

    assert body["estimatedTotal"] == "115.25" and body["confirmedTotal"] == "0.00"
    assert body["combinedTotal"] == "115.25" and body["budget"] == "100.00"
    assert body["remaining"] == "-15.25" and body["overBudget"] is True
    assert [(l["amount"], l["kind"], l["expired"]) for l in body["lines"]] == [
        ("60.00", "estimate", False),
        ("55.25", "estimate", True),
    ]


def test_read_access_follows_trip_membership(client):
    headers, trip = make_trip(client)
    client.post(f"/trips/{trip['id']}/participants", json={"username": "bob", "role": "viewer"}, headers=headers)

    for path in ("itinerary", "budget"):
        assert client.get(f"/trips/{trip['id']}/{path}", headers=login(client, "bob")).status_code == 200
        assert client.get(f"/trips/{trip['id']}/{path}", headers=login(client, "carol")).status_code == 404
        assert client.get(f"/trips/{trip['id']}/{path}").status_code == 401
