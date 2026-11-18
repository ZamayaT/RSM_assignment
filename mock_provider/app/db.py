from functools import lru_cache

from sqlalchemy import Engine, MetaData, create_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings

# Fixed per process by the environment.
SCHEMA = get_settings().mock_db_schema


class Base(DeclarativeBase):
    """Base class for all ORM models; every table lives in the mock schema."""

    metadata = MetaData(schema=SCHEMA)


@lru_cache
def get_engine() -> Engine:
    return create_engine(
        get_settings().database_url,
        pool_pre_ping=True,
        connect_args={"connect_timeout": 3},
    )
