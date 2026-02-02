"""Add pricing estimate fields to Lead model

Revision ID: 7d8d633017cd
Revises: 36c4015fcd35
Create Date: 2026-01-20 13:40:31.498502

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "7d8d633017cd"
down_revision: str | Sequence[str] | None = "36c4015fcd35"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add pricing estimate fields to leads table
    op.add_column("leads", sa.Column("estimated_price_min_pence", sa.Integer(), nullable=True))
    op.add_column("leads", sa.Column("estimated_price_max_pence", sa.Integer(), nullable=True))
    op.add_column(
        "leads",
        sa.Column("pricing_trace_json", postgresql.JSON(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    # Remove pricing estimate fields from leads table
    op.drop_column("leads", "pricing_trace_json")
    op.drop_column("leads", "estimated_price_max_pence")
    op.drop_column("leads", "estimated_price_min_pence")
