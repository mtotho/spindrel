"""Add prompt_template_id FK columns to heartbeats, channels, bots, tasks

Revision ID: 071
Revises: 070
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "071"
down_revision = "070"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "channel_heartbeats",
        sa.Column(
            "prompt_template_id",
            UUID(as_uuid=True),
            sa.ForeignKey("prompt_templates.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "channels",
        sa.Column(
            "compaction_prompt_template_id",
            UUID(as_uuid=True),
            sa.ForeignKey("prompt_templates.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "bots",
        sa.Column(
            "compaction_prompt_template_id",
            UUID(as_uuid=True),
            sa.ForeignKey("prompt_templates.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "tasks",
        sa.Column(
            "prompt_template_id",
            UUID(as_uuid=True),
            sa.ForeignKey("prompt_templates.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade():
    op.drop_column("tasks", "prompt_template_id")
    op.drop_column("bots", "compaction_prompt_template_id")
    op.drop_column("channels", "compaction_prompt_template_id")
    op.drop_column("channel_heartbeats", "prompt_template_id")
