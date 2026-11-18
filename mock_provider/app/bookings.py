"""Booking creation: idempotency, reference uniqueness, atomic offer checks, snapshots."""
import hashlib
import json
import uuid
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app import outcomes
from app.config import get_settings
from app.errors import ApiError
from app.failures import failure_error, get_failure
from app.models import Booking, IdempotencyRecord, Offer
from app.offers import to_schema
from app.schemas import BookingFailure, BookingOut, CreateBookingRequest, OfferOut


def fingerprint(body: CreateBookingRequest) -> str:
    """Hash of the semantic request body; property order and whitespace do not matter."""
    canonical = json.dumps(body.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def to_booking_schema(booking: Booking) -> BookingOut:
    failure = None
    if booking.status == outcomes.FAILED:
        failure = BookingFailure(code=booking.failure_code, message=booking.failure_message)
    return BookingOut(
        id=booking.id,
        clientReference=booking.client_reference,
        offer=OfferOut.model_validate(booking.offer_snapshot),
        status=booking.status,
        createdAt=booking.created_at,
        updatedAt=booking.updated_at,
        failure=failure,
    )


def resolve_if_due(session: Session, booking: Booking, now: datetime) -> Booking:
    """Lazily move a pending booking to confirmed once the mock clock says its delay has passed.

    Terminal bookings are returned untouched. The row is locked and re-checked so a concurrent reader or the
    control interface cannot make the outcome change twice.
    """
    delay = timedelta(seconds=get_settings().mock_pending_resolution_seconds)
    if booking.status != outcomes.PENDING or now - booking.created_at < delay:
        return booking
    locked = session.get(Booking, booking.id, with_for_update=True, populate_existing=True)
    if locked.status == outcomes.PENDING:
        locked.status = outcomes.CONFIRMED
        locked.updated_at = max(now, locked.created_at)
    session.commit()
    return locked


def _lock(session: Session, name: str) -> None:
    """Transaction-scoped advisory lock: requests with the same name run one at a time."""
    session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:name, 0))"), {"name": name})


def create_booking(
    session: Session, caller: str, idempotency_key: str, body: CreateBookingRequest, now: datetime
) -> tuple[Booking, bool]:
    """Return (booking, created). `created` is False for an idempotent replay."""
    request_hash = fingerprint(body)

    # Serialize on the key and on the reference (always in this order, so locks cannot deadlock):
    # concurrent identical requests then create exactly one booking and the rest replay it.
    _lock(session, f"key:{caller}:{idempotency_key}")
    _lock(session, f"ref:{caller}:{body.clientReference}")

    # 1. An existing idempotency key is resolved before looking at the offer at all.
    record = session.scalar(
        select(IdempotencyRecord).where(
            IdempotencyRecord.caller == caller, IdempotencyRecord.idempotency_key == idempotency_key
        )
    )
    if record is not None:
        if record.request_fingerprint != request_hash:
            raise ApiError(409, "IDEMPOTENCY_CONFLICT", "This key was already used with a different request body.")
        return resolve_if_due(session, session.get(Booking, record.booking_id), now), False

    # 2. A new key may not reuse a reference that already belongs to an accepted request.
    if session.scalar(
        select(Booking.id).where(Booking.caller == caller, Booking.client_reference == body.clientReference)
    ):
        raise ApiError(409, "REFERENCE_CONFLICT", "This client reference belongs to an existing booking request.")

    # 3. Lock the offer and check its current terms atomically.
    offer = session.get(Offer, body.offerId, with_for_update=True, populate_existing=True)
    if offer is None:
        raise ApiError(404, "NOT_FOUND", "No visible record exists for the supplied identifier.")
    failure = get_failure(offer.provider_id)
    if failure is not None:
        raise failure_error(failure)

    # Unavailable is reported before a changed quote: a sold-out offer also has a new revision, and
    # "no longer available" is the more useful answer for the caller.
    if not offer.available:
        raise ApiError(409, "OFFER_UNAVAILABLE", "The offer is no longer available.")
    price_matches = (
        body.expectedPrice.currency == offer.currency
        and Decimal(body.expectedPrice.amount) == offer.price_amount
    )
    if body.expectedOfferRevision != offer.revision or not price_matches or offer.valid_until <= now:
        raise ApiError(
            409, "OFFER_CHANGED", "Price, quote revision, or quote validity changed; review the latest offer."
        )

    # 4. Accept: the snapshot and total are frozen here and never change afterwards.
    outcome = outcomes.next_outcome()
    booking = Booking(
        id=f"booking-{uuid.uuid4().hex}",
        caller=caller,
        client_reference=body.clientReference,
        offer_id=offer.id,
        offer_snapshot=to_schema(offer).model_dump(mode="json", exclude_none=True),
        price_amount=offer.price_amount,
        currency=offer.currency,
        status=outcome,
        failure_code=outcomes.FAILURE_CODE if outcome == outcomes.FAILED else None,
        failure_message=outcomes.FAILURE_MESSAGE if outcome == outcomes.FAILED else None,
        created_at=now,
        updated_at=now,
    )
    session.add(booking)
    session.flush()
    session.add(
        IdempotencyRecord(
            caller=caller, idempotency_key=idempotency_key, request_fingerprint=request_hash, booking_id=booking.id
        )
    )
    session.commit()
    return booking, True
