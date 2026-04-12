"""Add bot_tool_enrollment table.

Persistent per-bot tool working set, mirroring bot_skill_enrollment.
Tools promoted on first successful call stay enrolled across turns/sessions.

Revision ID: 191
Revises: 190
"""

import sqlalchemy as sa
from alembic import op

revision: str = "191"
down_revision: str = "190"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.create_table(
        "bot_tool_enrollment",
        sa.Column("bot_id", sa.Text(), sa.ForeignKey("bots.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("tool_name", sa.Text(), primary_key=True),
        sa.Column("source", sa.Text(), nullable=False, server_default="manual"),
        sa.Column("enrolled_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )


def downgrade() -> None:
    op.drop_table("bot_tool_enrollment")
