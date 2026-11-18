"""Bookings: attempts for itinerary items, the booking endpoint and the bookings list.

An attempt is saved as `initiated` and committed BEFORE the provider is called, so a crash or a lost response
can always be reconciled by reference. Only a definite provider answer makes an attempt `failed`; anything
that leaves doubt is `unknown`.
"""
import logging
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app import provider_client as provider
from app.auth import CurrentUser
from app.config import get_settings
from app.errors import ApiError
from app.models import (
    BOOKING_CONFIRMED,
    BOOKING_FAILED,
    BOOKING_INITIATED,
    BOOKING_LIVE_STATUSES,
    BOOKING_PENDING,
    BOOKING_UNKNOWN,
    BookingAttempt,
    ItineraryItem,
)
from app.trips import SessionDep, can_edit, can_read, get_trip_for_user, require

logger = logging.getLogger("app.bookings")

router = APIRouter(tags=["bookings"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---- Queries shared with the itinerary and the budget ----


def latest_attempts(session, trip_id: uuid.UUID) -> dict[uuid.UUID, BookingAttempt]:
    """The most recent attempt of each item (the one that decides the item's booking status)."""
    latest: dict[uuid.UUID, BookingAttempt] = {}
    for attempt in session.scalars(
        select(BookingAttempt).where(BookingAttempt.trip_id == trip_id).order_by(BookingAttempt.created_at)
    ):
        latest[attempt.item_id] = attempt
    return latest


def live_attempt(session, item_id: uuid.UUID) -> BookingAttempt | None:
    return session.scalars(
        select(BookingAttempt).where(BookingAttempt.item_id == item_id, BookingAttempt.status.in_(BOOKING_LIVE_STATUSES))
    ).first()


def lock_item(session, trip_id: uuid.UUID, item_id: uuid.UUID) -> ItineraryItem | None:
    """The item row, locked until commit/rollback: removals, refreshes and bookings of one item queue up."""
    return session.scalars(
        select(ItineraryItem)
        .where(ItineraryItem.id == item_id, ItineraryItem.trip_id == trip_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).first()


# ---- Recording provider outcomes (shared by the booking request and the checks) ----


def poll_delay(attempt: BookingAttempt, now: datetime) -> timedelta:
    """How long to wait before reading a pending booking again: often at first, then once a minute."""
    settings = get_settings()
    young = now - attempt.created_at < timedelta(seconds=settings.booking_poll_fast_window_seconds)
    return timedelta(seconds=settings.booking_poll_fast_seconds if young else settings.booking_poll_slow_seconds)


def apply_booking(attempt: BookingAttempt, booking: provider.ProviderBooking) -> None:
    """Store the provider's current state. Terminal outcomes never reverse; the accepted snapshot never changes."""
    if attempt.status in (BOOKING_CONFIRMED, BOOKING_FAILED):
        return
    now = _now()
    attempt.status = booking.status
    attempt.provider_booking_id = booking.id
    if attempt.accepted_offer is None:
        attempt.accepted_offer = booking.offer.model_dump(mode="json")
        attempt.accepted_amount = Decimal(booking.offer.price.amount)
    attempt.failure_code = booking.failure.code if booking.failure else None
    attempt.failure_message = booking.failure.message if booking.failure else None
    attempt.unresolved = False
    attempt.updated_at = now
    attempt.next_check_at = now + poll_delay(attempt, now) if booking.status == BOOKING_PENDING else None


def mark_failed(attempt: BookingAttempt, code: str, message: str) -> None:
    """Definitely not booked (the provider refused). Never used for doubtful outcomes."""
    if attempt.status in (BOOKING_CONFIRMED, BOOKING_FAILED):
        return
    attempt.status = BOOKING_FAILED
    attempt.failure_code = code
    attempt.failure_message = message
    attempt.unresolved = False
    attempt.next_check_at = None
    attempt.updated_at = _now()


def mark_unknown(attempt: BookingAttempt) -> None:
    """We cannot prove whether the provider booked; the worker reconciles by reference."""
    if attempt.status != BOOKING_INITIATED:
        return
    now = _now()
    attempt.status = BOOKING_UNKNOWN
    attempt.next_check_at = now + timedelta(seconds=get_settings().booking_first_check_seconds)
    attempt.updated_at = now


REFUSALS = {
    provider.ProviderOfferChanged: (
        "OFFER_CHANGED",
        "The price or terms changed (or the quote expired) before the booking. Nothing was booked.",
    ),
    provider.ProviderOfferUnavailable: ("OFFER_UNAVAILABLE", "The offer is no longer available. Nothing was booked."),
    provider.ProviderBadRequest: ("BAD_REQUEST", "The provider rejected the booking request. Nothing was booked."),
}


def apply_refusal(attempt: BookingAttempt, exc: provider.ProviderError) -> bool:
    """Mark the attempt failed when the provider definitely refused it. Returns False when in doubt."""
    for error_class, (code, message) in REFUSALS.items():
        if isinstance(exc, error_class):
            mark_failed(attempt, code, message)
            return True
    return False


# ---- Output ----


class Price(BaseModel):
    amount: str
    currency: str


class FailureOut(BaseModel):
    code: str
    message: str


class AttemptOut(BaseModel):
    id: str
    itemId: str
    itemTitle: str
    status: str
    offerId: str
    requestedPrice: Price
    acceptedPrice: Price | None
    providerBookingId: str | None
    failure: FailureOut | None
    unresolved: bool
    takingLonger: bool
    createdAt: datetime
    updatedAt: datetime


def attempt_out(attempt: BookingAttempt, item_title: str) -> AttemptOut:
    slow = (
        attempt.status == BOOKING_PENDING
        and _now() - attempt.created_at > timedelta(seconds=get_settings().booking_slow_after_seconds)
    )
    return AttemptOut(
        id=str(attempt.id),
        itemId=str(attempt.item_id),
        itemTitle=item_title,
        status=attempt.status,
        offerId=attempt.offer_id,
        requestedPrice=Price(amount=f"{attempt.expected_amount:.2f}", currency=attempt.currency),
        acceptedPrice=None
        if attempt.accepted_amount is None
        else Price(amount=f"{attempt.accepted_amount:.2f}", currency=attempt.currency),
        providerBookingId=attempt.provider_booking_id,
        failure=None
        if attempt.failure_code is None
        else FailureOut(code=attempt.failure_code, message=attempt.failure_message or ""),
        unresolved=attempt.unresolved and attempt.status == BOOKING_UNKNOWN,
        takingLonger=slow,
        createdAt=attempt.created_at,
        updatedAt=attempt.updated_at,
    )


def _titles(session, trip_id: uuid.UUID) -> dict[uuid.UUID, str]:
    return dict(session.execute(select(ItineraryItem.id, ItineraryItem.title).where(ItineraryItem.trip_id == trip_id)).all())


def _out(session, attempt: BookingAttempt) -> AttemptOut:
    title = session.scalar(select(ItineraryItem.title).where(ItineraryItem.id == attempt.item_id))
    return attempt_out(attempt, title or "")


class CountsOut(BaseModel):
    """Items by the status of their latest attempt."""

    pending: int
    confirmed: int
    failed: int
    unknown: int


class BookingsOut(BaseModel):
    attempts: list[AttemptOut]
    counts: CountsOut


@router.get("/trips/{trip_id}/bookings")
def list_bookings(trip_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> BookingsOut:
    _, role = get_trip_for_user(session, trip_id, user)
    require(can_read(role))
    titles = _titles(session, trip_id)
    attempts = list(
        session.scalars(
            select(BookingAttempt).where(BookingAttempt.trip_id == trip_id).order_by(BookingAttempt.created_at.desc())
        )
    )
    latest = latest_attempts(session, trip_id).values()

    def count(*statuses: str) -> int:
        return sum(1 for a in latest if a.status in statuses)

    return BookingsOut(
        attempts=[attempt_out(a, titles.get(a.item_id, "")) for a in attempts],
        counts=CountsOut(
            pending=count(BOOKING_INITIATED, BOOKING_PENDING),
            confirmed=count(BOOKING_CONFIRMED),
            failed=count(BOOKING_FAILED),
            unknown=count(BOOKING_UNKNOWN),
        ),
    )


# ---- Booking ----


class MoneyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount: Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=2)]
    currency: Annotated[str, Field(min_length=3, max_length=3)]


class BookIn(BaseModel):
    """The terms the user was shown and confirmed; nothing else is ever booked."""

    model_config = ConfigDict(extra="forbid")

    itemId: uuid.UUID
    intentId: uuid.UUID
    expectedRevision: Annotated[str, Field(min_length=1, max_length=64)]
    expectedPrice: MoneyIn


def _exists(attempt: BookingAttempt, title: str) -> ApiError:
    return ApiError(
        409,
        "BOOKING_EXISTS",
        "This item already has a booking in progress or confirmed.",
        {"attempt": attempt_out(attempt, title).model_dump(mode="json")},
    )


@router.post("/trips/{trip_id}/bookings", status_code=201)
def create_booking(
    trip_id: uuid.UUID, body: BookIn, user: CurrentUser, session: SessionDep, request: Request, response: Response
) -> AttemptOut:
    _, role = get_trip_for_user(session, trip_id, user)
    require(can_edit(role), "You are not allowed to book on this trip.")

    item = lock_item(session, trip_id, body.itemId)
    if item is None:
        session.rollback()
        raise ApiError(404, "NOT_FOUND", "This item is not in the itinerary (it may have been removed).")

    # Same intent again (double click, retry, lost response): the same attempt, never a second booking.
    same_intent = session.scalars(select(BookingAttempt).where(BookingAttempt.intent_id == body.intentId)).first()
    if same_intent is not None:
        same_terms = (
            same_intent.item_id == item.id
            and same_intent.expected_revision == body.expectedRevision
            and same_intent.expected_amount == body.expectedPrice.amount
        )
        out = attempt_out(same_intent, item.title)
        session.rollback()
        if not same_terms:
            raise ApiError(409, "INTENT_CONFLICT", "This booking intent was already used with different terms.")
        response.status_code = 200
        return out

    existing = live_attempt(session, item.id)
    if existing is not None:
        error = _exists(existing, item.title)
        session.rollback()
        raise error

    reference = f"trip-{trip_id}-item-{item.id}-{uuid.uuid4().hex[:8]}"
    attempt = BookingAttempt(
        trip_id=trip_id,
        item_id=item.id,
        intent_id=body.intentId,
        client_reference=reference,
        idempotency_key=f"booking-intent-{body.intentId}",
        status=BOOKING_INITIATED,
        offer_id=item.offer_id,
        expected_revision=body.expectedRevision,
        expected_amount=body.expectedPrice.amount,
        currency=body.expectedPrice.currency,
        requested_by=user.id,
        next_check_at=_now() + timedelta(seconds=get_settings().booking_stale_initiated_seconds),
    )
    session.add(attempt)
    try:
        session.commit()  # saved before the provider is called
    except IntegrityError as exc:
        session.rollback()
        raise ApiError(409, "BOOKING_EXISTS", "This item already has a booking in progress or confirmed.") from exc

    price = provider.Money(amount=f"{body.expectedPrice.amount:.2f}", currency=body.expectedPrice.currency)
    try:
        created = provider.create_booking(
            attempt.client_reference, attempt.offer_id, attempt.expected_revision, price, attempt.idempotency_key
        )
    except provider.ProviderError as exc:
        # A definite refusal is data. Anything else could still have booked: unknown, never failed.
        if not apply_refusal(attempt, exc):
            logger.warning(
                "booking %s outcome unknown: %s request_id=%s", attempt.client_reference, type(exc).__name__, exc.request_id
            )
            mark_unknown(attempt)
    else:
        apply_booking(attempt, created.booking)
    session.commit()
    return attempt_out(attempt, item.title)


# ---- Check again ----


@router.post("/trips/{trip_id}/bookings/{attempt_id}/check")
def check_booking(trip_id: uuid.UUID, attempt_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> AttemptOut:
    """One immediate lookup of an attempt's real state; never a new booking."""
    from app.booking_steps import check_attempt  # local import: the steps use this module's helpers

    _, role = get_trip_for_user(session, trip_id, user)
    require(can_edit(role), "You are not allowed to check bookings on this trip.")
    attempt = session.scalars(
        select(BookingAttempt)
        .where(BookingAttempt.id == attempt_id, BookingAttempt.trip_id == trip_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).first()
    if attempt is None:
        session.rollback()
        raise ApiError(404, "NOT_FOUND", "Booking not found.")
    check_attempt(attempt)
    session.commit()
    return _out(session, attempt)
