"""Fixture data: the mock's catalogue. Pure data generation plus a seeding helper.

Everything is deterministic and relative to the clock, so a given clock instant always yields the same
catalogue. Offer dates are destination-local calendar days counted from the clock's "today".
"""
from datetime import datetime, time, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from math import ceil
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.clock import get_clock
from app.db import get_engine
from app.models import Booking, IdempotencyRecord, Offer

# Destination -> IANA timezone (destination-local calendar days).
DESTINATIONS = {
    "Lisbon": "Europe/Lisbon",
    "Paris": "Europe/Paris",
    "Rome": "Europe/Rome",
}

# Transport origins -> flight hours (rough, not modelled beyond the offer duration).
ORIGINS = {"London": 2.5, "New York": 8.0, "Madrid": 2.0}

# Per-person transport price in USD for origin -> destination.
TRANSPORT_BASE = {
    ("London", "Lisbon"): Decimal("119.90"), ("London", "Paris"): Decimal("89.55"),
    ("London", "Rome"): Decimal("139.99"),
    ("New York", "Lisbon"): Decimal("519.75"), ("New York", "Paris"): Decimal("479.20"),
    ("New York", "Rome"): Decimal("559.40"),
    ("Madrid", "Lisbon"): Decimal("69.99"), ("Madrid", "Paris"): Decimal("109.35"),
    ("Madrid", "Rome"): Decimal("94.85"),
}
NIGHT_BASE = {  # per room per night
    "Lisbon": Decimal("94.50"), "Paris": Decimal("159.90"), "Rome": Decimal("129.75"),
}

# Suppliers per category: at least two each, so partial results can be demonstrated.
SUPPLIERS = {
    "transport": ("supplier-a", "supplier-b"),
    "accommodation": ("supplier-a", "supplier-b", "supplier-c"),
    "activity": ("supplier-b", "supplier-c"),
}
ALL_SUPPLIERS = frozenset(supplier for suppliers in SUPPLIERS.values() for supplier in suppliers)
SUPPLIER_FACTOR = {"supplier-a": Decimal("1.00"), "supplier-b": Decimal("0.90"), "supplier-c": Decimal("1.15")}

# Each offer is a quote for one party size; searches match the requested party exactly.
PARTY_SIZES = (1, 2, 4)

# (title, per-person USD, start hour) per destination.
ACTIVITIES = {
    "Lisbon": (("Alfama walking tour", Decimal("34.50"), 10), ("Sintra day trip", Decimal("69.90"), 9)),
    "Paris": (("Seine evening cruise", Decimal("39.95"), 19), ("Louvre guided visit", Decimal("64.25"), 10)),
    "Rome": (("Colosseum and Forum tour", Decimal("59.80"), 9), ("Vatican Museums tour", Decimal("54.90"), 14)),
}

# Quote lifetimes cycle through short and long values so expiry scenarios exist from the start.
VALIDITY_CYCLE = (timedelta(minutes=30), timedelta(hours=6), timedelta(days=1), timedelta(days=3))
UNAVAILABLE_EVERY = 11  # every Nth offer is sold out


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _slug(text: str) -> str:
    return text.lower().replace(" ", "-")


def build_offers(now: datetime) -> list[dict]:
    """Return the whole catalogue as dicts matching the `Offer` model columns, relative to `now`."""
    offers: list[dict] = []

    def add(offer_id, provider, category, title, description, destination, origin, start, end, travelers, price):
        index = len(offers)
        offers.append(
            {
                "id": offer_id,
                "provider_id": provider,
                "category": category,
                "title": title,
                "description": description,
                "destination": destination,
                "origin": origin,
                "starts_at": start.astimezone(timezone.utc),
                "ends_at": end.astimezone(timezone.utc),
                "travelers": travelers,
                "price_amount": _money(price),
                "currency": "USD",
                "revision": "r1",
                "available": (index + 1) % UNAVAILABLE_EVERY != 0,
                "valid_until": now + VALIDITY_CYCLE[index % len(VALIDITY_CYCLE)],
                "updated_at": now,
            }
        )

    for destination, tz_name in DESTINATIONS.items():
        tz = ZoneInfo(tz_name)
        today = now.astimezone(tz).date()

        def at(day_offset: int, hour: int, minute: int = 0) -> datetime:
            return datetime.combine(today + timedelta(days=day_offset), time(hour, minute), tzinfo=tz)

        dest_slug = _slug(destination)

        for origin, hours in ORIGINS.items():
            for position, supplier in enumerate(SUPPLIERS["transport"]):
                start = at(21 + position * 2, 8 + position * 4)
                end = start + timedelta(hours=hours)
                for travelers in PARTY_SIZES:
                    price = TRANSPORT_BASE[(origin, destination)] * SUPPLIER_FACTOR[supplier] * travelers
                    add(
                        f"{dest_slug}-transport-{_slug(origin)}-{supplier}-p{travelers}",
                        supplier, "transport",
                        f"Flight {origin} to {destination}",
                        f"One-way flight from {origin} to {destination} for {travelers} traveler(s), total price.",
                        destination, origin, start, end, travelers, price,
                    )

        for position, supplier in enumerate(SUPPLIERS["accommodation"]):
            start = at(22 + position, 15)
            end = at(25 + position, 11)  # three nights
            for travelers in PARTY_SIZES:
                rooms = ceil(travelers / 2)
                price = NIGHT_BASE[destination] * SUPPLIER_FACTOR[supplier] * 3 * rooms
                add(
                    f"{dest_slug}-accommodation-{supplier}-p{travelers}",
                    supplier, "accommodation",
                    f"3-night stay in {destination} ({supplier})",
                    f"Three nights in {rooms} room(s) in {destination} for {travelers} traveler(s), total price.",
                    destination, None, start, end, travelers, price,
                )

        for position, supplier in enumerate(SUPPLIERS["activity"]):
            for number, (title, per_person, hour) in enumerate(ACTIVITIES[destination], start=1):
                start = at(23 + position + number, hour)
                end = start + timedelta(hours=3)
                for travelers in PARTY_SIZES:
                    price = per_person * SUPPLIER_FACTOR[supplier] * travelers
                    add(
                        f"{dest_slug}-activity-{supplier}-{number}-p{travelers}",
                        supplier, "activity",
                        title,
                        f"{title} in {destination} for {travelers} traveler(s), total price.",
                        destination, None, start, end, travelers, price,
                    )

    return offers


def seed_if_empty() -> bool:
    """Insert the fixture catalogue when there are no offers. Returns True if it seeded."""
    with Session(get_engine()) as session:
        if session.scalar(select(func.count()).select_from(Offer)):
            return False
        session.add_all(Offer(**row) for row in build_offers(get_clock().now()))
        session.commit()
        return True


def reseed() -> int:
    """Deliberate reset: delete all bookings, idempotency records and offers, then reload the fixtures
    relative to the current clock. Returns the number of offers loaded."""
    with Session(get_engine()) as session:
        session.execute(delete(IdempotencyRecord))
        session.execute(delete(Booking))
        session.execute(delete(Offer))
        rows = build_offers(get_clock().now())
        session.add_all(Offer(**row) for row in rows)
        session.commit()
        return len(rows)
