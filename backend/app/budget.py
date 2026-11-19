"""Budget: pure Decimal calculations and the read endpoint.

Rounding rule: amounts are exact two-decimal sums (provider prices already have two decimals); any result with
more decimals would be rounded half-up to the cent. An item's cost is the offer's total price for the party.
"""
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from app.auth import CurrentUser
from app.bookings import latest_attempts
from app.itinerary import list_items
from app.itinerary_rules import EXPIRED_QUOTE, ItemFacts, evaluate, TripFacts
from app.models import BOOKING_CONFIRMED, ItineraryItem
from app.trips import SessionDep, can_read, get_trip_for_user, require

router = APIRouter(tags=["budget"])

CENT = Decimal("0.01")
ESTIMATE = "estimate"
CONFIRMED = "confirmed"


def money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class BudgetLine:
    item_id: str
    title: str
    category: str
    amount: Decimal | None  # None: the item has no price and is left out of the totals
    kind: str  # "estimate" or "confirmed"
    expired: bool = False
    status: str = "estimate"  # the item's status label (estimate, booking_pending, confirmed, ...)


@dataclass(frozen=True)
class BudgetTotals:
    estimated: Decimal
    confirmed: Decimal
    combined: Decimal
    budget: Decimal
    remaining: Decimal  # negative when over budget

    @property
    def over_budget(self) -> bool:
        return self.remaining < 0


def compute_totals(lines: list[BudgetLine], budget: Decimal) -> BudgetTotals:
    estimated = money(sum((l.amount for l in lines if l.kind == ESTIMATE and l.amount is not None), Decimal("0")))
    confirmed = money(sum((l.amount for l in lines if l.kind == CONFIRMED and l.amount is not None), Decimal("0")))
    combined = money(estimated + confirmed)
    return BudgetTotals(estimated, confirmed, combined, money(budget), money(budget - combined))


class BudgetLineOut(BaseModel):
    itemId: str
    title: str
    category: str
    amount: str | None
    kind: Literal["estimate", "confirmed"]
    expired: bool
    status: str


class BudgetOut(BaseModel):
    currency: str = "USD"
    lines: list[BudgetLineOut]
    estimatedTotal: str
    confirmedTotal: str
    combinedTotal: str
    budget: str
    remaining: str
    overBudget: bool


@router.get("/trips/{trip_id}/budget")
def get_budget(trip_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> BudgetOut:
    trip, role = get_trip_for_user(session, trip_id, user)
    require(can_read(role))
    return build_budget(trip, list_items(session, trip_id), latest_attempts(session, trip_id))


def build_budget(trip, items: list[ItineraryItem], attempts: dict) -> BudgetOut:
    """The budget as everyone sees it. `attempts` maps item id to its latest booking attempt."""
    facts = [
        ItemFacts(
            i.id, i.title, i.category, i.destination, i.starts_at, i.ends_at, i.price_amount, i.valid_until,
            attempts[i.id].status if i.id in attempts else None,
        )
        for i in items
    ]
    evaluations = evaluate(facts, TripFacts(trip.start_date, trip.end_date, tuple(trip.destinations)), datetime.now(timezone.utc))
    lines = []
    for i in items:
        ev = evaluations[i.id]
        attempt = attempts.get(i.id)
        if attempt is not None and attempt.status == BOOKING_CONFIRMED:
            # The accepted price from the provider's booking; later provider price changes never alter it.
            lines.append(BudgetLine(str(i.id), i.title, i.category, attempt.accepted_amount, CONFIRMED, False, ev.status))
        else:
            expired = any(w.code == EXPIRED_QUOTE for w in ev.warnings)
            lines.append(BudgetLine(str(i.id), i.title, i.category, i.price_amount, ESTIMATE, expired, ev.status))
    totals = compute_totals(lines, trip.budget)
    return BudgetOut(
        lines=[
            BudgetLineOut(
                itemId=l.item_id,
                title=l.title,
                category=l.category,
                amount=None if l.amount is None else f"{money(l.amount):.2f}",
                kind=l.kind,
                expired=l.expired,
                status=l.status,
            )
            for l in lines
        ],
        estimatedTotal=f"{totals.estimated:.2f}",
        confirmedTotal=f"{totals.confirmed:.2f}",
        combinedTotal=f"{totals.combined:.2f}",
        budget=f"{totals.budget:.2f}",
        remaining=f"{totals.remaining:.2f}",
        overBudget=totals.over_budget,
    )
