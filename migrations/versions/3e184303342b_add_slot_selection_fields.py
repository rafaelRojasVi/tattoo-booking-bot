"""add_slot_selection_fields

Revision ID: 3e184303342b
Revises: 525558e3d746
Create Date: 2026-01-20 14:49:59.021797

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "3e184303342b"
down_revision: str | Sequence[str] | None = "525558e3d746"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add slot selection fields to leads table
    op.add_column("leads", sa.Column("suggested_slots_json", postgresql.JSON, nullable=True))
    op.add_column(
        "leads",
        sa.Column("selected_slot_start_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
    )
    op.add_column(
        "leads",
        sa.Column("selected_slot_end_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    # Remove slot selection fields from leads table
    op.drop_column("leads", "selected_slot_end_at")
    op.drop_column("leads", "selected_slot_start_at")
    op.drop_column("leads", "suggested_slots_json")
