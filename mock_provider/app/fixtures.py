"""Fixture data: the mock's catalogue. Pure data generation plus a seeding helper.

Everything is deterministic and relative to the clock, so a given clock instant always yields the same
catalogue. Offer dates are destination-local calendar days. A base catalogue (one listing of each kind, starting 21
days or more after the clock's "today", with stable ids) is extended with repeated listings that fill the days from
the day after the clock's "today" until 31 January 2027 (the catalogue covers November 2026 to January 2027; a
clock past that window gets the next 92 days instead).
"""
import zlib
from datetime import date, datetime, time, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from math import ceil
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, insert, select
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
    "transport": ("supplier-alamo", "supplier-boots"),
    "accommodation": ("supplier-alamo", "supplier-boots", "supplier-croc"),
    "activity": ("supplier-boots", "supplier-croc"),
}
ALL_SUPPLIERS = frozenset(supplier for suppliers in SUPPLIERS.values() for supplier in suppliers)
SUPPLIER_NAMES = {"supplier-alamo": "Supplier Alamo", "supplier-boots": "Supplier Boots", "supplier-croc": "Supplier Croc"}
SUPPLIER_FACTOR = {"supplier-alamo": Decimal("1.00"), "supplier-boots": Decimal("0.90"), "supplier-croc": Decimal("1.15")}

# Each offer is a quote for one party size; searches match the requested party exactly.
PARTY_SIZES = (1, 2, 4)

# (title, per-person USD, start hour) per destination.
ACTIVITIES = {
    "Lisbon": (("Alfama walking tour", Decimal("34.50"), 10), ("Sintra day trip", Decimal("69.90"), 9)),
    "Paris": (("Seine evening cruise", Decimal("39.95"), 19), ("Louvre guided visit", Decimal("64.25"), 10)),
    "Rome": (("Colosseum and Forum tour", Decimal("59.80"), 9), ("Vatican Museums tour", Decimal("54.90"), 14)),
}

# More activities (museum, food and other tours). They are added after the base ones, so the ids of the base
# activities (numbers 1 and 2) never change.
EXTRA_ACTIVITIES = {
    "Lisbon": (
        ("Museum tour: Gulbenkian and the Tile Museum", Decimal("44.00"), 11),
        ("Food places tour: pastries and petiscos", Decimal("58.50"), 12),
        ("Tram 28 and viewpoints ride", Decimal("29.90"), 15),
        ("Sunset sailing on the Tagus", Decimal("79.00"), 18),
        ("Fado dinner evening", Decimal("85.50"), 20),
        ("Cascais coast bike ride", Decimal("41.25"), 10),
    ),
    "Paris": (
        ("Museum tour: Orsay and Orangerie", Decimal("52.00"), 11),
        ("Food places tour: bakeries and cheese in Le Marais", Decimal("72.50"), 12),
        ("Montmartre walking tour", Decimal("27.90"), 15),
        ("Versailles day trip", Decimal("89.90"), 9),
        ("Croissant baking class", Decimal("95.00"), 14),
        ("Night photography walk", Decimal("49.00"), 21),
    ),
    "Rome": (
        ("Museum tour: Capitoline Museums", Decimal("38.00"), 11),
        ("Food places tour: Trastevere", Decimal("66.00"), 12),
        ("Pasta-making class", Decimal("79.50"), 16),
        ("Catacombs and Appian Way", Decimal("45.50"), 10),
        ("Vespa city ride", Decimal("99.00"), 15),
        ("Golden hour at the Gianicolo", Decimal("24.50"), 18),
    ),
}

# The calendar the catalogue is spread over (the clock's "today" moves the start forward, never backward).
CATALOGUE_START = date(2026, 11, 1)
CATALOGUE_END = date(2027, 1, 31)
FALLBACK_DAYS = 92  # a clock past CATALOGUE_END gets this many days from the day after its "today"

# Quote lifetimes cycle through short and long values so expiry scenarios exist from the start.
VALIDITY_CYCLE = (timedelta(minutes=30), timedelta(hours=6), timedelta(days=1), timedelta(days=3))
UNAVAILABLE_EVERY = 11  # every Nth offer is sold out


# Simulated restrictions per category. The choice for an offer is a stable function of its id, so the same
# catalogue always carries the same restrictions; some offers state none (an empty list).
RESTRICTIONS = {
    "transport": [
        ["Non-refundable simulated booking"],
        ["Carry-on bag only", "Non-refundable simulated booking"],
        [],
        ["Photo ID required at check-in"],
    ],
    "accommodation": [
        ["Non-refundable simulated booking", "Photo ID required at check-in"],
        ["Minimum age 18 to check in"],
        [],
        ["Non-refundable simulated booking"],
    ],
    "activity": [
        ["Non-refundable simulated booking"],
        ["Minimum age 18"],
        [],
        ["Weather permitting; the simulated booking is not refunded"],
    ],
}


def restrictions_for(offer_id: str, category: str) -> list[str]:
    options = RESTRICTIONS[category]
    return list(options[zlib.crc32(offer_id.encode()) % len(options)])


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def catalogue_window(today: date) -> tuple[date, date]:
    """First and last day the repeated listings may start on."""
    start = max(CATALOGUE_START, today + timedelta(days=1))
    if start > CATALOGUE_END:
        start = today + timedelta(days=1)
        return start, start + timedelta(days=FALLBACK_DAYS - 1)
    return start, CATALOGUE_END


def season_factor(day: date) -> Decimal:
    """Prices of the repeated listings follow the season: holidays cost more, January less."""
    if (day.month, day.day) >= (12, 20) or (day.month, day.day) <= (1, 3):
        return Decimal("1.25")
    if day.month == 12:
        return Decimal("1.10")
    if day.month == 1:
        return Decimal("0.90")
    return Decimal("1.00")


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
                "restrictions": restrictions_for(offer_id, category),
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
                    f"3-night stay in {destination} ({SUPPLIER_NAMES[supplier]})",
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

        # Repeated listings: the same kinds of offers on later days, so every week of the window has options.
        first, last = catalogue_window(today)
        span = (last - first).days
        dest_index = list(DESTINATIONS).index(destination)

        def days(step: int, phase: int) -> list[date]:
            return [first + timedelta(days=d) for d in range(phase % step, span + 1, step)]

        for origin_index, origin in enumerate(ORIGINS):
            for position, supplier in enumerate(SUPPLIERS["transport"]):
                for number, day in enumerate(days(4, origin_index + position * 2 + dest_index), start=1):
                    start = datetime.combine(day, time(7 + ((number + position) % 3) * 4, 0), tzinfo=tz)
                    end = start + timedelta(hours=ORIGINS[origin])
                    for travelers in PARTY_SIZES:
                        price = TRANSPORT_BASE[(origin, destination)] * SUPPLIER_FACTOR[supplier] * travelers * season_factor(day)
                        add(
                            f"{dest_slug}-transport-{_slug(origin)}-{supplier}-s{number}-p{travelers}",
                            supplier, "transport",
                            f"Flight {origin} to {destination}",
                            f"One-way flight from {origin} to {destination} for {travelers} traveler(s), total price.",
                            destination, origin, start, end, travelers, price,
                        )

        for position, supplier in enumerate(SUPPLIERS["accommodation"]):
            for number, day in enumerate(days(5, position * 2 + dest_index), start=1):
                start = datetime.combine(day, time(15, 0), tzinfo=tz)
                end = datetime.combine(day + timedelta(days=3), time(11, 0), tzinfo=tz)  # three nights
                for travelers in PARTY_SIZES:
                    rooms = ceil(travelers / 2)
                    price = NIGHT_BASE[destination] * SUPPLIER_FACTOR[supplier] * 3 * rooms * season_factor(day)
                    add(
                        f"{dest_slug}-accommodation-{supplier}-s{number}-p{travelers}",
                        supplier, "accommodation",
                        f"3-night stay in {destination} ({SUPPLIER_NAMES[supplier]})",
                        f"Three nights in {rooms} room(s) in {destination} for {travelers} traveler(s), total price.",
                        destination, None, start, end, travelers, price,
                    )

        activities = ACTIVITIES[destination] + EXTRA_ACTIVITIES[destination]
        for position, supplier in enumerate(SUPPLIERS["activity"]):
            for activity_number, (title, per_person, hour) in enumerate(activities, start=1):
                for number, day in enumerate(days(7, activity_number + position * 3 + dest_index), start=1):
                    start = datetime.combine(day, time(hour, 0), tzinfo=tz)
                    end = start + timedelta(hours=3)
                    for travelers in PARTY_SIZES:
                        price = per_person * SUPPLIER_FACTOR[supplier] * travelers * season_factor(day)
                        add(
                            f"{dest_slug}-activity-{supplier}-{activity_number}-s{number}-p{travelers}",
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
        session.execute(insert(Offer), build_offers(get_clock().now()))
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
        session.execute(insert(Offer), rows)
        session.commit()
        return len(rows)
