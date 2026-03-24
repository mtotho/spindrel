"""Add private and user_id to channels for ownership/visibility.

Revision ID: 063
Revises: 062
Create Date: 2026-03-24
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "063"
down_revision = "062"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "channels",
        sa.Column("private", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "channels",
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_channels_user_id", "channels", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_channels_user_id", table_name="channels")
    op.drop_column("channels", "user_id")
    op.drop_column("channels", "private")
