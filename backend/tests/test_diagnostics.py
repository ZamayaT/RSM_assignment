"""Diagnostics: the request id in every log line, one access line per request, and a standard 500."""
import logging

import pytest
from fastapi import APIRouter

from app import logging_setup
from app.config import get_settings
from app.main import app
from tests.itinerary_helpers import TRIP, make_trip, mock, offers  # noqa: F401


class Capture(logging.Handler):
    """Collects the application's log records together with the request id the log filter gives them."""

    def __init__(self):
        super().__init__(logging.DEBUG)
        self.addFilter(logging_setup.RequestIdFilter())
        self.records: list[logging.LogRecord] = []

    def emit(self, record):
        self.records.append(record)


@pytest.fixture
def logs():
    handler = Capture()
    root = logging.getLogger()
    previous = root.level
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    yield handler
    root.removeHandler(handler)
    root.setLevel(previous)


def of_request(logs, request_id):
    return [r for r in logs.records if r.name.startswith("app") and r.request_id == request_id]


def test_every_log_line_of_a_request_carries_its_request_id_and_links_the_provider_call(client, logs):
    headers, trip_id = make_trip(client)
    logs.records.clear()

    response = client.post(
        f"/trips/{trip_id}/search", json={"category": "accommodation", "destination": "Lisbon"}, headers=headers
    )

    request_id = response.headers["X-Request-Id"]
    app_lines = [r for r in logs.records if r.name.startswith("app")]
    assert app_lines and all(r.request_id == request_id for r in app_lines)
    names = {r.name for r in of_request(logs, request_id)}
    assert {"app.request", "app.provider"} <= names  # the access line and the provider call share the id
    provider_line = next(r for r in of_request(logs, request_id) if r.name == "app.provider")
    assert "status=200" in provider_line.getMessage() and "request_id=" in provider_line.getMessage()  # provider's own id


def test_the_access_line_has_method_path_status_duration_and_user_and_health_checks_are_quiet(client, logs):
    headers, trip_id = make_trip(client)
    user_id = client.get("/auth/users").json()[0]["id"]
    logs.records.clear()

    client.get("/health")
    client.get("/health/ready")
    response = client.get(f"/trips/{trip_id}", headers=headers)
    missing = client.get(f"/trips/{trip_id}")  # no login

    access = [r.getMessage() for r in logs.records if r.name == "app.request"]
    assert len(access) == 2  # the two health checks were not logged
    assert access[0].startswith(f"GET /trips/{trip_id} -> 200 in ") and " ms user=" in access[0]
    assert access[0].rsplit("user=", 1)[1] != "-"
    assert access[1].startswith(f"GET /trips/{trip_id} -> 401") and access[1].endswith("user=-")
    assert response.headers["X-Request-Id"] != missing.headers["X-Request-Id"]
    assert user_id  # users exist; the line holds one of them


def test_an_unexpected_error_returns_the_standard_body_and_logs_the_traceback_with_the_same_id(client, logs):
    router = APIRouter()

    @router.get("/_boom")
    def boom():
        raise RuntimeError("secret internal detail")

    app.include_router(router)
    try:
        response = client.get("/_boom")
    finally:
        app.router.routes[:] = [r for r in app.router.routes if getattr(r, "path", None) != "/_boom"]

    assert response.status_code == 500
    body = response.json()
    assert body["code"] == "INTERNAL_ERROR" and body["requestId"] == response.headers["X-Request-Id"]
    assert "secret internal detail" not in response.text  # nothing internal reaches the browser
    failures = [r for r in of_request(logs, body["requestId"]) if r.exc_info]
    assert failures and "secret internal detail" in str(failures[0].exc_info[1])


def test_the_log_level_comes_from_the_settings(monkeypatch):
    root = logging.getLogger()
    previous = root.level
    try:
        monkeypatch.setattr(get_settings(), "log_level", "WARNING")
        logging_setup.setup_logging()
        assert root.level == logging.WARNING
        monkeypatch.setattr(get_settings(), "log_level", "nonsense")
        logging_setup.setup_logging()
        assert root.level == logging.INFO  # an unknown level falls back to INFO
    finally:
        root.setLevel(previous)
