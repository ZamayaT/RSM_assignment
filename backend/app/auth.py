import secrets
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.errors import ApiError
from app.models import AuthToken, User

router = APIRouter(prefix="/auth", tags=["auth"])
bearer = HTTPBearer(auto_error=False)


class UserOut(BaseModel):
    id: str
    username: str
    displayName: str


class LoginIn(BaseModel):
    username: str


class LoginOut(BaseModel):
    token: str
    user: UserOut


def _user_out(user: User) -> UserOut:
    return UserOut(id=str(user.id), username=user.username, displayName=user.display_name)


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    session: Annotated[Session, Depends(get_session)],
) -> User:
    """401 when the bearer token is missing or unknown."""
    if credentials is not None:
        user = session.scalar(
            select(User).join(AuthToken, AuthToken.user_id == User.id).where(AuthToken.token == credentials.credentials)
        )
        if user is not None:
            return user
    raise ApiError(401, "UNAUTHORIZED", "Missing or invalid authentication token.")


CurrentUser = Annotated[User, Depends(get_current_user)]


@router.get("/users")
def list_users(session: Annotated[Session, Depends(get_session)]) -> list[UserOut]:
    """Public list used by the user-selection page."""
    return [_user_out(u) for u in session.scalars(select(User).order_by(User.username))]


@router.post("/login")
def login(body: LoginIn, session: Annotated[Session, Depends(get_session)]) -> LoginOut:
    user = session.scalar(select(User).where(User.username == body.username.strip().lower()))
    if user is None:
        raise ApiError(401, "UNAUTHORIZED", "Unknown user.")
    token = secrets.token_urlsafe(32)
    session.add(AuthToken(token=token, user_id=user.id))
    session.commit()
    return LoginOut(token=token, user=_user_out(user))


@router.get("/me")
def me(user: CurrentUser) -> UserOut:
    return _user_out(user)
