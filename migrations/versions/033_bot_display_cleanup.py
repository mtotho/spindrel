"""Bot display name cleanup + drop dead SlackChannelConfig table.

- Rename Bot.slack_display_name → display_name
- Rename Bot.slack_icon_url    → avatar_url
- Drop  Bot.slack_icon_emoji   (Slack-specific, not generic)
- Drop  slack_channel_configs  table (replaced by integration_channel_configs)

Revision ID: 033
Revises: 032
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "033"
down_revision = "032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Rename display columns on bots
    op.alter_column("bots", "slack_display_name", new_column_name="display_name")
    op.alter_column("bots", "slack_icon_url", new_column_name="avatar_url")

    # 2. Drop Slack-specific emoji column
    op.drop_column("bots", "slack_icon_emoji")

    # 3. Drop dead SlackChannelConfig table (replaced by integration_channel_configs)
    op.drop_table("slack_channel_configs")


def downgrade() -> None:
    # Recreate slack_channel_configs
    op.create_table(
        "slack_channel_configs",
        sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True),
        sa.Column("channel_id", sa.Text(), nullable=False, unique=True),
        sa.Column("bot_id", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
    )

    # Restore emoji column
    op.add_column("bots", sa.Column("slack_icon_emoji", sa.Text(), nullable=True))

    # Rename back
    op.alter_column("bots", "display_name", new_column_name="slack_display_name")
    op.alter_column("bots", "avatar_url", new_column_name="slack_icon_url")
