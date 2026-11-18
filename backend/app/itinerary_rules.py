"""Itinerary status and warnings: pure functions, computed on every read and never stored.

Simplified rules (see PROJECT.md): times are compared as UTC instants; travel time, opening hours and
local-day logic are not modeled.
"""
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal

STATUS_ESTIMATE = "estimate"
STATUS_EXPIRED = "expired_quote"

SCHEDULE_CONFLICT = "SCHEDULE_CONFLICT"
MISSING_SCHEDULE = "MISSING_SCHEDULE"
MISSING_PRICE = "MISSING_PRICE"
EXPIRED_QUOTE = "EXPIRED_QUOTE"
OUTSIDE_TRIP_DATES = "OUTSIDE_TRIP_DATES"
DESTINATION_NOT_IN_TRIP = "DESTINATION_NOT_IN_TRIP"


@dataclass(frozen=True)
class ItemFacts:
    """What the rules need to know about one itinerary item."""

    id: uuid.UUID | str
    title: str
    category: str
    destination: str
    starts_at: datetime | None
    ends_at: datetime | None
    price_amount: Decimal | None
    valid_until: datetime | None


@dataclass(frozen=True)
class TripFacts:
    start_date: date
    end_date: date
    destinations: tuple[str, ...]


@dataclass(frozen=True)
class Warning:
    code: str
    message: str


@dataclass
class Evaluation:
    status: str = STATUS_ESTIMATE
    warnings: list[Warning] = field(default_factory=list)


def _utc(value: datetime) -> datetime:
    return value.astimezone(timezone.utc)


def _has_schedule(item: ItemFacts) -> bool:
    return item.starts_at is not None and item.ends_at is not None


def conflicts(a: ItemFacts, b: ItemFacts) -> bool:
    """Time ranges overlap (end equal to start is allowed). Accommodation may overlap anything but accommodation."""
    if not (_has_schedule(a) and _has_schedule(b)):
        return False
    if (a.category == "accommodation") != (b.category == "accommodation"):
        return False
    return _utc(a.starts_at) < _utc(b.ends_at) and _utc(b.starts_at) < _utc(a.ends_at)


def is_expired(item: ItemFacts, now: datetime) -> bool:
    return item.valid_until is not None and _utc(item.valid_until) < _utc(now)


def evaluate(items: list[ItemFacts], trip: TripFacts, now: datetime) -> dict[uuid.UUID | str, Evaluation]:
    """Status and warnings for each item, keyed by item id."""
    result: dict[uuid.UUID | str, Evaluation] = {}
    for item in items:
        ev = Evaluation()
        if is_expired(item, now):
            ev.status = STATUS_EXPIRED
            ev.warnings.append(Warning(EXPIRED_QUOTE, "The quoted price has expired; it may have changed."))
        if not _has_schedule(item):
            ev.warnings.append(Warning(MISSING_SCHEDULE, "This item has no complete schedule."))
        else:
            first, last = _utc(item.starts_at).date(), _utc(item.ends_at).date()
            if first < trip.start_date or last > trip.end_date:
                ev.warnings.append(Warning(OUTSIDE_TRIP_DATES, "This item falls outside the trip dates."))
        if item.price_amount is None:
            ev.warnings.append(Warning(MISSING_PRICE, "This item has no price."))
        if item.destination not in trip.destinations:
            ev.warnings.append(Warning(DESTINATION_NOT_IN_TRIP, "The destination is not one of the trip's destinations."))
        for other in items:
            if other is not item and conflicts(item, other):
                ev.warnings.append(Warning(SCHEDULE_CONFLICT, f"Overlaps with “{other.title}”."))
        result[item.id] = ev
    return result
