"""Offer restrictions (the contract's optional `Offer.restrictions`).

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-19
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

SCHEMA = "mock_provider"


def upgrade() -> None:
    op.add_column(
        "offers",
        sa.Column("restrictions", postgresql.ARRAY(sa.Text()), server_default="{}", nullable=False),
        schema=SCHEMA,
    )
    # Offers loaded before this change get the same restrictions a fresh catalogue gives them.
    from app.fixtures import restrictions_for

    connection = op.get_bind()
    rows = connection.execute(sa.text(f"SELECT id, category FROM {SCHEMA}.offers")).all()
    for offer_id, category in rows:
        connection.execute(
            sa.text(f"UPDATE {SCHEMA}.offers SET restrictions = :r WHERE id = :i"),
            {"r": restrictions_for(offer_id, category), "i": offer_id},
        )


def downgrade() -> None:
    op.drop_column("offers", "restrictions", schema=SCHEMA)
