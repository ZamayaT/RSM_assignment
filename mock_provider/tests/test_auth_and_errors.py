"""Authentication and error format, checked on a small app that uses the real dependency and handlers."""
import pytest
from fastapi import APIRouter, Depends, FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field

from app.api import v1_router
from app.auth import get_caller
from app.errors import ApiError, install_error_handling
from app.main import app as real_app


class Probe(BaseModel):
    travelers: int = Field(ge=1, le=20)


def _build_app() -> FastAPI:
    app = FastAPI()
    install_error_handling(app)
    router = APIRouter(prefix="/v1", dependencies=[Depends(get_caller)])

    @router.post("/_probe")
    def probe(body: Probe) -> dict:
        return {"ok": body.travelers}

    @router.get("/_whoami")
    def whoami() -> dict:
        return {}

    @router.get("/_conflict")
    def conflict():
        raise ApiError(409, "OFFER_CHANGED", "changed", details={"offerId": "x"})

    app.include_router(router)
    return app


@pytest.fixture(scope="module")
def client():
    return TestClient(_build_app())


def _assert_error(response, status, code):
    assert response.status_code == status
    body = response.json()
    assert body["code"] == code
    assert body["message"]
    assert body["requestId"]
    assert response.headers["X-Request-Id"] == body["requestId"]
    return body


def test_missing_token_is_unauthorized(client):
    response = client.post("/v1/_probe", json={"travelers": 2})
    _assert_error(response, 401, "UNAUTHORIZED")
    assert response.headers["WWW-Authenticate"] == "Bearer"


@pytest.mark.parametrize("header", ["Bearer wrong", "Basic travel-demo-token", "travel-demo-token", "Bearer "])
def test_invalid_token_is_unauthorized(client, header):
    _assert_error(client.get("/v1/_whoami", headers={"Authorization": header}), 401, "UNAUTHORIZED")


@pytest.mark.parametrize("token", ["travel-demo-token", "other-demo-token"])
def test_demo_tokens_are_accepted(client, token):
    response = client.post("/v1/_probe", json={"travelers": 2}, headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200


def test_authentication_is_checked_before_validation(client):
    _assert_error(client.post("/v1/_probe", json={"travelers": 99}), 401, "UNAUTHORIZED")


AUTH = {"Authorization": "Bearer travel-demo-token"}


def test_invalid_body_is_bad_request_with_details(client):
    body = _assert_error(client.post("/v1/_probe", json={"travelers": 99}, headers=AUTH), 400, "BAD_REQUEST")
    assert body["details"]["errors"][0]["field"] == "body.travelers"


def test_missing_field_and_malformed_json_are_bad_request(client):
    _assert_error(client.post("/v1/_probe", json={}, headers=AUTH), 400, "BAD_REQUEST")
    malformed = client.post("/v1/_probe", content="{nope", headers={**AUTH, "Content-Type": "application/json"})
    _assert_error(malformed, 400, "BAD_REQUEST")


def test_api_error_uses_contract_format_with_details(client):
    body = _assert_error(client.get("/v1/_conflict", headers=AUTH), 409, "OFFER_CHANGED")
    assert body["details"] == {"offerId": "x"}


def test_request_ids_are_unique(client):
    ids = {client.get("/v1/_whoami").json()["requestId"] for _ in range(3)}
    assert len(ids) == 3


def test_unknown_route_is_not_found_in_contract_format():
    _assert_error(TestClient(real_app).get("/v1/nope", headers=AUTH), 404, "NOT_FOUND")


def test_health_needs_no_token():
    assert TestClient(real_app).get("/health").status_code == 200


def test_real_v1_router_requires_authentication():
    assert any(dep.dependency is get_caller for dep in v1_router.dependencies)
