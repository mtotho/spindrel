"""Add bot_hooks table for bot-configurable lifecycle hooks.

Revision ID: 181
Revises: 180
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID

revision = "181"
down_revision = "180"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "bot_hooks",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("bot_id", sa.Text(), sa.ForeignKey("bots.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("trigger", sa.Text(), nullable=False),
        sa.Column("conditions", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("command", sa.Text(), nullable=False),
        sa.Column("cooldown_seconds", sa.Integer(), nullable=False, server_default=sa.text("60")),
        sa.Column("on_failure", sa.Text(), nullable=False, server_default=sa.text("'warn'")),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", TIMESTAMP(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_bot_hooks_bot_id", "bot_hooks", ["bot_id"])


def downgrade() -> None:
    op.drop_index("ix_bot_hooks_bot_id", table_name="bot_hooks")
    op.drop_table("bot_hooks")
