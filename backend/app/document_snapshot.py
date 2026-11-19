"""The frozen snapshot a document is rendered from.

Taken once, when the document is requested, and stored as JSON. The PDF is rendered only from this data, so later
edits, price changes or booking changes never alter a document. Money stays in decimal strings.
"""
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select

from app.bookings import attempt_out, latest_attempts
from app.budget import build_budget
from app.itinerary import itinerary_out, list_items
from app.models import Trip, User

SNAPSHOT_SCHEMA = 1


@dataclass(frozen=True)
class Snapshot:
    trip_version: int
    taken_at: datetime
    data: dict  # JSON-safe; never changed after it is stored


def build_snapshot(session, trip_id: uuid.UUID, user: User) -> Snapshot:
    """Read the trip, itinerary, budget and bookings in the caller's transaction.

    The trip row is locked FOR SHARE until the caller commits: an edit bumps the trip version through that row,
    so it waits, and the saved version always matches the content read here.
    """
    trip = session.scalars(
        select(Trip).where(Trip.id == trip_id).with_for_update(read=True).execution_options(populate_existing=True)
    ).one()
    items = list_items(session, trip_id)
    attempts = latest_attempts(session, trip_id)
    taken_at = datetime.now(timezone.utc)

    itinerary = itinerary_out(trip, items, attempts)
    budget = build_budget(trip, items, attempts)
    titles = {i.id: i.title for i in items}
    # Latest attempt per item, in itinerary order.
    bookings = [attempt_out(attempts[i.id], titles[i.id]) for i in items if i.id in attempts]

    data = {
        "schema": SNAPSHOT_SCHEMA,
        "generatedAt": taken_at.isoformat(),
        "generatedBy": {"id": str(user.id), "displayName": user.display_name},
        "tripVersion": trip.version,
        "trip": {
            "id": str(trip.id),
            "name": trip.name,
            "destinations": list(trip.destinations),
            "startDate": trip.start_date.isoformat(),
            "endDate": trip.end_date.isoformat(),
            "travelers": trip.travelers,
            "budget": f"{trip.budget:.2f}",
            "notes": trip.notes,
        },
        "itinerary": [i.model_dump(mode="json") for i in itinerary.items],
        "budget": budget.model_dump(mode="json"),
        "bookings": [b.model_dump(mode="json") for b in bookings],
    }
    return Snapshot(trip.version, taken_at, data)
