import logging
import uuid
from datetime import date, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

from app import provider_client as provider
from app.auth import CurrentUser
from app.errors import ApiError
from app.search_constants import CATEGORIES, ORIGINS, SUPPLIERS
from app.trips import SessionDep, get_trip_for_user

logger = logging.getLogger("app.search")

router = APIRouter(tags=["search"])


@router.get("/search/options")
def search_options(_: CurrentUser) -> dict[str, list[str]]:
    return {"categories": list(CATEGORIES), "origins": list(ORIGINS), "suppliers": list(SUPPLIERS)}


class SearchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: Literal["transport", "accommodation", "activity"]
    destination: Annotated[str, Field(min_length=1, max_length=200)]
    origin: Annotated[str, Field(min_length=1, max_length=200)] | None = None
    startsOn: date | None = None
    endsOn: date | None = None
    travelers: Annotated[int, Field(strict=True, ge=1, le=20)] | None = None
    providerId: Annotated[str, Field(min_length=1, max_length=128)] | None = None


class SearchWarning(BaseModel):
    providerId: str
    code: str
    message: str


class SearchOut(BaseModel):
    state: Literal["complete", "partial", "empty"]
    offers: list[provider.ProviderOffer]
    warnings: list[SearchWarning]
    searchedAt: datetime


def _fail(fields: dict[str, str]) -> ApiError:
    return ApiError(400, "VALIDATION_ERROR", "Some fields are invalid.", {"fields": fields})


def _warning_message(code: str, supplier: str) -> str:
    if code == "RATE_LIMITED":
        return f"{supplier} is limiting requests; its results are missing."
    if code == "PROVIDER_TIMEOUT":
        return f"{supplier} did not answer in time; its results are missing."
    return f"{supplier} is unavailable; its results are missing."


def map_provider_error(exc: provider.ProviderError, request_id: str, action: str = "search") -> ApiError:
    """Standard error for a failed provider call; provider text is only logged, never returned."""
    logger.warning(
        "%s failed: %s request_id=%s provider_request_id=%s", action, type(exc).__name__, request_id, exc.request_id
    )
    if isinstance(exc, provider.ProviderBadRequest) and exc.fields:
        return _fail(exc.fields)
    if isinstance(exc, provider.ProviderRateLimited):
        headers = {"Retry-After": str(exc.retry_after)} if exc.retry_after is not None else None
        return ApiError(429, "RATE_LIMITED", "The provider is limiting requests. Please try again shortly.", headers=headers)
    if isinstance(exc, provider.ProviderUnavailable) or isinstance(exc, provider.ProviderUnreachable):
        return ApiError(503, "PROVIDER_UNAVAILABLE", "The providers are unavailable. Please try again later.")
    if isinstance(exc, provider.ProviderTimeout):
        return ApiError(504, "PROVIDER_TIMEOUT", f"The {action} took too long. Please try again.")
    return ApiError(502, "PROVIDER_ERROR", f"The {action} could not be completed. Please try again later.")


@router.post("/trips/{trip_id}/search")
def search_trip(trip_id: uuid.UUID, body: SearchIn, user: CurrentUser, session: SessionDep, request: Request) -> SearchOut:
    """Search offers for a trip. Changes nothing; any participant (viewers too) may search."""
    trip, _role = get_trip_for_user(session, trip_id, user)

    starts_on = body.startsOn or trip.start_date
    ends_on = body.endsOn or trip.end_date
    travelers = body.travelers or trip.travelers

    fields: dict[str, str] = {}
    if body.destination not in trip.destinations:
        fields["destination"] = "Destination is not part of this trip"
    if body.category == "transport" and body.origin is None:
        fields["origin"] = "Origin is required for transport"
    elif body.category == "transport" and body.origin not in ORIGINS:
        fields["origin"] = "Unsupported origin"
    if starts_on > ends_on:
        fields["endsOn"] = "End date must not be before the start date"
    if fields:
        raise _fail(fields)

    params = provider.SearchParams(
        category=body.category,
        destination=body.destination,
        origin=body.origin if body.category == "transport" else None,
        startsOn=starts_on,
        endsOn=ends_on,
        travelers=travelers,
        providerId=body.providerId,
    )
    request_id = getattr(request.state, "request_id", "-")
    try:
        result = provider.search_offers(params)
    except provider.ProviderError as exc:
        raise map_provider_error(exc, request_id) from exc

    if result.partial:
        state = "partial"
    elif not result.offers:
        state = "empty"
    else:
        state = "complete"
    warnings = [
        SearchWarning(providerId=w.providerId, code=w.code, message=_warning_message(w.code, w.providerId))
        for w in result.warnings
    ]
    return SearchOut(state=state, offers=result.offers, warnings=warnings, searchedAt=result.searchedAt)
