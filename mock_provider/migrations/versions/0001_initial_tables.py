"""Initial tables: offers, bookings, idempotency records.

Revision ID: 0001
Revises:
Create Date: 2026-11-18
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

SCHEMA = "mock_provider"


def upgrade() -> None:
    op.execute(f'CREATE SCHEMA IF NOT EXISTS "{SCHEMA}"')

    op.create_table(
        "offers",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("provider_id", sa.String(128), nullable=False),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("destination", sa.String(200), nullable=False),
        sa.Column("origin", sa.String(200)),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("travelers", sa.Integer, nullable=False),
        sa.Column("price_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("revision", sa.String(64), nullable=False),
        sa.Column("available", sa.Boolean, nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("category IN ('transport', 'accommodation', 'activity')", name="ck_offers_category"),
        sa.CheckConstraint("travelers BETWEEN 1 AND 20", name="ck_offers_travelers"),
        sa.CheckConstraint("ends_at > starts_at", name="ck_offers_period"),
        sa.CheckConstraint("price_amount >= 0", name="ck_offers_price"),
        schema=SCHEMA,
    )
    op.create_index("ix_offers_search", "offers", ["category", "destination"], schema=SCHEMA)
    op.create_index("ix_offers_provider_id", "offers", ["provider_id"], schema=SCHEMA)

    op.create_table(
        "bookings",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("caller", sa.String(128), nullable=False),
        sa.Column("client_reference", sa.String(128), nullable=False),
        sa.Column("offer_id", sa.String(128), sa.ForeignKey(f"{SCHEMA}.offers.id"), nullable=False),
        sa.Column("offer_snapshot", postgresql.JSONB, nullable=False),
        sa.Column("price_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("failure_code", sa.String(128)),
        sa.Column("failure_message", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("caller", "client_reference", name="uq_bookings_caller_reference"),
        sa.CheckConstraint("status IN ('pending', 'confirmed', 'failed')", name="ck_bookings_status"),
        sa.CheckConstraint(
            "(status = 'failed') = (failure_code IS NOT NULL AND failure_message IS NOT NULL)",
            name="ck_bookings_failure",
        ),
        sa.CheckConstraint("updated_at >= created_at", name="ck_bookings_timestamps"),
        schema=SCHEMA,
    )
    op.create_index("ix_bookings_offer_id", "bookings", ["offer_id"], schema=SCHEMA)

    op.create_table(
        "idempotency_records",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("caller", sa.String(128), nullable=False),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("booking_id", sa.String(128), sa.ForeignKey(f"{SCHEMA}.bookings.id"), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("caller", "idempotency_key", name="uq_idempotency_caller_key"),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_table("idempotency_records", schema=SCHEMA)
    op.drop_table("bookings", schema=SCHEMA)
    op.drop_table("offers", schema=SCHEMA)
