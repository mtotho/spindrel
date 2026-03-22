"""Add channel_heartbeats table for periodic heartbeat prompts.

Revision ID: 046
Revises: 045
"""
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "046"
down_revision: Union[str, None] = "045"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.create_table(
        "channel_heartbeats",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("channel_id", sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey("channels.id", ondelete="CASCADE"), unique=True, nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("interval_minutes", sa.Integer(), nullable=False, server_default=sa.text("60")),
        sa.Column("model", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("model_provider_id", sa.Text(), nullable=True),
        sa.Column("prompt", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("dispatch_results", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("trigger_response", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("last_run_at", sa.dialects.postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("next_run_at", sa.dialects.postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", sa.dialects.postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.dialects.postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index(
        "ix_channel_heartbeats_enabled_next",
        "channel_heartbeats",
        ["enabled", "next_run_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_channel_heartbeats_enabled_next", table_name="channel_heartbeats")
    op.drop_table("channel_heartbeats")
