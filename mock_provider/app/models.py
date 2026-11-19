from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Offer(Base):
    """Current quote of an offer. The id is stable; the quote fields change with a new revision."""

    __tablename__ = "offers"
    __table_args__ = (
        CheckConstraint("category IN ('transport', 'accommodation', 'activity')", name="ck_offers_category"),
        CheckConstraint("travelers BETWEEN 1 AND 20", name="ck_offers_travelers"),
        CheckConstraint("ends_at > starts_at", name="ck_offers_period"),
        CheckConstraint("price_amount >= 0", name="ck_offers_price"),
        Index("ix_offers_search", "category", "destination"),
        Index("ix_offers_provider_id", "provider_id"),
    )

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    provider_id: Mapped[str] = mapped_column(String(128))
    category: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text)
    destination: Mapped[str] = mapped_column(String(200))
    origin: Mapped[str | None] = mapped_column(String(200))
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    travelers: Mapped[int] = mapped_column(Integer)
    price_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    revision: Mapped[str] = mapped_column(String(64))
    available: Mapped[bool] = mapped_column(Boolean, default=True)
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    restrictions: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list, server_default="{}")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Booking(Base):
    """Accepted booking. The offer snapshot and price never change; only status and updated_at do."""

    __tablename__ = "bookings"
    __table_args__ = (
        UniqueConstraint("caller", "client_reference", name="uq_bookings_caller_reference"),
        CheckConstraint("status IN ('pending', 'confirmed', 'failed')", name="ck_bookings_status"),
        CheckConstraint(
            "(status = 'failed') = (failure_code IS NOT NULL AND failure_message IS NOT NULL)",
            name="ck_bookings_failure",
        ),
        CheckConstraint("updated_at >= created_at", name="ck_bookings_timestamps"),
        Index("ix_bookings_offer_id", "offer_id"),
    )

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    caller: Mapped[str] = mapped_column(String(128))
    client_reference: Mapped[str] = mapped_column(String(128))
    offer_id: Mapped[str] = mapped_column(ForeignKey("offers.id"))
    offer_snapshot: Mapped[dict] = mapped_column(JSONB)
    price_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    status: Mapped[str] = mapped_column(String(16))
    failure_code: Mapped[str | None] = mapped_column(String(128))
    failure_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class IdempotencyRecord(Base):
    """Remembers the booking created for a caller's Idempotency-Key and the request that created it."""

    __tablename__ = "idempotency_records"
    __table_args__ = (UniqueConstraint("caller", "idempotency_key", name="uq_idempotency_caller_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    caller: Mapped[str] = mapped_column(String(128))
    idempotency_key: Mapped[str] = mapped_column(String(255))
    request_fingerprint: Mapped[str] = mapped_column(String(64))
    booking_id: Mapped[str] = mapped_column(ForeignKey("bookings.id"), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
