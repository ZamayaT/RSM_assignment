"""itinerary item restrictions

Revision ID: 0005
Revises: 0004
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Items saved before this change have no recorded restrictions: an empty list (they are filled on refresh).
    op.add_column(
        "itinerary_items",
        sa.Column("restrictions", postgresql.ARRAY(sa.Text()), server_default="{}", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("itinerary_items", "restrictions")
