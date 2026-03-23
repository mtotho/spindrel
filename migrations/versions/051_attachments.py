"""Add attachments table.

Revision ID: 051
Revises: 050
"""
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "051"
down_revision: Union[str, None] = "050"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "attachments",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("message_id", UUID(as_uuid=True),
                  sa.ForeignKey("messages.id", ondelete="CASCADE"), nullable=False),
        sa.Column("channel_id", UUID(as_uuid=True),
                  sa.ForeignKey("channels.id", ondelete="SET NULL"), nullable=True),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("mime_type", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("posted_by", sa.Text(), nullable=True),
        sa.Column("source_integration", sa.Text(), nullable=False,
                  server_default="web"),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("description_model", sa.Text(), nullable=True),
        sa.Column("described_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
    )
    op.create_index("ix_attachments_message_type", "attachments",
                    ["message_id", "type"])
    op.create_index("ix_attachments_channel_type", "attachments",
                    ["channel_id", "type"])
    op.create_index(
        "ix_attachments_unsummarized", "attachments",
        ["type", "described_at"],
        postgresql_where=sa.text(
            "described_at IS NULL AND type IN ('image', 'text', 'file')"
        ),
    )


def downgrade() -> None:
    op.drop_index("ix_attachments_unsummarized", "attachments")
    op.drop_index("ix_attachments_channel_type", "attachments")
    op.drop_index("ix_attachments_message_type", "attachments")
    op.drop_table("attachments")
