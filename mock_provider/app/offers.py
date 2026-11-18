"""Offer logic shared by the offer endpoints: quote refresh, party-size selection, serialization."""
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.fixtures import DESTINATIONS
from app.models import Offer
from app.schemas import Money, OfferOut

# How long a refreshed quote stays valid.
REFRESH_VALIDITY = timedelta(hours=1)


def next_revision(revision: str) -> str:
    """Opaque to clients; the mock uses r1, r2, ..."""
    match = re.fullmatch(r"r(\d+)", revision)
    return f"r{int(match.group(1)) + 1}" if match else f"{revision}.1"


def destination_tz(destination: str) -> ZoneInfo:
    return ZoneInfo(DESTINATIONS.get(destination, "UTC"))


def refresh_if_expired(session: Session, offer_id: str, now: datetime) -> Offer | None:
    """Return the offer, giving an expired quote a future validUntil and a new revision.

    The row is locked while it is checked, so concurrent callers refresh it only once.
    Returns None for an unknown id. Commits when it refreshed something.
    """
    offer = session.get(Offer, offer_id, with_for_update=True, populate_existing=True)
    if offer is None:
        session.rollback()
        return None
    if offer.valid_until <= now:
        offer.valid_until = now + REFRESH_VALIDITY
        offer.revision = next_revision(offer.revision)
        offer.updated_at = now
    session.commit()
    return offer


def select_for_party(offers: list[Offer], travelers: int) -> list[Offer]:
    """Per listing, keep the exact party-size quote, else the smallest quote for a larger party.

    Quotes of one listing (same supplier, category, destination, origin, title and schedule) differ only
    in party size.
    """
    listings: dict[tuple, list[Offer]] = {}
    for offer in offers:
        key = (offer.provider_id, offer.category, offer.destination, offer.origin, offer.title,
               offer.starts_at, offer.ends_at)
        listings.setdefault(key, []).append(offer)

    chosen = []
    for quotes in listings.values():
        fitting = [q for q in quotes if q.travelers >= travelers]
        if fitting:
            chosen.append(min(fitting, key=lambda q: q.travelers))
    return chosen


def to_schema(offer: Offer) -> OfferOut:
    tz = destination_tz(offer.destination)
    return OfferOut(
        id=offer.id,
        providerId=offer.provider_id,
        category=offer.category,
        title=offer.title,
        description=offer.description,
        destination=offer.destination,
        origin=offer.origin,
        startsAt=offer.starts_at.astimezone(tz),
        endsAt=offer.ends_at.astimezone(tz),
        travelers=offer.travelers,
        price=Money(amount=f"{offer.price_amount:.2f}", currency=offer.currency),
        revision=offer.revision,
        available=offer.available,
        validUntil=offer.valid_until,
    )
