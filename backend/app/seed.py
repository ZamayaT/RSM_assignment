from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_engine
from app.models import User

SEED_USERS = (
    ("alice", "Alice"),
    ("bob", "Bob"),
    ("carol", "Carol"),
)


def seed_users(session: Session) -> None:
    """Create the test users when the table is empty. Safe to run on every startup."""
    if session.scalar(select(User.id).limit(1)) is not None:
        return
    session.add_all(User(username=name, display_name=display) for name, display in SEED_USERS)
    session.commit()


def run_seed() -> None:
    with Session(get_engine()) as session:
        seed_users(session)
