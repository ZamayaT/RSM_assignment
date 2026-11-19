from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_engine
from app.models import User

SEED_USERS = (
    ("alice", "Alice"),
    ("bob", "Bob"),
    ("carol", "Carol"),
    ("daniela", "Daniela"),
)


def seed_users(session: Session) -> None:
    """Create the test users that do not exist yet (so a user added later also reaches an existing database).
    Safe to run on every startup."""
    existing = set(session.scalars(select(User.username)))
    missing = [User(username=name, display_name=display) for name, display in SEED_USERS if name not in existing]
    if missing:
        session.add_all(missing)
        session.commit()


def run_seed() -> None:
    with Session(get_engine()) as session:
        seed_users(session)
