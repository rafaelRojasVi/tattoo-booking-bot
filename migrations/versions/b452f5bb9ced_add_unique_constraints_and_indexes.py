"""add_unique_constraints_and_indexes

Revision ID: b452f5bb9ced
Revises: add_notification_timestamps
Create Date: 2026-01-18 18:37:26.354000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b452f5bb9ced"
down_revision: str | Sequence[str] | None = "add_notification_timestamps"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """
    Add unique constraints on Stripe IDs and indexes on query-hot fields.

    This migration:
    1. Checks for duplicate Stripe IDs (raises error if found)
    2. Adds unique constraints on stripe_payment_intent_id and stripe_checkout_session_id
    3. Adds indexes on status, created_at, and last_client_message_at
    """
    # Check for duplicates before adding constraints
    # This will raise an error if duplicates exist, preventing migration failure
    conn = op.get_bind()

    # Check for duplicate payment intent IDs
    result = conn.execute(
        sa.text("""
        SELECT stripe_payment_intent_id, COUNT(*) as cnt
        FROM leads
        WHERE stripe_payment_intent_id IS NOT NULL
        GROUP BY stripe_payment_intent_id
        HAVING COUNT(*) > 1
    """)
    )
    duplicates = result.fetchall()
    if duplicates:
        raise ValueError(
            f"Found {len(duplicates)} duplicate stripe_payment_intent_id values. "
            "Please remove duplicates before running this migration."
        )

    # Check for duplicate checkout session IDs
    result = conn.execute(
        sa.text("""
        SELECT stripe_checkout_session_id, COUNT(*) as cnt
        FROM leads
        WHERE stripe_checkout_session_id IS NOT NULL
        GROUP BY stripe_checkout_session_id
        HAVING COUNT(*) > 1
    """)
    )
    duplicates = result.fetchall()
    if duplicates:
        raise ValueError(
            f"Found {len(duplicates)} duplicate stripe_checkout_session_id values. "
            "Please remove duplicates before running this migration."
        )

    # Add unique constraints (nullable columns - multiple NULLs are allowed)
    op.create_unique_constraint(
        "uq_leads_stripe_payment_intent_id", "leads", ["stripe_payment_intent_id"]
    )

    op.create_unique_constraint(
        "uq_leads_stripe_checkout_session_id", "leads", ["stripe_checkout_session_id"]
    )

    # Add indexes on query-hot fields
    # Note: SQLite doesn't support IF NOT EXISTS, but these indexes shouldn't exist yet
    op.create_index("ix_leads_status", "leads", ["status"])

    op.create_index("ix_leads_created_at", "leads", ["created_at"])

    op.create_index("ix_leads_last_client_message_at", "leads", ["last_client_message_at"])


def downgrade() -> None:
    """Remove unique constraints and indexes."""
    # Drop indexes
    op.drop_index("ix_leads_last_client_message_at", table_name="leads")
    op.drop_index("ix_leads_created_at", table_name="leads")
    op.drop_index("ix_leads_status", table_name="leads")

    # Drop unique constraints
    op.drop_constraint("uq_leads_stripe_checkout_session_id", "leads", type_="unique")
    op.drop_constraint("uq_leads_stripe_payment_intent_id", "leads", type_="unique")
