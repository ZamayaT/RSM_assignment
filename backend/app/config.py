from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL


class Settings(BaseSettings):
    """Application configuration, read from environment variables."""

    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    postgres_db: str
    postgres_user: str
    postgres_password: str
    postgres_host: str
    postgres_port: int = 5432

    # Browser origin allowed to call the API (CORS).
    frontend_origin: str = "http://localhost:5173"

    # Log level of the backend and the worker (DEBUG, INFO, WARNING, ERROR).
    log_level: str = "INFO"

    # Provider (mock) reached over HTTP.
    provider_base_url: str = "http://mock_provider:4010/v1"
    provider_token: str = "travel-demo-token"
    provider_timeout_seconds: float = 5

    # Booking follow-up timings (seconds). The worker settles unknown outcomes and follows pending bookings.
    booking_stale_initiated_seconds: int = 60  # an `initiated` attempt older than this is treated as unknown
    booking_first_check_seconds: int = 10  # first lookup of an unknown outcome; the base of its backoff
    booking_backoff_max_seconds: int = 60  # longest wait between lookups of an unknown outcome
    booking_unresolved_after_seconds: int = 600  # then the attempt is flagged "unresolved" (stays unknown)
    booking_poll_fast_seconds: int = 10  # pending bookings are read this often at first ...
    booking_poll_fast_window_seconds: int = 300  # ... for this long ...
    booking_poll_slow_seconds: int = 60  # ... and then this often
    booking_slow_after_seconds: int = 1800  # a pending booking older than this is "taking longer than expected"
    booking_worker_tick_seconds: float = 2  # how often the worker looks for due attempts

    # Documents (PDF trip summaries built by the worker).
    documents_dir: str = "/data/documents"  # shared volume mounted in `backend` and `worker`
    document_stuck_seconds: int = 120  # an `in_progress` document older than this goes back to `waiting`
    document_max_attempts: int = 3  # after this many attempts an interrupted document is marked `failed`

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
