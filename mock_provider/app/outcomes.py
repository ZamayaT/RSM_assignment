"""Outcome the provider gives to the next accepted bookings (set through the control interface).

In memory, like the supplier failure modes. With nothing queued, new bookings are confirmed.
"""
from collections import deque

CONFIRMED = "confirmed"
FAILED = "failed"
PENDING = "pending"
OUTCOMES = (CONFIRMED, FAILED, PENDING)

FAILURE_CODE = "BOOKING_REJECTED"
FAILURE_MESSAGE = "The supplier rejected the booking request."

_queue: deque[str] = deque()


def enqueue(outcome: str, count: int = 1) -> None:
    if outcome not in OUTCOMES:
        raise ValueError(f"unknown outcome: {outcome}")
    _queue.extend([outcome] * count)


def clear() -> None:
    _queue.clear()


def queued() -> list[str]:
    return list(_queue)


def next_outcome() -> str:
    return _queue.popleft() if _queue else CONFIRMED
