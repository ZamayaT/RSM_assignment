from datetime import datetime, timedelta, timezone
from functools import lru_cache

from app.config import get_settings


class Clock:
    """The mock's only source of time. Every time-dependent rule (quote expiry, fixture dates,
    booking timestamps) must call `now()` here instead of reading the system clock.

    Real time by default; shifted by `offset`; or fixed at `frozen_at` (which wins over the offset).
    """

    def __init__(self, frozen_at: datetime | None = None, offset: timedelta = timedelta(0)):
        self._initial = (frozen_at, offset)
        self.frozen_at = frozen_at
        self.offset = offset

    # Runtime changes (used by the control interface); they last until `reset` or a restart.
    def freeze(self) -> None:
        self.frozen_at = self.now()

    def freeze_at(self, instant: datetime) -> None:
        self.frozen_at = instant

    def set_offset(self, offset: timedelta) -> None:
        self.frozen_at = None
        self.offset = offset

    def advance(self, delta: timedelta) -> None:
        if self.frozen_at is not None:
            self.frozen_at += delta
        else:
            self.offset += delta

    def real_time(self) -> None:
        self.frozen_at, self.offset = None, timedelta(0)

    def reset(self) -> None:
        """Back to the configured (environment) clock."""
        self.frozen_at, self.offset = self._initial

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
