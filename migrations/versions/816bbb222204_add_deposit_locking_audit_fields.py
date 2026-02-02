"""Add deposit locking audit fields

Revision ID: 816bbb222204
Revises: 7d8d633017cd
Create Date: 2026-01-20 13:45:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "816bbb222204"
down_revision: str | Sequence[str] | None = "7d8d633017cd"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add deposit locking audit fields to leads table
    op.add_column(
        "leads",
        sa.Column("deposit_amount_locked_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
    )
    op.add_column("leads", sa.Column("deposit_rule_version", sa.String(length=20), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    # Remove deposit locking audit fields from leads table
    op.drop_column("leads", "deposit_rule_version")
    op.drop_column("leads", "deposit_amount_locked_at")
