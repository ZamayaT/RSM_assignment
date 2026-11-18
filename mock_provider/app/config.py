from datetime import datetime
from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL


class Settings(BaseSettings):
    """Mock provider configuration, read from environment variables."""

    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    postgres_db: str
    postgres_user: str
    postgres_password: str
    postgres_host: str
    postgres_port: int = 5432

    # The mock keeps all its tables in its own schema, apart from the backend's.
    mock_db_schema: str = "mock_provider"

    # Clock: real time by default. Set a frozen instant (ISO 8601 with offset, e.g. 2030-01-15T09:00:00Z)
    # or an offset in seconds from real time (negative allowed). A frozen instant wins over the offset.
    mock_clock_frozen_at: datetime | None = None
    mock_clock_offset_seconds: int = 0

    @field_validator("mock_clock_frozen_at", mode="before")
    @classmethod
    def _empty_means_unset(cls, value):
        return None if value == "" else value

    @field_validator("mock_clock_frozen_at")
    @classmethod
    def _require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("MOCK_CLOCK_FROZEN_AT must include a timezone offset, e.g. 2030-01-15T09:00:00Z")
        return value

    @property
    def database_url(self) -> URL:
        # URL.create escapes special characters in credentials.
        return URL.create(
            drivername="postgresql+psycopg",
            username=self.postgres_user,
            password=self.postgres_password,
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_db,
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
