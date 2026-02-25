"""Add artist_id to leads (multi-artist seam)

Revision ID: add_artist_id
Revises: d5e6f7a8b9c0
Create Date: 2026-02-19

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "add_artist_id"
down_revision: str | Sequence[str] | None = "d5e6f7a8b9c0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "leads",
        sa.Column("artist_id", sa.String(length=64), nullable=True),
    )
    op.execute("UPDATE leads SET artist_id = 'default' WHERE artist_id IS NULL")
    op.alter_column(
        "leads",
        "artist_id",
        existing_type=sa.String(length=64),
        nullable=False,
        server_default=sa.text("'default'"),
    )


def downgrade() -> None:
    op.drop_column("leads", "artist_id")
