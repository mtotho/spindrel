"""Add activation columns to channel_integrations.

Supports first-class integration activation on channels.
Data migration: channels with channel_workspace_enabled=true get a
mission_control ChannelIntegration row with activated=true.

Revision ID: 142
Revises: 141
"""

import sqlalchemy as sa
from alembic import op

revision = "142"
down_revision = "141"


def upgrade() -> None:
    op.add_column(
        "channel_integrations",
        sa.Column("activated", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "channel_integrations",
        sa.Column("activation_config", sa.JSON(), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )

    # Data migration: for channels with channel_workspace_enabled=true,
    # insert a mission_control ChannelIntegration row with activated=true
    # (skip if an MC row already exists for that channel).
    op.execute(sa.text("""
        INSERT INTO channel_integrations (id, channel_id, integration_type, client_id, activated, activation_config)
        SELECT
            gen_random_uuid(),
            c.id,
            'mission_control',
            'mc-activated:' || c.id::text,
            true,
            '{}'::jsonb
        FROM channels c
        WHERE c.channel_workspace_enabled = true
          AND NOT EXISTS (
            SELECT 1 FROM channel_integrations ci
            WHERE ci.channel_id = c.id
              AND ci.integration_type = 'mission_control'
          )
    """))


def downgrade() -> None:
    # Remove the MC activation rows we inserted
    op.execute(sa.text("""
        DELETE FROM channel_integrations
        WHERE integration_type = 'mission_control'
          AND client_id LIKE 'mc-activated:%'
    """))
    op.drop_column("channel_integrations", "activation_config")
    op.drop_column("channel_integrations", "activated")
