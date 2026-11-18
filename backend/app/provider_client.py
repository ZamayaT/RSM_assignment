"""HTTP client for the provider's offer search, with typed results and typed errors."""
import logging
import time
from datetime import date, datetime
from typing import Literal

import httpx
from pydantic import BaseModel, ValidationError

from app.config import get_settings

logger = logging.getLogger("app.provider")


# ---- Typed result (fields as the provider sends them; price stays a two-decimal string) ----


class Money(BaseModel):
    amount: str
    currency: str


class ProviderOffer(BaseModel):
    id: str
    providerId: str
    category: Literal["transport", "accommodation", "activity"]
    title: str
    description: str
    destination: str
    origin: str | None = None
    startsAt: datetime
    endsAt: datetime
    travelers: int
    price: Money
    revision: str
    available: bool
    validUntil: datetime


class SupplierWarning(BaseModel):
    providerId: str
    code: str
    message: str


class SearchResult(BaseModel):
    offers: list[ProviderOffer]
    partial: bool
    warnings: list[SupplierWarning]
    searchedAt: datetime


class SearchParams(BaseModel):
    category: str
    destination: str
    origin: str | None = None
    startsOn: date
    endsOn: date
    travelers: int
    providerId: str | None = None


# ---- Typed errors ----


class ProviderError(Exception):
    """Base class. `request_id` is the provider's request id, when it sent one (for logs only)."""

    def __init__(self, message: str, request_id: str | None = None):
        super().__init__(message)
        self.request_id = request_id


class ProviderBadRequest(ProviderError):
    """Provider 400. `fields` maps request field names (without the `body.` prefix) to messages."""

    def __init__(self, message: str, fields: dict[str, str], request_id: str | None = None):
        super().__init__(message, request_id)
        self.fields = fields


class ProviderRateLimited(ProviderError):
    """Provider 429. `retry_after` is the seconds the provider asked to wait, if it said so."""

    def __init__(self, message: str, retry_after: int | None, request_id: str | None = None):
        super().__init__(message, request_id)
        self.retry_after = retry_after


class ProviderUnavailable(ProviderError):
    """Provider 503: no queried supplier could complete the search."""


class ProviderTimeout(ProviderError):
    """No response within the configured timeout."""


class ProviderUnreachable(ProviderError):
    """Connection to the provider failed."""


class ProviderMalformedResponse(ProviderError):
    """Unparseable body or an unexpected status."""


# ---- Client ----


def _retry_after(response: httpx.Response) -> int | None:
    value = response.headers.get("Retry-After")
    return int(value) if value is not None and value.strip().isdigit() else None


def _bad_request_fields(response: httpx.Response) -> dict[str, str]:
    try:
        errors = response.json()["details"]["errors"]
        return {str(e["field"]).removeprefix("body."): str(e["message"]) for e in errors}
    except (ValueError, KeyError, TypeError):
        return {}


def search_offers(params: SearchParams, transport: httpx.BaseTransport | None = None) -> SearchResult:
    """POST /offers/search. No retries: callers see the failure and may repeat the search."""
    settings = get_settings()
    started = time.monotonic()
    try:
        with httpx.Client(
            base_url=settings.provider_base_url,
            headers={"Authorization": f"Bearer {settings.provider_token}"},
            timeout=settings.provider_timeout_seconds,
            transport=transport,
        ) as client:
            response = client.post("/offers/search", json=params.model_dump(mode="json", exclude_none=True))
    except httpx.TimeoutException as exc:
        logger.warning("provider search timed out: %s", exc)
        raise ProviderTimeout("The provider did not answer in time.") from exc
    except httpx.TransportError as exc:
        logger.warning("provider unreachable: %s", exc)
        raise ProviderUnreachable("The provider could not be reached.") from exc

    request_id = response.headers.get("X-Request-Id")
    logger.info(
        "provider search status=%s request_id=%s elapsed_ms=%d",
        response.status_code,
        request_id,
        (time.monotonic() - started) * 1000,
    )

    status = response.status_code
    if status == 200:
        try:
            return SearchResult.model_validate(response.json())
        except (ValueError, ValidationError) as exc:
            raise ProviderMalformedResponse("The provider returned an invalid search response.", request_id) from exc
    if status == 400:
        raise ProviderBadRequest("The provider rejected the search.", _bad_request_fields(response), request_id)
    if status == 429:
        raise ProviderRateLimited("The provider is rate limiting searches.", _retry_after(response), request_id)
    if status == 503:
        raise ProviderUnavailable("The provider is unavailable.", request_id)
    raise ProviderMalformedResponse(f"Unexpected provider status {status}.", request_id)
