"""add_system_events_table

Revision ID: a1b2c3d4e5f7
Revises: 3e184303342b
Create Date: 2026-01-21 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f7"
down_revision: str | Sequence[str] | None = "3e184303342b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "system_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("level", sa.String(length=10), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("lead_id", sa.Integer(), nullable=True),
        sa.Column("payload", postgresql.JSON, nullable=True),
        sa.ForeignKeyConstraint(
            ["lead_id"],
            ["leads.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_system_events_created_at"), "system_events", ["created_at"], unique=False
    )
    op.create_index(op.f("ix_system_events_level"), "system_events", ["level"], unique=False)
    op.create_index(
        op.f("ix_system_events_event_type"), "system_events", ["event_type"], unique=False
    )
    op.create_index(op.f("ix_system_events_lead_id"), "system_events", ["lead_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_system_events_lead_id"), table_name="system_events")
    op.drop_index(op.f("ix_system_events_event_type"), table_name="system_events")
    op.drop_index(op.f("ix_system_events_level"), table_name="system_events")
    op.drop_index(op.f("ix_system_events_created_at"), table_name="system_events")
    op.drop_table("system_events")
