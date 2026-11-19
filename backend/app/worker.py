"""Background worker: settles unknown booking outcomes, follows pending bookings and builds trip documents.

Run with `python -m app.worker`. Due attempts are claimed with FOR UPDATE SKIP LOCKED, so a restart or a
second worker never processes the same attempt at the same time, and everything it does is safe to repeat
(the provider deduplicates by idempotency key).
"""
import logging
import signal
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.booking_steps import check_attempt
from app.config import get_settings
from app.db import get_engine
from app.document_steps import run_documents_once
from app.models import BOOKING_INITIATED, BOOKING_PENDING, BOOKING_UNKNOWN, BookingAttempt

logger = logging.getLogger("app.worker")

MAX_PER_PASS = 50


def process_next_due(now: datetime | None = None) -> bool:
    """Claim one due attempt, run its step and commit. Returns False when nothing is due."""
    now = now or datetime.now(timezone.utc)
    with Session(get_engine(), expire_on_commit=False) as session:
        attempt = session.scalars(
            select(BookingAttempt)
            .where(
                BookingAttempt.status.in_((BOOKING_INITIATED, BOOKING_PENDING, BOOKING_UNKNOWN)),
                BookingAttempt.next_check_at <= now,
            )
            .order_by(BookingAttempt.next_check_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        ).first()
        if attempt is None:
            return False
        check_attempt(attempt)
        if attempt.next_check_at is not None and attempt.next_check_at <= now:
            # The step left it due (nothing to do yet): look again later instead of spinning.
            attempt.next_check_at = now + timedelta(seconds=max(get_settings().booking_worker_tick_seconds, 1))
        session.commit()
        return True


def run_once(now: datetime | None = None) -> int:
    """Process every attempt that is due now (bounded). Returns how many were processed."""
    done = 0
    while done < MAX_PER_PASS and process_next_due(now):
        done += 1
    return done


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    stopping = False

    def stop(*_):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    logger.info("worker started (bookings and documents)")
    while not stopping:
        try:
            run_once()
        except Exception:  # database not ready yet, provider trouble, ...: log and keep going
            logger.exception("booking pass failed")
        try:
            run_documents_once()
        except Exception:  # a failing document pass must not stop the bookings, and the other way round
            logger.exception("document pass failed")
        time.sleep(get_settings().booking_worker_tick_seconds)
    logger.info("worker stopped (bookings and documents)")


if __name__ == "__main__":
    main()
