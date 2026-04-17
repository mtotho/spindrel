"""Add tool_output_display column to channels.

Controls how tool-call results render in chat integrations (Slack etc.).
Values: compact (one-line badge, default) | full (rich Block Kit) | none.

Revision ID: 200
Revises: 199
"""
from alembic import op
import sqlalchemy as sa

revision = "200"
down_revision = "199"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "channels",
        sa.Column(
            "tool_output_display",
            sa.Text(),
            server_default="compact",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("channels", "tool_output_display")
