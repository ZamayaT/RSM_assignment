from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.clock import Clock
from app.config import Settings

BASE = {"postgres_db": "d", "postgres_user": "u", "postgres_password": "p", "postgres_host": "h"}


def test_real_time_by_default():
    assert abs(Clock().now() - datetime.now(timezone.utc)) < timedelta(seconds=1)


def test_offset_shifts_real_time():
    shifted = Clock(offset=timedelta(days=2)).now()
    assert abs(shifted - (datetime.now(timezone.utc) + timedelta(days=2))) < timedelta(seconds=1)


def test_frozen_clock_does_not_move_and_wins_over_offset():
    frozen = datetime(2030, 1, 15, 9, 0, tzinfo=timezone.utc)
    clock = Clock(frozen_at=frozen, offset=timedelta(days=5))
    assert clock.now() == frozen
    assert clock.now() == frozen


def test_settings_parse_clock_values():
    settings = Settings(**BASE, mock_clock_frozen_at="2030-01-15T09:00:00Z", mock_clock_offset_seconds=60)
    assert settings.mock_clock_frozen_at == datetime(2030, 1, 15, 9, 0, tzinfo=timezone.utc)
    assert settings.mock_clock_offset_seconds == 60


def test_settings_empty_frozen_value_means_real_time():
    assert Settings(**BASE, mock_clock_frozen_at="").mock_clock_frozen_at is None


def test_settings_reject_frozen_instant_without_timezone():
    with pytest.raises(ValidationError):
        Settings(**BASE, mock_clock_frozen_at="2030-01-15T09:00:00")
