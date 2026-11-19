import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

ROLE_ORGANIZER = "organizer"
ROLE_EDITOR = "editor"
ROLE_VIEWER = "viewer"
ROLES = (ROLE_ORGANIZER, ROLE_EDITOR, ROLE_VIEWER)

BOOKING_INITIATED = "initiated"
BOOKING_PENDING = "pending"
BOOKING_CONFIRMED = "confirmed"
BOOKING_FAILED = "failed"
BOOKING_UNKNOWN = "unknown"
BOOKING_STATUSES = (BOOKING_INITIATED, BOOKING_PENDING, BOOKING_CONFIRMED, BOOKING_FAILED, BOOKING_UNKNOWN)
# An attempt in one of these states blocks a new one for the same item.
BOOKING_LIVE_STATUSES = (BOOKING_INITIATED, BOOKING_PENDING, BOOKING_UNKNOWN, BOOKING_CONFIRMED)


DOCUMENT_WAITING = "waiting"
DOCUMENT_IN_PROGRESS = "in_progress"
DOCUMENT_COMPLETE = "complete"
DOCUMENT_FAILED = "failed"
DOCUMENT_STATUSES = (DOCUMENT_WAITING, DOCUMENT_IN_PROGRESS, DOCUMENT_COMPLETE, DOCUMENT_FAILED)
# A document in one of these states is "live": a trip has at most one.
DOCUMENT_LIVE_STATUSES = (DOCUMENT_WAITING, DOCUMENT_IN_PROGRESS)


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


class Document(Base):
    """A PDF summary of a trip, rendered by the worker from a frozen snapshot taken at request time."""

    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint("status IN ('waiting', 'in_progress', 'complete', 'failed')", name="ck_documents_status"),
        Index(
            "uq_documents_live_trip",
            "trip_id",
            unique=True,
            postgresql_where=text("status IN ('waiting', 'in_progress')"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    trip_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("trips.id", ondelete="CASCADE"), index=True)
    requested_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(20))
    trip_version: Mapped[int] = mapped_column(Integer)
    snapshot: Mapped[dict] = mapped_column(JSONB)
    snapshot_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    file_path: Mapped[str | None] = mapped_column(String(255))  # relative to DOCUMENTS_DIR
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    sha256: Mapped[str | None] = mapped_column(String(64))
    failure_message: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BookingAttempt(Base):
    """One booking decision for an itinerary item. Saved as `initiated` before the provider is called."""

    __tablename__ = "booking_attempts"
    __table_args__ = (
        UniqueConstraint("intent_id", name="uq_booking_attempts_intent"),
        UniqueConstraint("client_reference", name="uq_booking_attempts_reference"),
        CheckConstraint(
            "status IN ('initiated', 'pending', 'confirmed', 'failed', 'unknown')", name="ck_booking_attempts_status"
        ),
        CheckConstraint("expected_amount >= 0", name="ck_booking_attempts_amount"),
        Index(
            "uq_booking_attempts_live_item",
            "item_id",
            unique=True,
            postgresql_where=text("status IN ('initiated', 'pending', 'unknown', 'confirmed')"),
        ),
        Index(
            "ix_booking_attempts_due",
            "next_check_at",
            postgresql_where=text("status IN ('initiated', 'pending', 'unknown')"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    trip_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("trips.id", ondelete="CASCADE"), index=True)
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("itinerary_items.id", ondelete="CASCADE"), index=True)
    intent_id: Mapped[uuid.UUID] = mapped_column()
    client_reference: Mapped[str] = mapped_column(String(128))
    idempotency_key: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(20))
    # What the user confirmed (sent to the provider).
    offer_id: Mapped[str] = mapped_column(String(128))
    expected_revision: Mapped[str] = mapped_column(String(64))
    expected_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3))
    # What the provider accepted (immutable once stored).
    provider_booking_id: Mapped[str | None] = mapped_column(String(128))
    accepted_offer: Mapped[dict | None] = mapped_column(JSONB)
    accepted_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    failure_code: Mapped[str | None] = mapped_column(String(100))
    failure_message: Mapped[str | None] = mapped_column(Text)
    # Worker bookkeeping.
    check_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    next_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    unresolved: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    requested_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
