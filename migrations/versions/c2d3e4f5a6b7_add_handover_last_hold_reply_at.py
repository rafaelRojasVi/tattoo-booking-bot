"""Add handover_last_hold_reply_at for rate-limiting holding message

Revision ID: c2d3e4f5a6b7
Revises: add_attachments_table
Create Date: 2026-01-29 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c2d3e4f5a6b7"
down_revision: str | Sequence[str] | None = "add_attachments_table"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "leads",
        sa.Column("handover_last_hold_reply_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("leads", "handover_last_hold_reply_at")
