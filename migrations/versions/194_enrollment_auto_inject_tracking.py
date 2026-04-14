"""Add auto-inject tracking to bot_skill_enrollment.

- auto_inject_count: per-bot count of system-initiated auto-injections
- last_auto_injected_at: when this skill was last auto-injected for this bot

Tracked separately from fetch_count/last_fetched_at (bot-initiated get_skill)
so hygiene and evaluation can distinguish the two.

Revision ID: 194
Revises: 193
"""

import sqlalchemy as sa
from alembic import op

revision: str = "194"
down_revision: str = "193"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.add_column(
        "bot_skill_enrollment",
        sa.Column("auto_inject_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "bot_skill_enrollment",
        sa.Column("last_auto_injected_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("bot_skill_enrollment", "last_auto_injected_at")
    op.drop_column("bot_skill_enrollment", "auto_inject_count")
