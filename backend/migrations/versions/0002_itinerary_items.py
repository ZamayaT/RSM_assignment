"""itinerary items

Revision ID: 0002
Revises: 0001
"""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "itinerary_items",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("trip_id", sa.Uuid(), sa.ForeignKey("trips.id", ondelete="CASCADE"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("offer_id", sa.String(128), nullable=False),
        sa.Column("provider_id", sa.String(128), nullable=False),
        sa.Column("category", sa.String(20), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("destination", sa.String(200), nullable=False),
        sa.Column("origin", sa.String(200), nullable=True),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("travelers", sa.Integer(), nullable=False),
        sa.Column("price_amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("currency", sa.String(3), server_default="USD", nullable=False),
        sa.Column("revision", sa.String(64), nullable=False),
        sa.Column("available", sa.Boolean(), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("added_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("added_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("trip_id", "offer_id", name="uq_itinerary_items_trip_offer"),
        sa.CheckConstraint(
            "category IN ('transport', 'accommodation', 'activity')", name="ck_itinerary_items_category"
        ),
        sa.CheckConstraint("price_amount IS NULL OR price_amount >= 0", name="ck_itinerary_items_price"),
    )
    op.create_index("ix_itinerary_items_trip_id", "itinerary_items", ["trip_id"])


def downgrade() -> None:
    op.drop_table("itinerary_items")
