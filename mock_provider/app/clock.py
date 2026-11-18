from datetime import datetime, timedelta, timezone
from functools import lru_cache

from app.config import get_settings


class Clock:
    """The mock's only source of time. Every time-dependent rule (quote expiry, fixture dates,
    booking timestamps) must call `now()` here instead of reading the system clock.

    Real time by default; shifted by `offset`; or fixed at `frozen_at` (which wins over the offset).
    """

    def __init__(self, frozen_at: datetime | None = None, offset: timedelta = timedelta(0)):
        self.frozen_at = frozen_at
        self.offset = offset

    def now(self) -> datetime:
        if self.frozen_at is not None:
            return self.frozen_at
        return datetime.now(timezone.utc) + self.offset


@lru_cache
def get_clock() -> Clock:
    settings = get_settings()
    return Clock(
        frozen_at=settings.mock_clock_frozen_at,
        offset=timedelta(seconds=settings.mock_clock_offset_seconds),
    )
