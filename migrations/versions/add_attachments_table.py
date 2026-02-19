"""add attachments table

Revision ID: add_attachments_table
Revises:
Create Date: 2026-01-23 12:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "add_attachments_table"
down_revision = "b1c2d3e4f5a6"  # Latest migration
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create attachments table
    op.create_table(
        "attachments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("lead_id", sa.Integer(), nullable=False),
        sa.Column("lead_answer_id", sa.Integer(), nullable=True),
        sa.Column("whatsapp_media_id", sa.String(length=255), nullable=True),
        sa.Column("provider", sa.String(length=50), nullable=False, server_default="supabase"),
        sa.Column("bucket", sa.String(length=100), nullable=True),
        sa.Column("object_key", sa.String(length=500), nullable=True),
        sa.Column("content_type", sa.String(length=100), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("upload_status", sa.String(length=20), nullable=False, server_default="PENDING"),
        sa.Column("upload_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_attachments_lead_id"), "attachments", ["lead_id"], unique=False)
    op.create_index(
        op.f("ix_attachments_lead_answer_id"), "attachments", ["lead_answer_id"], unique=False
    )
    op.create_index(
        op.f("ix_attachments_whatsapp_media_id"), "attachments", ["whatsapp_media_id"], unique=False
    )
    op.create_index(op.f("ix_attachments_object_key"), "attachments", ["object_key"], unique=False)
    op.create_index(
        op.f("ix_attachments_upload_status"), "attachments", ["upload_status"], unique=False
    )
    op.create_foreign_key(
        op.f("fk_attachments_lead_id_leads"), "attachments", "leads", ["lead_id"], ["id"]
    )
    op.create_foreign_key(
        op.f("fk_attachments_lead_answer_id_lead_answers"),
        "attachments",
        "lead_answers",
        ["lead_answer_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("fk_attachments_lead_answer_id_lead_answers"), "attachments", type_="foreignkey"
    )
    op.drop_constraint(op.f("fk_attachments_lead_id_leads"), "attachments", type_="foreignkey")
    op.drop_index(op.f("ix_attachments_upload_status"), table_name="attachments")
    op.drop_index(op.f("ix_attachments_object_key"), table_name="attachments")
    op.drop_index(op.f("ix_attachments_whatsapp_media_id"), table_name="attachments")
    op.drop_index(op.f("ix_attachments_lead_answer_id"), table_name="attachments")
    op.drop_index(op.f("ix_attachments_lead_id"), table_name="attachments")
    op.drop_table("attachments")
