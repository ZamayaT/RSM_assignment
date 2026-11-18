"""HTTP client for the provider's offer search, with typed results and typed errors."""
import logging
import time
from datetime import date, datetime
from typing import Literal
from urllib.parse import quote

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


class ProviderNotFound(ProviderError):
    """Provider 404: no such record."""


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


def _call(
    method: str,
    path: str,
    what: str,
    json: dict | None = None,
    transport: httpx.BaseTransport | None = None,
) -> tuple[httpx.Response, str | None]:
    """One provider request. Returns the 200 response; every other outcome raises a typed error.

    No retries: callers see the failure and may repeat the action.
    """
    settings = get_settings()
    started = time.monotonic()
    try:
        with httpx.Client(
            base_url=settings.provider_base_url,
            headers={"Authorization": f"Bearer {settings.provider_token}"},
            timeout=settings.provider_timeout_seconds,
            transport=transport,
        ) as client:
            response = client.request(method, path, json=json)
    except httpx.TimeoutException as exc:
        logger.warning("provider %s timed out: %s", what, exc)
        raise ProviderTimeout("The provider did not answer in time.") from exc
    except httpx.TransportError as exc:
        logger.warning("provider %s unreachable: %s", what, exc)
        raise ProviderUnreachable("The provider could not be reached.") from exc

    request_id = response.headers.get("X-Request-Id")
    logger.info(
        "provider %s status=%s request_id=%s elapsed_ms=%d",
        what,
        response.status_code,
        request_id,
        (time.monotonic() - started) * 1000,
    )

    status = response.status_code
    if status == 200:
        return response, request_id
    if status == 400:
        raise ProviderBadRequest("The provider rejected the request.", _bad_request_fields(response), request_id)
    if status == 404:
        raise ProviderNotFound("The provider does not know this record.", request_id)
    if status == 429:
        raise ProviderRateLimited("The provider is rate limiting requests.", _retry_after(response), request_id)
    if status == 503:
        raise ProviderUnavailable("The provider is unavailable.", request_id)
    raise ProviderMalformedResponse(f"Unexpected provider status {status}.", request_id)


def search_offers(params: SearchParams, transport: httpx.BaseTransport | None = None) -> SearchResult:
    """POST /offers/search."""
    response, request_id = _call(
        "POST", "/offers/search", "search", params.model_dump(mode="json", exclude_none=True), transport
    )
    try:
        return SearchResult.model_validate(response.json())
    except (ValueError, ValidationError) as exc:
        raise ProviderMalformedResponse("The provider returned an invalid search response.", request_id) from exc


def get_offer(offer_id: str, transport: httpx.BaseTransport | None = None) -> ProviderOffer:
    """GET /offers/{id}: the offer as the provider has it now. Unknown ids raise ProviderNotFound."""
    response, request_id = _call("GET", f"/offers/{quote(offer_id, safe='')}", "get offer", None, transport)
    try:
        return ProviderOffer.model_validate(response.json())
    except (ValueError, ValidationError) as exc:
        raise ProviderMalformedResponse("The provider returned an invalid offer.", request_id) from exc
