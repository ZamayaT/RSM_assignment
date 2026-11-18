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
from sqlalchemy import select

from app.auth import CurrentUser
from app.itinerary_rules import ItemFacts, evaluate, STATUS_EXPIRED, TripFacts
from app.models import ItineraryItem
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
    items = list(
        session.scalars(
            select(ItineraryItem)
            .where(ItineraryItem.trip_id == trip_id)
            .order_by(ItineraryItem.position, ItineraryItem.added_at)
        )
    )
    facts = [
        ItemFacts(i.id, i.title, i.category, i.destination, i.starts_at, i.ends_at, i.price_amount, i.valid_until)
        for i in items
    ]
    evaluations = evaluate(facts, TripFacts(trip.start_date, trip.end_date, tuple(trip.destinations)), datetime.now(timezone.utc))
    # Every item is an estimate until bookings exist (change 6).
    lines = [
        BudgetLine(str(i.id), i.title, i.category, i.price_amount, ESTIMATE, evaluations[i.id].status == STATUS_EXPIRED)
        for i in items
    ]
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
