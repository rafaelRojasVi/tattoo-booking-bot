"""Add proposal v1.4 fields to leads and create processed_messages table

Revision ID: a1b2c3d4e5f6
Revises: eef03f799c01
Create Date: 2026-01-19 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: str | Sequence[str] | None = "eef03f799c01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add location fields
    op.add_column("leads", sa.Column("location_city", sa.String(length=100), nullable=True))
    op.add_column("leads", sa.Column("location_country", sa.String(length=100), nullable=True))
    op.add_column("leads", sa.Column("region_bucket", sa.String(length=20), nullable=True))

    # Add size and budget fields
    op.add_column("leads", sa.Column("size_category", sa.String(length=20), nullable=True))
    op.add_column("leads", sa.Column("size_measurement", sa.String(length=100), nullable=True))
    op.add_column("leads", sa.Column("budget_range_text", sa.String(length=100), nullable=True))

    # Add summary field
    op.add_column("leads", sa.Column("summary_text", sa.Text(), nullable=True))

    # Add deposit fields
    op.add_column("leads", sa.Column("deposit_amount_pence", sa.Integer(), nullable=True))
    op.add_column(
        "leads", sa.Column("stripe_checkout_session_id", sa.String(length=255), nullable=True)
    )
    op.add_column(
        "leads", sa.Column("stripe_payment_intent_id", sa.String(length=255), nullable=True)
    )
    op.add_column("leads", sa.Column("stripe_payment_status", sa.String(length=50), nullable=True))
    op.add_column("leads", sa.Column("deposit_paid_at", sa.DateTime(timezone=True), nullable=True))

    # Add booking fields
    op.add_column("leads", sa.Column("booking_link", sa.String(length=500), nullable=True))
    op.add_column("leads", sa.Column("booking_tool", sa.String(length=50), nullable=True))
    op.add_column(
        "leads", sa.Column("booking_link_sent_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("leads", sa.Column("booked_at", sa.DateTime(timezone=True), nullable=True))

    # Add timestamp fields for reminders and tracking
    op.add_column(
        "leads", sa.Column("last_client_message_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "leads", sa.Column("last_bot_message_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "leads", sa.Column("reminder_qualifying_sent_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "leads",
        sa.Column("reminder_booking_sent_24h_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "leads",
        sa.Column("reminder_booking_sent_72h_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("leads", sa.Column("stale_marked_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "leads", sa.Column("abandoned_marked_at", sa.DateTime(timezone=True), nullable=True)
    )

    # Add admin fields
    op.add_column("leads", sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("leads", sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("leads", sa.Column("last_admin_action", sa.String(length=100), nullable=True))
    op.add_column(
        "leads", sa.Column("last_admin_action_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("leads", sa.Column("admin_notes", sa.Text(), nullable=True))

    # Add media fields to lead_answers
    op.add_column("lead_answers", sa.Column("message_id", sa.String(length=255), nullable=True))
    op.add_column("lead_answers", sa.Column("media_id", sa.String(length=255), nullable=True))
    op.add_column("lead_answers", sa.Column("media_url", sa.String(length=500), nullable=True))

    # Create processed_messages table for idempotency
    op.create_table(
        "processed_messages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("message_id", sa.String(length=255), nullable=False),
        sa.Column("lead_id", sa.Integer(), nullable=True),
        sa.Column(
            "processed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["lead_id"],
            ["leads.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_processed_messages_message_id"), "processed_messages", ["message_id"], unique=True
    )
    op.create_index(
        op.f("ix_processed_messages_lead_id"), "processed_messages", ["lead_id"], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    # Drop processed_messages table
    op.drop_index(op.f("ix_processed_messages_lead_id"), table_name="processed_messages")
    op.drop_index(op.f("ix_processed_messages_message_id"), table_name="processed_messages")
    op.drop_table("processed_messages")

    # Remove media fields from lead_answers
    op.drop_column("lead_answers", "media_url")
    op.drop_column("lead_answers", "media_id")
    op.drop_column("lead_answers", "message_id")

    # Remove admin fields
    op.drop_column("leads", "admin_notes")
    op.drop_column("leads", "last_admin_action_at")
    op.drop_column("leads", "last_admin_action")
    op.drop_column("leads", "rejected_at")
    op.drop_column("leads", "approved_at")

    # Remove timestamp fields
    op.drop_column("leads", "abandoned_marked_at")
    op.drop_column("leads", "stale_marked_at")
    op.drop_column("leads", "reminder_booking_sent_72h_at")
    op.drop_column("leads", "reminder_booking_sent_24h_at")
    op.drop_column("leads", "reminder_qualifying_sent_at")
    op.drop_column("leads", "last_bot_message_at")
    op.drop_column("leads", "last_client_message_at")

    # Remove booking fields
    op.drop_column("leads", "booked_at")
    op.drop_column("leads", "booking_link_sent_at")
    op.drop_column("leads", "booking_tool")
    op.drop_column("leads", "booking_link")

    # Remove deposit fields
    op.drop_column("leads", "deposit_paid_at")
    op.drop_column("leads", "stripe_payment_status")
    op.drop_column("leads", "stripe_payment_intent_id")
    op.drop_column("leads", "stripe_checkout_session_id")
    op.drop_column("leads", "deposit_amount_pence")

    # Remove summary field
    op.drop_column("leads", "summary_text")

    # Remove size and budget fields
    op.drop_column("leads", "budget_range_text")
    op.drop_column("leads", "size_measurement")
    op.drop_column("leads", "size_category")

    # Remove location fields
    op.drop_column("leads", "region_bucket")
    op.drop_column("leads", "location_country")
    op.drop_column("leads", "location_city")
