from fastapi import APIRouter, Depends, Header, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_caller
from app.bookings import create_booking, resolve_if_due, to_booking_schema
from app.clock import get_clock
from app.db import get_session
from app.failures import apply_latency
from app.errors import ApiError
from app.models import Booking, Offer
from app.schemas import BookingOut, CreateBookingRequest

router = APIRouter(tags=["Bookings"])


@router.post("/bookings", response_model=BookingOut, response_model_exclude_none=True, status_code=201)
def post_booking(
    body: CreateBookingRequest,
    response: Response,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=128),
    caller: str = Depends(get_caller),
    session: Session = Depends(get_session),
) -> BookingOut:
    # Slow-supplier simulation happens before any lock is taken.
    offer = session.get(Offer, body.offerId)
    if offer is not None:
        apply_latency([offer.provider_id])
    session.rollback()

    booking, created = create_booking(session, caller, idempotency_key, body, get_clock().now())
    if not created:
        response.status_code = 200
    return to_booking_schema(booking)


def _visible(session: Session, booking: Booking | None) -> BookingOut:
    """Current state of a booking that the caller may see; a missing one is a 404."""
    if booking is None:
        raise ApiError(404, "NOT_FOUND", "No visible record exists for the supplied identifier.")
    return to_booking_schema(resolve_if_due(session, booking, get_clock().now()))


@router.get("/bookings/by-reference/{clientReference}", response_model=BookingOut, response_model_exclude_none=True)
def get_booking_by_reference(
    clientReference: str, caller: str = Depends(get_caller), session: Session = Depends(get_session)
) -> BookingOut:
    booking = session.scalar(
        select(Booking).where(Booking.caller == caller, Booking.client_reference == clientReference)
    )
    return _visible(session, booking)


@router.get("/bookings/{bookingId}", response_model=BookingOut, response_model_exclude_none=True)
def get_booking(
    bookingId: str, caller: str = Depends(get_caller), session: Session = Depends(get_session)
) -> BookingOut:
    booking = session.get(Booking, bookingId)
    if booking is not None and booking.caller != caller:
        booking = None  # other callers' bookings are invisible
    return _visible(session, booking)
