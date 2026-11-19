import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select, update

from app import provider_client as provider
from app.auth import CurrentUser
from app.bookings import latest_attempts, live_attempt, lock_item
from app.errors import ApiError
from app.itinerary_rules import ItemFacts, TripFacts, evaluate
from app.models import BOOKING_CONFIRMED, ItineraryItem, Trip
from app.search import map_provider_error
from app.trips import SessionDep, _trip_out, can_edit, can_read, get_trip_for_user, require

router = APIRouter(tags=["itinerary"])


class Price(BaseModel):
    amount: str
    currency: str


class WarningOut(BaseModel):
    code: str
    message: str


class ItemOut(BaseModel):
    id: str
    offerId: str
    providerId: str
    category: str
    title: str
    description: str
    destination: str
    origin: str | None
    startsAt: datetime | None
    endsAt: datetime | None
    travelers: int
    price: Price | None
    acceptedPrice: Price | None  # the provider's accepted price once the item's booking is confirmed
    revision: str
    available: bool
    validUntil: datetime | None
    restrictions: list[str]  # as the provider stated them when the offer was added or last refreshed
    status: str
    warnings: list[WarningOut]
    addedAt: datetime


class ItineraryOut(BaseModel):
    version: int
    items: list[ItemOut]


def list_items(session, trip_id: uuid.UUID) -> list[ItineraryItem]:
    return list(
        session.scalars(
            select(ItineraryItem)
            .where(ItineraryItem.trip_id == trip_id)
            .order_by(ItineraryItem.position, ItineraryItem.added_at)
        )
    )


def _accepted_price(attempt) -> Price | None:
    if attempt is None or attempt.status != BOOKING_CONFIRMED or attempt.accepted_amount is None:
        return None
    return Price(amount=f"{attempt.accepted_amount:.2f}", currency=attempt.currency)


def itinerary_out(trip, items: list[ItineraryItem], attempts: dict) -> ItineraryOut:
    """The itinerary as everyone sees it: stored order, status and warnings computed now.
    `attempts` maps item id to its latest booking attempt."""
    facts = [
        ItemFacts(
            i.id, i.title, i.category, i.destination, i.starts_at, i.ends_at, i.price_amount, i.valid_until,
            attempts[i.id].status if i.id in attempts else None,
        )
        for i in items
    ]
    evaluations = evaluate(facts, TripFacts(trip.start_date, trip.end_date, tuple(trip.destinations)), datetime.now(timezone.utc))
    return ItineraryOut(
        version=trip.version,
        items=[
            ItemOut(
                id=str(i.id),
                offerId=i.offer_id,
                providerId=i.provider_id,
                category=i.category,
                title=i.title,
                description=i.description,
                destination=i.destination,
                origin=i.origin,
                startsAt=i.starts_at,
                endsAt=i.ends_at,
                travelers=i.travelers,
                price=None if i.price_amount is None else Price(amount=f"{i.price_amount:.2f}", currency=i.currency),
                acceptedPrice=_accepted_price(attempts.get(i.id)),
                revision=i.revision,
                available=i.available,
                validUntil=i.valid_until,
                restrictions=list(i.restrictions or []),
                status=evaluations[i.id].status,
                warnings=[WarningOut(code=w.code, message=w.message) for w in evaluations[i.id].warnings],
                addedAt=i.added_at,
            )
            for i in items
        ],
    )


@router.get("/trips/{trip_id}/itinerary")
def get_itinerary(trip_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> ItineraryOut:
    trip, role = get_trip_for_user(session, trip_id, user)
    require(can_read(role))
    return itinerary_out(trip, list_items(session, trip_id), latest_attempts(session, trip_id))


# ---- Changes (organizer and editor). Every change carries the trip version the client last saw. ----

Version = Annotated[int, Field(ge=1)]


class AddIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    offerId: Annotated[str, Field(min_length=1, max_length=128)]
    version: Version


class RefreshIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Version


class OrderIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    itemIds: list[uuid.UUID]
    version: Version


def _require_editor(session, trip_id: uuid.UUID, user) -> None:
    _, role = get_trip_for_user(session, trip_id, user)
    require(can_edit(role), "You are not allowed to change this itinerary.")


def _current(session, trip_id: uuid.UUID) -> tuple[Trip, list[ItineraryItem]]:
    trip = session.scalars(
        select(Trip).where(Trip.id == trip_id).execution_options(populate_existing=True)
    ).one()
    return trip, list_items(session, trip_id)


def _conflict(session, trip_id: uuid.UUID, user) -> ApiError:
    """The 409 for a stale version: nothing was changed; the body carries the latest state."""
    session.rollback()
    _, role = get_trip_for_user(session, trip_id, user)
    trip, items = _current(session, trip_id)
    return ApiError(
        409,
        "VERSION_CONFLICT",
        "The itinerary was changed by someone else. Review the latest version.",
        {
            "latest": {
                "trip": _trip_out(trip, role).model_dump(mode="json"),
                "itinerary": itinerary_out(trip, items, latest_attempts(session, trip_id)).model_dump(mode="json"),
            }
        },
    )


def _bump_version(session, trip_id: uuid.UUID, version: int, user) -> None:
    """Check the version and increase it in one statement. The row stays locked until commit, so
    concurrent writers queue up and the later one sees a changed version."""
    bumped = session.scalar(
        update(Trip)
        .where(Trip.id == trip_id, Trip.version == version)
        .values(version=Trip.version + 1, updated_at=func.now())
        .returning(Trip.id)
    )
    if bumped is None:
        raise _conflict(session, trip_id, user)


def _booked() -> ApiError:
    return ApiError(409, "ITEM_BOOKED", "This item has a booking in progress or confirmed, so it cannot be changed.")


def _renumber(items: list[ItineraryItem]) -> None:
    for position, item in enumerate(items):
        if item.position != position:
            item.position = position


def _finish(session, trip_id: uuid.UUID) -> ItineraryOut:
    session.commit()
    trip, items = _current(session, trip_id)
    return itinerary_out(trip, items, latest_attempts(session, trip_id))


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "-")


@router.post("/trips/{trip_id}/itinerary", status_code=201)
def add_item(trip_id: uuid.UUID, body: AddIn, user: CurrentUser, session: SessionDep, request: Request) -> ItineraryOut:
    trip, role = get_trip_for_user(session, trip_id, user)
    require(can_edit(role), "You are not allowed to change this itinerary.")
    if trip.version != body.version:
        raise _conflict(session, trip_id, user)

    # The offer comes from the provider, never from the client, so prices cannot be invented.
    try:
        offer = provider.get_offer(body.offerId)
    except provider.ProviderNotFound as exc:
        raise ApiError(404, "NOT_FOUND", "Offer not found.") from exc
    except provider.ProviderError as exc:
        raise map_provider_error(exc, _request_id(request), "add to itinerary") from exc

    if offer.destination not in trip.destinations:
        raise ApiError(
            400, "VALIDATION_ERROR", "Some fields are invalid.", {"fields": {"offerId": "Destination is not part of this trip"}}
        )
    if not offer.available:
        raise ApiError(409, "OFFER_UNAVAILABLE", "This offer is no longer available.")

    _bump_version(session, trip_id, body.version, user)
    items = list_items(session, trip_id)
    if any(i.offer_id == offer.id for i in items):
        session.rollback()
        raise ApiError(409, "ALREADY_IN_ITINERARY", "This offer is already in the itinerary.")

    new_item = ItineraryItem(
        trip_id=trip_id,
        position=0,
        offer_id=offer.id,
        provider_id=offer.providerId,
        category=offer.category,
        title=offer.title,
        description=offer.description,
        destination=offer.destination,
        origin=offer.origin,
        starts_at=offer.startsAt,
        ends_at=offer.endsAt,
        travelers=offer.travelers,
        price_amount=Decimal(offer.price.amount),
        currency=offer.price.currency,
        revision=offer.revision,
        available=offer.available,
        valid_until=offer.validUntil,
        restrictions=list(offer.restrictions),
        added_by=user.id,
    )
    # Chronological place: before the first item that starts later (items without a start keep their place).
    index = next(
        (n for n, i in enumerate(items) if i.starts_at is not None and i.starts_at > offer.startsAt), len(items)
    )
    items.insert(index, new_item)
    session.add(new_item)
    _renumber(items)
    return _finish(session, trip_id)


@router.delete("/trips/{trip_id}/itinerary/{item_id}")
def remove_item(
    trip_id: uuid.UUID, item_id: uuid.UUID, version: Annotated[int, Query(ge=1)], user: CurrentUser, session: SessionDep
) -> ItineraryOut:
    _require_editor(session, trip_id, user)
    _bump_version(session, trip_id, version, user)
    items = list_items(session, trip_id)
    target = next((i for i in items if i.id == item_id), None)
    if target is None:
        session.rollback()
        raise ApiError(404, "NOT_FOUND", "This item is not in the itinerary (it may already have been removed).")
    # Lock the item so a booking cannot slip in between this check and the delete.
    lock_item(session, trip_id, item_id)
    if live_attempt(session, item_id) is not None:
        session.rollback()
        raise _booked()
    session.delete(target)
    items.remove(target)
    _renumber(items)
    return _finish(session, trip_id)


@router.put("/trips/{trip_id}/itinerary/order")
def reorder_items(trip_id: uuid.UUID, body: OrderIn, user: CurrentUser, session: SessionDep) -> ItineraryOut:
    _require_editor(session, trip_id, user)
    _bump_version(session, trip_id, body.version, user)
    items = list_items(session, trip_id)
    by_id = {i.id: i for i in items}
    if len(body.itemIds) != len(set(body.itemIds)) or set(body.itemIds) != set(by_id):
        session.rollback()
        raise ApiError(
            400,
            "VALIDATION_ERROR",
            "Some fields are invalid.",
            {"fields": {"itemIds": "The order must list every current item exactly once"}},
        )
    _renumber([by_id[item_id] for item_id in body.itemIds])
    return _finish(session, trip_id)


# ---- Quote and refresh (organizer and editor) ----


class Terms(BaseModel):
    price: Price
    revision: str
    available: bool
    validUntil: datetime | None
    expired: bool


class QuoteOut(BaseModel):
    """The offer as the provider has it now, next to what the itinerary saved, with what differs."""

    itemId: str
    saved: Terms
    current: Terms
    changes: list[Literal["price", "revision", "availability", "expired", "restrictions"]]
    savedRestrictions: list[str]
    restrictions: list[str]  # the provider's current restrictions
    description: str  # the provider's current description; the mock states its conditions there
    bookable: bool
    reason: str | None


def _terms(price: Decimal | None, currency: str, revision: str, available: bool, valid_until, now) -> Terms:
    return Terms(
        price=Price(amount="0.00" if price is None else f"{price:.2f}", currency=currency),
        revision=revision,
        available=available,
        validUntil=valid_until,
        expired=valid_until is not None and valid_until.astimezone(timezone.utc) < now,
    )


def _fetch_offer(item: ItineraryItem, request: Request, action: str) -> provider.ProviderOffer:
    try:
        return provider.get_offer(item.offer_id)
    except provider.ProviderNotFound as exc:
        raise ApiError(404, "NOT_FOUND", "The provider no longer offers this item.") from exc
    except provider.ProviderError as exc:
        raise map_provider_error(exc, _request_id(request), action) from exc


def _item_or_404(session, trip_id: uuid.UUID, item_id: uuid.UUID) -> ItineraryItem:
    item = next((i for i in list_items(session, trip_id) if i.id == item_id), None)
    if item is None:
        raise ApiError(404, "NOT_FOUND", "This item is not in the itinerary (it may already have been removed).")
    return item


@router.get("/trips/{trip_id}/itinerary/{item_id}/quote")
def get_quote(trip_id: uuid.UUID, item_id: uuid.UUID, user: CurrentUser, session: SessionDep, request: Request) -> QuoteOut:
    _require_editor(session, trip_id, user)
    item = _item_or_404(session, trip_id, item_id)
    offer = _fetch_offer(item, request, "price check")
    now = datetime.now(timezone.utc)
    saved = _terms(item.price_amount, item.currency, item.revision, item.available, item.valid_until, now)
    current = _terms(Decimal(offer.price.amount), offer.price.currency, offer.revision, offer.available, offer.validUntil, now)

    changes = []
    if saved.price != current.price:
        changes.append("price")
    if saved.revision != current.revision:
        changes.append("revision")
    if saved.available != current.available:
        changes.append("availability")
    if current.expired:
        changes.append("expired")
    if list(item.restrictions or []) != list(offer.restrictions):
        changes.append("restrictions")
    reason = None
    if not current.available:
        reason = "This offer is no longer available."
    elif current.expired:
        reason = "This quote has expired. Refresh the price to get a new quote."
    return QuoteOut(
        itemId=str(item.id),
        saved=saved,
        current=current,
        changes=changes,
        savedRestrictions=list(item.restrictions or []),
        restrictions=list(offer.restrictions),
        description=offer.description,
        bookable=reason is None,
        reason=reason,
    )


@router.post("/trips/{trip_id}/itinerary/{item_id}/refresh")
def refresh_item(
    trip_id: uuid.UUID, item_id: uuid.UUID, body: RefreshIn, user: CurrentUser, session: SessionDep, request: Request
) -> ItineraryOut:
    """Replace the saved price, revision, availability and quote expiry with the provider's current terms."""
    trip, role = get_trip_for_user(session, trip_id, user)
    require(can_edit(role), "You are not allowed to change this itinerary.")
    if trip.version != body.version:
        raise _conflict(session, trip_id, user)
    item = _item_or_404(session, trip_id, item_id)
    if live_attempt(session, item_id) is not None:
        raise _booked()
    offer = _fetch_offer(item, request, "price refresh")

    _bump_version(session, trip_id, body.version, user)
    locked = lock_item(session, trip_id, item_id)
    if locked is None:
        session.rollback()
        raise ApiError(404, "NOT_FOUND", "This item is not in the itinerary (it may already have been removed).")
    if live_attempt(session, item_id) is not None:
        session.rollback()
        raise _booked()
    locked.price_amount = Decimal(offer.price.amount)
    locked.currency = offer.price.currency
    locked.revision = offer.revision
    locked.available = offer.available
    locked.valid_until = offer.validUntil
    locked.restrictions = list(offer.restrictions)
    return _finish(session, trip_id)
