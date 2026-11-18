import os
from pathlib import Path

# Dummy values so settings can load without a real environment (real ones win when present).
os.environ.setdefault("POSTGRES_DB", "test")
os.environ.setdefault("POSTGRES_USER", "test")
os.environ.setdefault("POSTGRES_PASSWORD", "test")
os.environ.setdefault("POSTGRES_HOST", "localhost")

# Tests that need a database use a separate one, so the development data is never touched.
ADMIN_DB = os.environ["POSTGRES_DB"]
TEST_DB = f"{ADMIN_DB}_test"
os.environ["POSTGRES_DB"] = TEST_DB

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db import get_engine  # noqa: E402
from app.main import app  # noqa: E402

BACKEND_DIR = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def database():
    """A fresh test database with all migrations applied."""
    admin_url = get_settings().database_url.set(database=ADMIN_DB)
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f'DROP DATABASE IF EXISTS "{TEST_DB}" WITH (FORCE)'))
        connection.execute(text(f'CREATE DATABASE "{TEST_DB}"'))
    admin.dispose()

    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    command.upgrade(config, "head")
    yield
    get_engine().dispose()


@pytest.fixture
def client(database):
    """API client with the startup seed applied and no trips or logins left over from other tests."""
    with get_engine().begin() as connection:
        connection.execute(text("TRUNCATE itinerary_items, trip_participants, trips, auth_tokens"))
    with TestClient(app) as test_client:
        yield test_client


def login(client: TestClient, username: str) -> dict[str, str]:
    """Log in and return the Authorization header."""
    response = client.post("/auth/login", json={"username": username})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['token']}"}


VALID_TRIP = {
    "name": "Summer in Lisbon",
    "destinations": ["Lisbon"],
    "startDate": "2026-07-01",
    "endDate": "2026-07-10",
    "travelers": 2,
    "budget": "1500.00",
    "notes": "Beaches",
}
