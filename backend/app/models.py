import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

ROLE_ORGANIZER = "organizer"
ROLE_EDITOR = "editor"
ROLE_VIEWER = "viewer"
ROLES = (ROLE_ORGANIZER, ROLE_EDITOR, ROLE_VIEWER)


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(String(50), unique=True)
    display_name: Mapped[str] = mapped_column(String(100))


class AuthToken(Base):
    __tablename__ = "auth_tokens"

    token: Mapped[str] = mapped_column(String(100), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Trip(Base):
    __tablename__ = "trips"
    __table_args__ = (
        CheckConstraint("end_date >= start_date", name="ck_trips_dates"),
        CheckConstraint("travelers BETWEEN 1 AND 20", name="ck_trips_travelers"),
        CheckConstraint("budget >= 0", name="ck_trips_budget"),
        CheckConstraint("version >= 1", name="ck_trips_version"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(120))
    destinations: Mapped[list[str]] = mapped_column(ARRAY(String(50)))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    travelers: Mapped[int] = mapped_column(Integer)
    budget: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    notes: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ItineraryItem(Base):
    """An offer copied into a trip's itinerary. The snapshot never changes when the provider's data does."""

    __tablename__ = "itinerary_items"
    __table_args__ = (
        UniqueConstraint("trip_id", "offer_id", name="uq_itinerary_items_trip_offer"),
        CheckConstraint("category IN ('transport', 'accommodation', 'activity')", name="ck_itinerary_items_category"),
        CheckConstraint("price_amount IS NULL OR price_amount >= 0", name="ck_itinerary_items_price"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    trip_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("trips.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    # Offer snapshot (as the provider returned it when the item was added).
    offer_id: Mapped[str] = mapped_column(String(128))
    provider_id: Mapped[str] = mapped_column(String(128))
    category: Mapped[str] = mapped_column(String(20))
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text)
    destination: Mapped[str] = mapped_column(String(200))
    origin: Mapped[str | None] = mapped_column(String(200))
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    travelers: Mapped[int] = mapped_column(Integer)
    price_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3), default="USD", server_default="USD")
    revision: Mapped[str] = mapped_column(String(64))
    available: Mapped[bool] = mapped_column(Boolean)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    added_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TripParticipant(Base):
    __tablename__ = "trip_participants"
    __table_args__ = (
        CheckConstraint("role IN ('organizer', 'editor', 'viewer')", name="ck_trip_participants_role"),
    )

    trip_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("trips.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True)
    role: Mapped[str] = mapped_column(String(20))
