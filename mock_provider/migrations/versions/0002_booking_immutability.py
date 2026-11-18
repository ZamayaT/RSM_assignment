"""Guard bookings: the offer snapshot and total never change, and terminal outcomes never reverse.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-18
"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

SCHEMA = "mock_provider"


def upgrade() -> None:
    op.execute(
        f"""
        CREATE FUNCTION {SCHEMA}.bookings_guard() RETURNS trigger AS $$
        BEGIN
            IF NEW.id IS DISTINCT FROM OLD.id
               OR NEW.caller IS DISTINCT FROM OLD.caller
               OR NEW.client_reference IS DISTINCT FROM OLD.client_reference
               OR NEW.offer_id IS DISTINCT FROM OLD.offer_id
               OR NEW.offer_snapshot IS DISTINCT FROM OLD.offer_snapshot
               OR NEW.price_amount IS DISTINCT FROM OLD.price_amount
               OR NEW.currency IS DISTINCT FROM OLD.currency
               OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
                RAISE EXCEPTION 'the accepted offer, total and identity of a booking are immutable';
            END IF;
            IF OLD.status IN ('confirmed', 'failed')
               AND (NEW.status IS DISTINCT FROM OLD.status
                    OR NEW.failure_code IS DISTINCT FROM OLD.failure_code
                    OR NEW.failure_message IS DISTINCT FROM OLD.failure_message
                    OR NEW.updated_at IS DISTINCT FROM OLD.updated_at) THEN
                RAISE EXCEPTION 'a terminal booking outcome never changes';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER bookings_guard BEFORE UPDATE ON {SCHEMA}.bookings
        FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.bookings_guard()
        """
    )


def downgrade() -> None:
    op.execute(f"DROP TRIGGER bookings_guard ON {SCHEMA}.bookings")
    op.execute(f"DROP FUNCTION {SCHEMA}.bookings_guard()")
