"""Add provider to processed_messages for (provider, message_id) unique constraint

Revision ID: d5e6f7a8b9c0
Revises: c2d3e4f5a6b7
Create Date: 2026-02-17 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d5e6f7a8b9c0"
down_revision: str | Sequence[str] | None = "c2d3e4f5a6b7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Add provider column with default 'whatsapp' for existing rows
    op.add_column(
        "processed_messages",
        sa.Column("provider", sa.String(length=32), nullable=False, server_default="whatsapp"),
    )
    # Drop old unique index on message_id
    op.drop_index("ix_processed_messages_message_id", table_name="processed_messages")
    # Create unique index on (provider, message_id)
    op.create_index(
        "ix_processed_messages_provider_message_id",
        "processed_messages",
        ["provider", "message_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_processed_messages_provider_message_id", table_name="processed_messages")
    op.create_index(
        "ix_processed_messages_message_id",
        "processed_messages",
        ["message_id"],
        unique=True,
    )
    op.drop_column("processed_messages", "provider")
