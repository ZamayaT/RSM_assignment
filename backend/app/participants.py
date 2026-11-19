import uuid
from typing import Literal

from fastapi import APIRouter, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import CurrentUser
from app.errors import ApiError
from app.models import ROLE_ORGANIZER, TripParticipant, User
from app.trips import SessionDep, can_manage_participants, can_read, get_trip_for_user, require

router = APIRouter(prefix="/trips/{trip_id}/participants", tags=["participants"])

# The organizer is the creator and cannot be granted or changed here.
AssignableRole = Literal["editor", "viewer"]


class ParticipantOut(BaseModel):
    userId: str
    username: str
    displayName: str
    role: str


class AddParticipantIn(BaseModel):
    username: str
    role: AssignableRole


class ChangeRoleIn(BaseModel):
    role: AssignableRole


def _out(user: User, role: str) -> ParticipantOut:
    return ParticipantOut(userId=str(user.id), username=user.username, displayName=user.display_name, role=role)


def _load_member(session: Session, trip_id: uuid.UUID, user_id: uuid.UUID) -> tuple[TripParticipant, User]:
    row = session.execute(
        select(TripParticipant, User)
        .join(User, User.id == TripParticipant.user_id)
        .where(TripParticipant.trip_id == trip_id, TripParticipant.user_id == user_id)
    ).first()
    if row is None:
        raise ApiError(404, "NOT_FOUND", "Participant not found.")
    return row[0], row[1]


@router.get("")
def list_participants(trip_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> list[ParticipantOut]:
    _, role = get_trip_for_user(session, trip_id, user)
    require(can_read(role))
    rows = session.execute(
        select(User, TripParticipant.role)
        .join(TripParticipant, TripParticipant.user_id == User.id)
        .where(TripParticipant.trip_id == trip_id)
    ).all()
    # Organizer first, then by username.
    rows.sort(key=lambda r: (r[1] != ROLE_ORGANIZER, r[0].username))
    return [_out(u, r) for u, r in rows]


@router.post("", status_code=201)
def add_participant(trip_id: uuid.UUID, body: AddParticipantIn, user: CurrentUser, session: SessionDep) -> ParticipantOut:
    _, role = get_trip_for_user(session, trip_id, user)
    require(can_manage_participants(role), "Only the organizer can manage participants.")

    target = session.scalar(select(User).where(User.username == body.username.strip().lower()))
    if target is None:
        raise ApiError(400, "VALIDATION_ERROR", "Some fields are invalid.", {"fields": {"username": "No user with this username"}})
    exists = session.scalar(
        select(TripParticipant.user_id).where(TripParticipant.trip_id == trip_id, TripParticipant.user_id == target.id)
    )
    already = ApiError(409, "ALREADY_PARTICIPANT", "This user is already on the trip.")
    if exists is not None:
        raise already
    session.add(TripParticipant(trip_id=trip_id, user_id=target.id, role=body.role))
    try:
        session.commit()
    except IntegrityError:  # added concurrently by another request
        session.rollback()
        raise already
    return _out(target, body.role)


@router.put("/{user_id}")
def change_role(
    trip_id: uuid.UUID, user_id: uuid.UUID, body: ChangeRoleIn, user: CurrentUser, session: SessionDep
) -> ParticipantOut:
    _, role = get_trip_for_user(session, trip_id, user)
    require(can_manage_participants(role), "Only the organizer can manage participants.")
    member, target = _load_member(session, trip_id, user_id)
    if member.role == ROLE_ORGANIZER:
        raise ApiError(400, "ORGANIZER_PROTECTED", "The organizer's role cannot be changed.")
    member.role = body.role
    session.commit()
    return _out(target, body.role)


@router.delete("/{user_id}", status_code=204)
def remove_participant(trip_id: uuid.UUID, user_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> Response:
    _, role = get_trip_for_user(session, trip_id, user)
    require(can_manage_participants(role), "Only the organizer can manage participants.")
    member, _ = _load_member(session, trip_id, user_id)
    if member.role == ROLE_ORGANIZER:
        raise ApiError(400, "ORGANIZER_PROTECTED", "The organizer cannot be removed from the trip.")
    session.delete(member)
    session.commit()
    return Response(status_code=204)
