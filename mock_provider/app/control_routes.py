"""Control interface: outside the public contract (not under /v1, no token). Used to reproduce scenarios.

The application must never depend on these endpoints.
"""
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.orm import Session

from app import failures, outcomes
from app.bookings import to_booking_schema
from app.clock import get_clock
from app.db import get_session
from app.errors import ApiError
from app.fixtures import ALL_SUPPLIERS, reseed
from app.models import Booking, Offer
from app.offers import next_revision, to_schema
from app.schemas import BookingOut, OfferOut

router = APIRouter(prefix="/control", tags=["Control (outside the contract)"])

AMOUNT = r"^(0|[1-9][0-9]*)\.[0-9]{2}$"


def _clock_state() -> dict:
    clock = get_clock()
    return {
        "now": clock.now().isoformat(),
        "frozen": clock.frozen_at is not None,
        "offsetSeconds": clock.offset.total_seconds(),
    }


def _check_supplier(provider_id: str) -> None:
    if provider_id not in ALL_SUPPLIERS:
        raise ApiError(404, "NOT_FOUND", f"Unknown supplier: {provider_id}.")


@router.get("/state")
def state() -> dict:
    """Clock, supplier failure modes, artificial latency, and queued booking outcomes."""
    return {
        "clock": _clock_state(),
        "supplierFailures": {
            provider: {"mode": f.mode, "retryAfterSeconds": f.retry_after} for provider, f in failures.failures().items()
        },
        "supplierLatencyMs": failures.latencies(),
        "nextBookingOutcomes": outcomes.queued(),
    }


@router.post("/reset")
def reset() -> dict:
    """Delete bookings, references and idempotency records; reload fixtures; clear every control setting
    (clock back to its configured value, failure modes, latency, queued outcomes)."""
    get_clock().reset()
    failures.clear_all()
    outcomes.clear()
    return {"offersLoaded": reseed(), "clock": _clock_state()}


# ---- clock -------------------------------------------------------------------------------------------

class ClockRequest(BaseModel):
    """Send exactly one field."""

    model_config = ConfigDict(extra="forbid")

    freeze: Literal[True] | None = Field(default=None, description="Freeze at the current instant.")
    frozenAt: datetime | None = Field(default=None, description="Freeze at this instant (needs a timezone).")
    offsetSeconds: int | None = Field(default=None, description="Follow real time shifted by this many seconds.")
    advanceSeconds: int | None = Field(default=None, description="Move the clock forward (negative: back).")
    realTime: Literal[True] | None = Field(default=None, description="Follow real time again, no offset.")

    @model_validator(mode="after")
    def _exactly_one(self):
        if sum(value is not None for value in self.model_dump().values()) != 1:
            raise ValueError("send exactly one of freeze, frozenAt, offsetSeconds, advanceSeconds, realTime")
        if self.frozenAt is not None and self.frozenAt.tzinfo is None:
            raise ValueError("frozenAt must include a timezone offset")
        return self


@router.post("/clock")
def set_clock(body: ClockRequest) -> dict:
    clock = get_clock()
    if body.freeze:
        clock.freeze()
    elif body.frozenAt is not None:
        clock.freeze_at(body.frozenAt)
    elif body.offsetSeconds is not None:
        clock.set_offset(timedelta(seconds=body.offsetSeconds))
    elif body.advanceSeconds is not None:
        clock.advance(timedelta(seconds=body.advanceSeconds))
    else:
        clock.real_time()
    return _clock_state()


# ---- suppliers ---------------------------------------------------------------------------------------

class FailureRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["unavailable", "timeout", "rate_limited"]
    retryAfterSeconds: Annotated[int, Field(ge=1, le=3600)] = failures.DEFAULT_RETRY_AFTER


@router.put("/suppliers/{providerId}/failure", status_code=204)
def set_supplier_failure(providerId: str, body: FailureRequest) -> Response:
    """Make a supplier fail (search warnings or errors, 503/429 on its offers and bookings)."""
    _check_supplier(providerId)
    failures.set_failure(providerId, body.mode, body.retryAfterSeconds)
    return Response(status_code=204)


@router.delete("/suppliers/{providerId}/failure", status_code=204)
def clear_supplier_failure(providerId: str) -> Response:
    _check_supplier(providerId)
    failures.clear_failure(providerId)
    return Response(status_code=204)


class LatencyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    milliseconds: Annotated[int, Field(ge=0, le=failures.MAX_LATENCY_MS)]


@router.put("/suppliers/{providerId}/latency", status_code=204)
def set_supplier_latency(providerId: str, body: LatencyRequest) -> Response:
    """Delay every request that involves this supplier. 0 removes the delay."""
    _check_supplier(providerId)
    failures.set_latency(providerId, body.milliseconds)
    return Response(status_code=204)


# ---- offers ------------------------------------------------------------------------------------------

class OfferChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    price: str | None = Field(default=None, pattern=AMOUNT, description='New total price, e.g. "199.90".')
    available: bool | None = None

    @model_validator(mode="after")
    def _something(self):
        if self.price is None and self.available is None:
            raise ValueError("send price and/or available")
        return self


@router.post("/offers/{offerId}", response_model=OfferOut, response_model_exclude_none=True)
def change_offer(offerId: str, body: OfferChange, session: Session = Depends(get_session)) -> OfferOut:
    """Change an offer's price and/or availability. A real change creates a new revision."""
    offer = session.get(Offer, offerId, with_for_update=True)
    if offer is None:
        raise ApiError(404, "NOT_FOUND", "No visible record exists for the supplied identifier.")
    changed = False
    if body.price is not None and Decimal(body.price) != offer.price_amount:
        offer.price_amount, changed = Decimal(body.price), True
    if body.available is not None and body.available != offer.available:
        offer.available, changed = body.available, True
    if changed:
        offer.revision = next_revision(offer.revision)
        offer.updated_at = get_clock().now()
    session.commit()
    return to_schema(offer)


# ---- bookings ----------------------------------------------------------------------------------------

class OutcomeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome: Literal["confirmed", "failed", "pending"]
    count: Annotated[int, Field(ge=1, le=1000)] = 1


@router.put("/booking-outcomes", status_code=204)
def queue_booking_outcome(body: OutcomeRequest) -> Response:
    """Add `count` entries to the queue deciding how the next accepted bookings end. An empty queue means
    `confirmed`."""
    outcomes.enqueue(body.outcome, body.count)
    return Response(status_code=204)


@router.delete("/booking-outcomes", status_code=204)
def clear_booking_outcomes() -> Response:
    outcomes.clear()
    return Response(status_code=204)


class ResolveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome: Literal["confirmed", "failed"]


@router.post("/bookings/{bookingId}/resolve", response_model=BookingOut, response_model_exclude_none=True)
def resolve_booking(bookingId: str, body: ResolveRequest, session: Session = Depends(get_session)) -> BookingOut:
    """Force a pending booking to a terminal outcome. Terminal bookings never change."""
    booking = session.get(Booking, bookingId, with_for_update=True)
    if booking is None:
        raise ApiError(404, "NOT_FOUND", "No visible record exists for the supplied identifier.")
    if booking.status != outcomes.PENDING:
        raise ApiError(409, "CONFLICT", f"The booking is already {booking.status}; terminal outcomes never change.")
    booking.status = body.outcome
    booking.updated_at = max(get_clock().now(), booking.created_at)
    if body.outcome == outcomes.FAILED:
        booking.failure_code, booking.failure_message = outcomes.FAILURE_CODE, outcomes.FAILURE_MESSAGE
    session.commit()
    return to_booking_schema(booking)
