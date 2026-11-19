import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, StringConstraints, field_serializer, field_validator
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.auth import CurrentUser
from app.db import get_session
from app.destinations import SUPPORTED_DESTINATIONS
from app.errors import ApiError
from app.models import ROLE_EDITOR, ROLE_ORGANIZER, ROLES, Trip, TripParticipant, User

router = APIRouter(prefix="/trips", tags=["trips"])

SessionDep = Annotated[Session, Depends(get_session)]


class TripIn(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
    destinations: Annotated[list[str], Field(min_length=1)]
    startDate: date
    endDate: date
    travelers: Annotated[int, Field(ge=1, le=20)]
    budget: Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=2)]
    notes: Annotated[str | None, StringConstraints(strip_whitespace=True, max_length=2000)] = None

    @field_validator("destinations")
    @classmethod
    def _known_destinations(cls, value: list[str]) -> list[str]:
        unknown = [d for d in value if d not in SUPPORTED_DESTINATIONS]
        if unknown:
            raise ValueError(f"Unsupported destination: {', '.join(unknown)}")
        return list(dict.fromkeys(value))

    @field_validator("endDate")
    @classmethod
    def _end_not_before_start(cls, value: date, info) -> date:
        start = info.data.get("startDate")
        if start is not None and value < start:
            raise ValueError("End date must not be before the start date")
        return value

    @field_validator("notes")
    @classmethod
    def _blank_notes_to_none(cls, value: str | None) -> str | None:
        return value or None


class TripUpdateIn(TripIn):
    version: Annotated[int, Field(ge=1)]


class TripOut(BaseModel):
    id: str
    name: str
    destinations: list[str]
    startDate: date
    endDate: date
    travelers: int
    budget: Decimal
    notes: str | None
    version: int
    role: str
    createdAt: datetime
    updatedAt: datetime

    @field_serializer("budget")
    def _budget_two_decimals(self, value: Decimal) -> str:
        return f"{value:.2f}"


def _trip_out(trip: Trip, role: str) -> TripOut:
    return TripOut(
        id=str(trip.id),
        name=trip.name,
        destinations=list(trip.destinations),
        startDate=trip.start_date,
        endDate=trip.end_date,
        travelers=trip.travelers,
        budget=trip.budget,
        notes=trip.notes,
        version=trip.version,
        role=role,
        createdAt=trip.created_at,
        updatedAt=trip.updated_at,
    )


def can_read(role: str) -> bool:
    """Any participant may read the trip."""
    return role in ROLES


def can_edit(role: str) -> bool:
    """Organizer and editor may change the trip."""
    return role in (ROLE_ORGANIZER, ROLE_EDITOR)


def can_manage_participants(role: str) -> bool:
    """Only the organizer manages who is on the trip and with which role."""
    return role == ROLE_ORGANIZER


def require(allowed: bool, message: str = "You are not allowed to do this on this trip.") -> None:
    """403 for a participant whose role does not allow the action (non-participants already got 404)."""
    if not allowed:
        raise ApiError(403, "FORBIDDEN", message)


def get_trip_for_user(session: Session, trip_id: uuid.UUID, user: User) -> tuple[Trip, str]:
    """The trip and the user's role in it; 404 when the user does not participate (existence stays hidden)."""
    row = session.execute(
        select(Trip, TripParticipant.role)
        .join(TripParticipant, TripParticipant.trip_id == Trip.id)
        .where(Trip.id == trip_id, TripParticipant.user_id == user.id)
    ).first()
    if row is None:
        raise ApiError(404, "NOT_FOUND", "Trip not found.")
    return row[0], row[1]


@router.post("", status_code=201)
def create_trip(body: TripIn, user: CurrentUser, session: SessionDep) -> TripOut:
    trip = Trip(
        name=body.name,
        destinations=body.destinations,
        start_date=body.startDate,
        end_date=body.endDate,
        travelers=body.travelers,
        budget=body.budget,
        notes=body.notes,
        version=1,
    )
    session.add(trip)
    session.flush()
    session.add(TripParticipant(trip_id=trip.id, user_id=user.id, role=ROLE_ORGANIZER))
    session.commit()
    session.refresh(trip)
    return _trip_out(trip, ROLE_ORGANIZER)


@router.get("")
def list_trips(user: CurrentUser, session: SessionDep) -> list[TripOut]:
    rows = session.execute(
        select(Trip, TripParticipant.role)
        .join(TripParticipant, TripParticipant.trip_id == Trip.id)
        .where(TripParticipant.user_id == user.id)
        .order_by(Trip.start_date, Trip.created_at)
    ).all()
    return [_trip_out(trip, role) for trip, role in rows]


@router.get("/{trip_id}")
def get_trip(trip_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> TripOut:
    trip, role = get_trip_for_user(session, trip_id, user)
    require(can_read(role))
    return _trip_out(trip, role)


@router.put("/{trip_id}")
def update_trip(trip_id: uuid.UUID, body: TripUpdateIn, user: CurrentUser, session: SessionDep) -> TripOut:
    trip, role = get_trip_for_user(session, trip_id, user)
    require(can_edit(role), "You are not allowed to edit this trip.")

    # Check and update in one statement: if another save got in first, no row matches the version.
    updated = session.scalar(
        update(Trip)
        .where(Trip.id == trip_id, Trip.version == body.version)
        .values(
            name=body.name,
            destinations=body.destinations,
            start_date=body.startDate,
            end_date=body.endDate,
            travelers=body.travelers,
            budget=body.budget,
            notes=body.notes,
            version=Trip.version + 1,
            updated_at=func.now(),
        )
        .returning(Trip)
        .execution_options(populate_existing=True)
    )
    if updated is None:
        session.rollback()
        latest, _ = get_trip_for_user(session, trip_id, user)
        raise ApiError(
            409,
            "VERSION_CONFLICT",
            "The trip was changed by someone else. Reload the latest version.",
            {"latest": _trip_out(latest, role).model_dump(mode="json")},
        )
    session.commit()
    return _trip_out(updated, role)
