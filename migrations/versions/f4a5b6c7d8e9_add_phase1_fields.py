"""Add Phase 1 fields to leads table

Revision ID: f4a5b6c7d8e9
Revises: a1b2c3d4e5f6
Create Date: 2026-01-19 15:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f4a5b6c7d8e9"
down_revision: str | Sequence[str] | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema - add Phase 1 fields."""

    # Tour fields (Phase 1)
    op.add_column("leads", sa.Column("requested_city", sa.String(length=100), nullable=True))
    op.add_column("leads", sa.Column("requested_country", sa.String(length=100), nullable=True))
    op.add_column("leads", sa.Column("offered_tour_city", sa.String(length=100), nullable=True))
    op.add_column(
        "leads", sa.Column("offered_tour_dates_text", sa.String(length=200), nullable=True)
    )
    op.add_column("leads", sa.Column("tour_offer_accepted", sa.Boolean(), nullable=True))
    op.add_column(
        "leads", sa.Column("waitlisted", sa.Boolean(), nullable=True, server_default="false")
    )

    # Estimation fields (Phase 1)
    op.add_column("leads", sa.Column("complexity_level", sa.Integer(), nullable=True))
    op.add_column("leads", sa.Column("estimated_category", sa.String(length=20), nullable=True))
    op.add_column("leads", sa.Column("estimated_deposit_amount", sa.Integer(), nullable=True))
    op.add_column("leads", sa.Column("min_budget_amount", sa.Integer(), nullable=True))
    op.add_column(
        "leads", sa.Column("below_min_budget", sa.Boolean(), nullable=True, server_default="false")
    )

    # Instagram handle (Phase 1)
    op.add_column("leads", sa.Column("instagram_handle", sa.String(length=100), nullable=True))

    # Calendar fields (Phase 1 - optional detection)
    op.add_column("leads", sa.Column("calendar_event_id", sa.String(length=255), nullable=True))
    op.add_column(
        "leads", sa.Column("calendar_start_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("leads", sa.Column("calendar_end_at", sa.DateTime(timezone=True), nullable=True))

    # Handover fields (Phase 1)
    op.add_column("leads", sa.Column("handover_reason", sa.String(length=200), nullable=True))
    op.add_column(
        "leads", sa.Column("preferred_handover_channel", sa.String(length=20), nullable=True)
    )
    op.add_column("leads", sa.Column("call_availability_notes", sa.Text(), nullable=True))

    # Phase 1 funnel timestamps
    op.add_column(
        "leads", sa.Column("qualifying_started_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "leads", sa.Column("qualifying_completed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "leads", sa.Column("pending_approval_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "leads", sa.Column("needs_follow_up_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "leads", sa.Column("needs_artist_reply_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("leads", sa.Column("stale_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("leads", sa.Column("abandoned_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "leads", sa.Column("booking_pending_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("leads", sa.Column("deposit_sent_at", sa.DateTime(timezone=True), nullable=True))

    # Add event_type to processed_messages (for LeadEvent-like tracking)
    op.add_column(
        "processed_messages", sa.Column("event_type", sa.String(length=100), nullable=True)
    )


def downgrade() -> None:
    """Downgrade schema - remove Phase 1 fields."""

    # Remove event_type from processed_messages
    op.drop_column("processed_messages", "event_type")

    # Remove Phase 1 funnel timestamps
    op.drop_column("leads", "deposit_sent_at")
    op.drop_column("leads", "booking_pending_at")
    op.drop_column("leads", "abandoned_at")
    op.drop_column("leads", "stale_at")
    op.drop_column("leads", "needs_artist_reply_at")
    op.drop_column("leads", "needs_follow_up_at")
    op.drop_column("leads", "pending_approval_at")
    op.drop_column("leads", "qualifying_completed_at")
    op.drop_column("leads", "qualifying_started_at")

    # Remove handover fields
    op.drop_column("leads", "call_availability_notes")
    op.drop_column("leads", "preferred_handover_channel")
    op.drop_column("leads", "handover_reason")

    # Remove calendar fields
    op.drop_column("leads", "calendar_end_at")
    op.drop_column("leads", "calendar_start_at")
    op.drop_column("leads", "calendar_event_id")

    # Remove Instagram handle
    op.drop_column("leads", "instagram_handle")

    # Remove estimation fields
    op.drop_column("leads", "below_min_budget")
    op.drop_column("leads", "min_budget_amount")
    op.drop_column("leads", "estimated_deposit_amount")
    op.drop_column("leads", "estimated_category")
    op.drop_column("leads", "complexity_level")

    # Remove tour fields
    op.drop_column("leads", "waitlisted")
    op.drop_column("leads", "tour_offer_accepted")
    op.drop_column("leads", "offered_tour_dates_text")
    op.drop_column("leads", "offered_tour_city")
    op.drop_column("leads", "requested_country")
    op.drop_column("leads", "requested_city")
