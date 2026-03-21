"""Add sessions.locked, messages.metadata, integration_channel_configs.

Revision ID: 030
Revises: 029
"""
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "030"
down_revision: Union[str, None] = "029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # sessions.locked
    op.add_column(
        "sessions",
        sa.Column("locked", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    # Set locked=true for all existing integration sessions
    op.execute("UPDATE sessions SET locked = TRUE WHERE client_id LIKE 'slack:%'")

    # messages.metadata (JSONB message metadata: passive, sender_id, recipient_id, etc.)
    op.add_column(
        "messages",
        sa.Column("metadata", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )

    # integration_channel_configs — replaces slack_channel_configs with richer fields
    op.create_table(
        "integration_channel_configs",
        sa.Column("client_id", sa.Text(), primary_key=True),
        sa.Column("integration", sa.Text(), nullable=False, server_default=sa.text("'slack'")),
        sa.Column("require_mention", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("bot_id", sa.Text(), nullable=True),
        sa.Column("passive_memory", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("rag_on_all", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("metadata", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # Migrate existing slack_channel_configs data
    op.execute(
        """
        INSERT INTO integration_channel_configs
            (client_id, integration, bot_id, require_mention, passive_memory, rag_on_all, created_at, updated_at)
        SELECT
            'slack:' || channel_id,
            'slack',
            bot_id,
            TRUE,
            TRUE,
            FALSE,
            created_at,
            updated_at
        FROM slack_channel_configs
        ON CONFLICT DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_table("integration_channel_configs")
    op.drop_column("messages", "metadata")
    op.drop_column("sessions", "locked")
