"""Add notification timestamp fields

Revision ID: add_notification_timestamps
Revises: f4a5b6c7d8e9
Create Date: 2026-01-19 16:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "add_notification_timestamps"
down_revision: str | Sequence[str] | None = "f4a5b6c7d8e9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add notification timestamp fields to prevent duplicate notifications."""
    op.add_column(
        "leads", sa.Column("needs_follow_up_notified_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "leads",
        sa.Column("needs_artist_reply_notified_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    """Remove notification timestamp fields."""
    op.drop_column("leads", "needs_artist_reply_notified_at")
    op.drop_column("leads", "needs_follow_up_notified_at")
