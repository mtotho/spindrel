"""DB-backed bots, skills, and Slack channel config.

Revision ID: 015
Revises: 014
Create Date: 2026-03-20

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "015"
down_revision: Union[str, None] = "014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "bots",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("system_prompt", sa.Text(), nullable=False, server_default=""),
        sa.Column("local_tools", JSONB(), nullable=False, server_default="[]"),
        sa.Column("mcp_servers", JSONB(), nullable=False, server_default="[]"),
        sa.Column("client_tools", JSONB(), nullable=False, server_default="[]"),
        sa.Column("pinned_tools", JSONB(), nullable=False, server_default="[]"),
        sa.Column("skills", JSONB(), nullable=False, server_default="[]"),
        sa.Column("docker_sandbox_profiles", JSONB(), nullable=False, server_default="[]"),
        sa.Column("tool_retrieval", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("tool_similarity_threshold", sa.Float(), nullable=True),
        sa.Column("persona", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("context_compaction", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("compaction_interval", sa.Integer(), nullable=True),
        sa.Column("compaction_keep_turns", sa.Integer(), nullable=True),
        sa.Column("compaction_model", sa.Text(), nullable=True),
        sa.Column("memory_knowledge_compaction_prompt", sa.Text(), nullable=True),
        sa.Column("audio_input", sa.Text(), nullable=False, server_default="transcribe"),
        sa.Column("memory_config", JSONB(), nullable=False, server_default="{}"),
        sa.Column("knowledge_config", JSONB(), nullable=False, server_default="{}"),
        sa.Column("filesystem_indexes", JSONB(), nullable=False, server_default="[]"),
        sa.Column("slack_display_name", sa.Text(), nullable=True),
        sa.Column("slack_icon_emoji", sa.Text(), nullable=True),
        sa.Column("slack_icon_url", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "skills",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("content_hash", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "slack_channel_configs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("channel_id", sa.Text(), nullable=False, unique=True),
        sa.Column("bot_id", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_slack_channel_configs_channel_id", "slack_channel_configs", ["channel_id"])


def downgrade() -> None:
    op.drop_table("slack_channel_configs")
    op.drop_table("skills")
    op.drop_table("bots")
