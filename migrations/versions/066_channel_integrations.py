"""Add channel_integrations table for multi-integration bindings.

Revision ID: 066
Revises: 065
Create Date: 2026-03-24
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID

revision = "066"
down_revision = "065"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "channel_integrations",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("channel_id", UUID(as_uuid=True), sa.ForeignKey("channels.id", ondelete="CASCADE"), nullable=False),
        sa.Column("integration_type", sa.Text, nullable=False),
        sa.Column("client_id", sa.Text, nullable=False, unique=True),
        sa.Column("dispatch_config", JSONB, nullable=True),
        sa.Column("display_name", sa.Text, nullable=True),
        sa.Column("metadata", JSONB, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", TIMESTAMP(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_channel_integrations_channel_id", "channel_integrations", ["channel_id"])

    # Seed from existing channels that have integration bindings
    op.execute("""
        INSERT INTO channel_integrations (channel_id, integration_type, client_id, dispatch_config)
        SELECT id, integration, client_id, dispatch_config
        FROM channels
        WHERE integration IS NOT NULL AND client_id IS NOT NULL
    """)


def downgrade():
    op.drop_index("ix_channel_integrations_channel_id")
    op.drop_table("channel_integrations")
