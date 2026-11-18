"""booking attempts

Revision ID: 0003
Revises: 0002
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

LIVE = "status IN ('initiated', 'pending', 'unknown', 'confirmed')"


def upgrade() -> None:
    op.create_table(
        "booking_attempts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("trip_id", sa.Uuid(), sa.ForeignKey("trips.id", ondelete="CASCADE"), nullable=False),
        sa.Column("item_id", sa.Uuid(), sa.ForeignKey("itinerary_items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("intent_id", sa.Uuid(), nullable=False),
        sa.Column("client_reference", sa.String(128), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("offer_id", sa.String(128), nullable=False),
        sa.Column("expected_revision", sa.String(64), nullable=False),
        sa.Column("expected_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("provider_booking_id", sa.String(128), nullable=True),
        sa.Column("accepted_offer", postgresql.JSONB(), nullable=True),
        sa.Column("accepted_amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("failure_code", sa.String(100), nullable=True),
        sa.Column("failure_message", sa.Text(), nullable=True),
        sa.Column("check_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("next_check_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("unresolved", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("requested_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("intent_id", name="uq_booking_attempts_intent"),
        sa.UniqueConstraint("client_reference", name="uq_booking_attempts_reference"),
        sa.CheckConstraint(
            "status IN ('initiated', 'pending', 'confirmed', 'failed', 'unknown')", name="ck_booking_attempts_status"
        ),
        sa.CheckConstraint("expected_amount >= 0", name="ck_booking_attempts_amount"),
    )
    op.create_index("ix_booking_attempts_trip_id", "booking_attempts", ["trip_id"])
    op.create_index("ix_booking_attempts_item_id", "booking_attempts", ["item_id"])
    op.create_index(
        "uq_booking_attempts_live_item",
        "booking_attempts",
        ["item_id"],
        unique=True,
        postgresql_where=sa.text(LIVE),
    )
    op.create_index(
        "ix_booking_attempts_due",
        "booking_attempts",
        ["next_check_at"],
        postgresql_where=sa.text("status IN ('initiated', 'pending', 'unknown')"),
    )


def downgrade() -> None:
    op.drop_table("booking_attempts")
