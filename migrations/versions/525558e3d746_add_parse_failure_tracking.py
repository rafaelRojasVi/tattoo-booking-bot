"""add_parse_failure_tracking

Revision ID: 525558e3d746
Revises: 816bbb222204
Create Date: 2026-01-20 14:16:34.424850

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "525558e3d746"
down_revision: str | Sequence[str] | None = "816bbb222204"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add parse_failure_counts JSON field to leads table
    op.add_column("leads", sa.Column("parse_failure_counts", postgresql.JSON, nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    # Remove parse_failure_counts field from leads table
    op.drop_column("leads", "parse_failure_counts")
