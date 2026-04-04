"""Add docker_stacks table and docker_stacks_config to bots

Revision ID: 163
Revises: 162
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "163"
down_revision = "162"


def upgrade() -> None:
    op.create_table(
        "docker_stacks",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_by_bot", sa.Text(), nullable=False),
        sa.Column("channel_id", UUID(as_uuid=True), sa.ForeignKey("channels.id", ondelete="SET NULL"), nullable=True),
        sa.Column("compose_definition", sa.Text(), nullable=False),
        sa.Column("project_name", sa.Text(), unique=True, nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'stopped'")),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("network_name", sa.Text(), nullable=True),
        sa.Column("container_ids", JSONB, server_default=sa.text("'{}'::jsonb")),
        sa.Column("exposed_ports", JSONB, server_default=sa.text("'{}'::jsonb")),
        sa.Column("last_started_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("last_stopped_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_docker_stacks_created_by_bot", "docker_stacks", ["created_by_bot"])
    op.create_index("ix_docker_stacks_bot_channel", "docker_stacks", ["created_by_bot", "channel_id"])

    op.add_column("bots", sa.Column("docker_stacks_config", JSONB, server_default=sa.text("'{}'::jsonb")))


def downgrade() -> None:
    op.drop_column("bots", "docker_stacks_config")
    op.drop_table("docker_stacks")
