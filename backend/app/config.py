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

    # Provider (mock) reached over HTTP.
    provider_base_url: str = "http://mock_provider:4010/v1"
    provider_token: str = "travel-demo-token"
    provider_timeout_seconds: float = 5

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
