from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import select

from app.auth import CurrentUser, UserOut, _user_out
from app.models import User
from app.trips import SessionDep

router = APIRouter(prefix="/users", tags=["users"])

MAX_RESULTS = 10


@router.get("")
def search_users(
    _: CurrentUser,
    session: SessionDep,
    query: Annotated[str, Query(min_length=1, max_length=50)],
) -> list[UserOut]:
    """Find users by username (case-insensitive, contains). Public fields only."""
    users = session.scalars(
        select(User).where(User.username.icontains(query.strip(), autoescape=True)).order_by(User.username).limit(MAX_RESULTS)
    )
    return [_user_out(u) for u in users]
