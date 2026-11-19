"""The read-only tools: plain functions `(session, user, ...) -> JSON-safe dict`.

They reuse the same read code as the REST endpoints, so the assistant and the screens can never disagree, and they
import no write code. Access is checked here, per call: a trip id alone grants nothing, and a non-participant gets
the same "not found" as for a trip that does not exist.
"""
import uuid
from typing import Any

from pydantic import ValidationError

from app.bookings import build_bookings, latest_attempts
from app.budget import build_budget
from app.errors import ApiError
from app.itinerary import itinerary_out, list_items
from app.models import User
from app.search import SearchIn, run_search
from app.trips import _trip_out, can_read, get_trip_for_user, require


class ToolFailure(Exception):
    """A failure the model should see (shown as a failed tool call). Never carries internal details."""


def parse_trip_id(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except ValueError as exc:
        raise ToolFailure("trip_id must be a trip identifier (UUID); use the id of the current trip.") from exc


def authorized_trip(session, user: User, trip_id: str):
    """The trip, if the user participates in it (any role may read). Anyone else gets 'Trip not found.'"""
    try:
        trip, role = get_trip_for_user(session, parse_trip_id(trip_id), user)
        require(can_read(role))
    except ApiError as exc:
        raise ToolFailure(exc.message) from exc
    return trip, role


def get_trip(session, user: User, trip_id: str) -> dict[str, Any]:
    trip, role = authorized_trip(session, user, trip_id)
    return _trip_out(trip, role).model_dump(mode="json")


def get_itinerary(session, user: User, trip_id: str) -> dict[str, Any]:
    trip, _ = authorized_trip(session, user, trip_id)
    items = list_items(session, trip.id)
    return itinerary_out(trip, items, latest_attempts(session, trip.id)).model_dump(mode="json")


def get_budget(session, user: User, trip_id: str) -> dict[str, Any]:
    trip, _ = authorized_trip(session, user, trip_id)
    items = list_items(session, trip.id)
    return build_budget(trip, items, latest_attempts(session, trip.id)).model_dump(mode="json")


def get_bookings(session, user: User, trip_id: str) -> dict[str, Any]:
    trip, _ = authorized_trip(session, user, trip_id)
    return build_bookings(session, trip.id).model_dump(mode="json")


def search_options(
    session,
    user: User,
    trip_id: str,
    category: str,
    destination: str,
    origin: str | None = None,
    starts_on: str | None = None,
    ends_on: str | None = None,
    travelers: int | None = None,
    supplier: str | None = None,
    request_id: str = "-",
) -> dict[str, Any]:
    trip, _ = authorized_trip(session, user, trip_id)
    try:
        body = SearchIn(
            category=category,
            destination=destination,
            origin=origin,
            startsOn=starts_on,
            endsOn=ends_on,
            travelers=travelers,
            providerId=supplier,
        )
    except ValidationError as exc:
        problems = "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors())
        raise ToolFailure(f"Invalid search arguments ({problems}).") from exc
    try:
        return run_search(trip, body, request_id).model_dump(mode="json")
    except ApiError as exc:
        fields = (exc.details or {}).get("fields")
        detail = f" ({'; '.join(f'{k}: {v}' for k, v in fields.items())})" if fields else ""
        raise ToolFailure(f"{exc.message}{detail}") from exc


# name -> (function, what the model is told). Every entry reads; nothing here changes data.
TOOL_DESCRIPTIONS = {
    "get_trip": "Read the trip: name, dates, destinations, number of travelers, budget in USD, the organizer's notes and "
    "preferences, and the caller's role. Call this first to understand the traveler's needs.",
    "get_itinerary": "Read the itinerary in order: each item's schedule, price, status (estimate, expired quote, booking "
    "pending, confirmed, failed, unknown), warnings (conflicts, missing information) and the provider's restrictions.",
    "get_budget": "Read the budget in USD: estimated total (not booked), confirmed total (accepted booking prices), combined "
    "total, the trip budget, the amount remaining (negative when over budget), and each item's cost.",
    "get_bookings": "Read the booking attempts and the counts by outcome (pending, confirmed, failed, unknown). Unknown "
    "means the outcome is not settled yet; it is not a failure.",
    "search_options": "Search the provider's current offers for transport, accommodation or activities at one of the "
    "trip's destinations. Returns the offers with price (total for the whole party), schedule, availability, quote "
    "validity and restrictions, plus the state: complete, partial (some supplier failed: see warnings) or empty. "
    "Offers are estimates, not bookings.",
}
