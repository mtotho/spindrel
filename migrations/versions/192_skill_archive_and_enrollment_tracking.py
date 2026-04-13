"""Add skill archiving and per-enrollment fetch tracking.

- skills.archived_at: nullable timestamp for soft-delete/archive
- bot_skill_enrollment.fetch_count: per-bot count of get_skill() calls
- bot_skill_enrollment.last_fetched_at: when this bot last fetched the skill

Revision ID: 192
Revises: 191
"""

import sqlalchemy as sa
from alembic import op

revision: str = "192"
down_revision: str = "191"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.add_column("skills", sa.Column("archived_at", sa.TIMESTAMP(timezone=True), nullable=True))
    op.add_column(
        "bot_skill_enrollment",
        sa.Column("fetch_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "bot_skill_enrollment",
        sa.Column("last_fetched_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("bot_skill_enrollment", "last_fetched_at")
    op.drop_column("bot_skill_enrollment", "fetch_count")
    op.drop_column("skills", "archived_at")
