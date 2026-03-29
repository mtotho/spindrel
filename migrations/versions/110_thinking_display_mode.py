"""Add thinking_display column to channels.

Revision ID: 110
Revises: 109
"""
from alembic import op
import sqlalchemy as sa

revision = "110"
down_revision = "109"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "channels",
        sa.Column("thinking_display", sa.Text(), server_default="append", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("channels", "thinking_display")
