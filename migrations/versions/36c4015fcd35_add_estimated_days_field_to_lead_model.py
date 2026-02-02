"""Add estimated_days field to Lead model

Revision ID: 36c4015fcd35
Revises: b452f5bb9ced
Create Date: 2026-01-20 13:38:21.577539

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "36c4015fcd35"
down_revision: str | Sequence[str] | None = "b452f5bb9ced"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add estimated_days column to leads table
    op.add_column("leads", sa.Column("estimated_days", sa.Float(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    # Remove estimated_days column from leads table
    op.drop_column("leads", "estimated_days")
