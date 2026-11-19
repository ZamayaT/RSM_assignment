"""One lookup step for a booking attempt: ask the provider what really happened, never book blindly.

`check_attempt` is the single step shared by the worker and "check again". It changes only the attempt (the
caller commits) and schedules the next look in `next_check_at`.
"""
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app import provider_client as provider
from app.bookings import apply_booking, apply_refusal, mark_unknown, poll_delay
from app.config import get_settings
from app.models import BOOKING_INITIATED, BOOKING_PENDING, BOOKING_UNKNOWN, BookingAttempt

logger = logging.getLogger("app.bookings")


def replay(attempt: BookingAttempt) -> provider.ProviderBooking | None:
    """No record by reference: send the same booking again with the same key and body (safe: the provider
    deduplicates, and a changed offer is refused). Returns the booking, or None when the provider refused
    (the attempt is then marked failed). Other provider errors propagate."""
    price = provider.Money(amount=f"{Decimal(attempt.expected_amount):.2f}", currency=attempt.currency)
    try:
        return provider.create_booking(
            attempt.client_reference, attempt.offer_id, attempt.expected_revision, price, attempt.idempotency_key
        ).booking
    except provider.ProviderError as exc:
        if apply_refusal(attempt, exc):
            return None
        raise


def reconcile(attempt: BookingAttempt) -> None:
    """Unknown outcome: look it up by reference; if the provider has no record, replay the booking."""
    try:
        booking = provider.get_booking_by_reference(attempt.client_reference)
    except provider.ProviderNotFound:
        booking = replay(attempt)
        if booking is None:
            return
    apply_booking(attempt, booking)


def poll(attempt: BookingAttempt) -> None:
    """Pending booking: read its current state."""
    if attempt.provider_booking_id:
        booking = provider.get_booking(attempt.provider_booking_id)
    else:
        booking = provider.get_booking_by_reference(attempt.client_reference)
    apply_booking(attempt, booking)


def backoff(attempt: BookingAttempt) -> timedelta:
    """Growing wait between lookups of an unknown outcome: base, doubling, up to the maximum."""
    settings = get_settings()
    seconds = settings.booking_first_check_seconds * 2 ** max(attempt.check_count - 1, 0)
    return timedelta(seconds=min(seconds, settings.booking_backoff_max_seconds))


def _inconclusive(attempt: BookingAttempt, now: datetime) -> None:
    """The provider could not tell us. Pending: try again later. Unknown: back off, then flag unresolved."""
    if attempt.status == BOOKING_PENDING:
        attempt.next_check_at = now + poll_delay(attempt, now)
    elif attempt.status == BOOKING_UNKNOWN:
        if now - attempt.created_at >= timedelta(seconds=get_settings().booking_unresolved_after_seconds):
            attempt.unresolved = True  # the status stays unknown; only "check again" tries from here on
            attempt.next_check_at = None
        else:
            attempt.next_check_at = now + backoff(attempt)
    attempt.updated_at = now


def check_attempt(attempt: BookingAttempt) -> None:
    """Run one step for the attempt's current status. Provider trouble never changes the status."""
    now = datetime.now(timezone.utc)
    if attempt.status == BOOKING_INITIATED:
        if now - attempt.created_at < timedelta(seconds=get_settings().booking_stale_initiated_seconds):
            return  # the request that created it is probably still talking to the provider
        mark_unknown(attempt)  # the process that saved it never recorded an answer
    if attempt.status not in (BOOKING_UNKNOWN, BOOKING_PENDING):
        return
    attempt.last_checked_at = now
    attempt.check_count += 1
    try:
        if attempt.status == BOOKING_UNKNOWN:
            reconcile(attempt)
        else:
            poll(attempt)
    except provider.ProviderError as exc:
        logger.warning("check of %s inconclusive: %s", attempt.client_reference, type(exc).__name__)
        _inconclusive(attempt, now)
