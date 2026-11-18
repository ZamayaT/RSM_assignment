from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.clock import get_clock
from app.db import get_session
from app.errors import ApiError
from app.failures import RATE_LIMITED, WARNING_CODES, apply_latency, failure_error, get_failure
from app.fixtures import ALL_SUPPLIERS, SUPPLIERS
from app.models import Offer
from app.offers import destination_tz, refresh_if_expired, select_for_party, to_schema
from app.schemas import OfferOut, SearchRequest, SearchResponse, SupplierWarning

router = APIRouter(tags=["Offers"])


@router.post("/offers/search", response_model=SearchResponse, response_model_exclude_none=True)
def search_offers(body: SearchRequest, session: Session = Depends(get_session)) -> SearchResponse:
    if body.providerId is not None and body.providerId not in ALL_SUPPLIERS:
        raise ApiError(
            400,
            "BAD_REQUEST",
            "Invalid request parameters or body.",
            details={"errors": [{"field": "body.providerId", "message": "unknown supplier"}]},
        )

    # A supplied providerId queries only that supplier (even one that does not offer the category:
    # it then simply has no matches). Otherwise all suppliers supporting the category are queried.
    queried = [body.providerId] if body.providerId else list(SUPPLIERS[body.category])
    apply_latency(queried)
    failures = {provider: get_failure(provider) for provider in queried}
    succeeded = [provider for provider in queried if failures[provider] is None]
    failed = [provider for provider in queried if failures[provider] is not None]

    if not succeeded:
        only = failures[queried[0]]
        if len(queried) == 1 and only.mode == RATE_LIMITED:
            raise failure_error(only)
        raise ApiError(503, "PROVIDER_UNAVAILABLE", "No queried supplier could complete the search.")

    now = get_clock().now()
    query = select(Offer).where(
        Offer.category == body.category,
        func.lower(Offer.destination) == body.destination.strip().lower(),
        Offer.provider_id.in_(succeeded),
    )
    if body.category == "transport":
        query = query.where(func.lower(Offer.origin) == body.origin.strip().lower())

    # The window is made of destination-local calendar days and must contain the whole offer.
    in_window = [
        offer
        for offer in session.scalars(query)
        if body.startsOn <= offer.starts_at.astimezone(destination_tz(offer.destination)).date()
        and offer.ends_at.astimezone(destination_tz(offer.destination)).date() <= body.endsOn
    ]
    chosen = select_for_party(in_window, body.travelers)

    # Expired quotes are refreshed before they are returned (ids sorted so concurrent searches lock in order).
    offers = []
    for offer_id in sorted(offer.id for offer in chosen):
        refreshed = refresh_if_expired(session, offer_id, now)
        if refreshed is not None:
            offers.append(refreshed)
    offers.sort(key=lambda o: (o.starts_at, o.price_amount, o.id))

    warnings = [
        SupplierWarning(
            providerId=provider,
            code=WARNING_CODES[failures[provider].mode],
            message=f"{provider} did not complete the search.",
        )
        for provider in failed
    ]
    return SearchResponse(
        offers=[to_schema(offer) for offer in offers],
        partial=bool(failed),
        warnings=warnings,
        searchedAt=now,
    )


@router.get("/offers/{offerId}", response_model=OfferOut, response_model_exclude_none=True)
def get_offer(offerId: str, session: Session = Depends(get_session)) -> OfferOut:
    offer = session.get(Offer, offerId)
    if offer is None:
        raise ApiError(404, "NOT_FOUND", "No visible record exists for the supplied identifier.")
    apply_latency([offer.provider_id])
    failure = get_failure(offer.provider_id)
    if failure is not None:
        raise failure_error(failure)
    refreshed = refresh_if_expired(session, offerId, get_clock().now())
    return to_schema(refreshed)
