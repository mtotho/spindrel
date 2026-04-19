"""Bot grants table (User Management Phase 5).

Junction table `(bot_id, user_id)` that lets a non-admin use a bot they
don't own. Mint/list endpoints authorize via owner OR grantee. Role is
stored but today only `'view'` is accepted; the column exists so adding
`'manage'` later needs no migration.

Revision ID: 221
Revises: 220
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PgUUID


revision = "221"
down_revision = "220"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "bot_grants",
        sa.Column(
            "bot_id", sa.Text(),
            sa.ForeignKey("bots.id", ondelete="CASCADE"),
            primary_key=True, nullable=False,
        ),
        sa.Column(
            "user_id", PgUUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True, nullable=False,
        ),
        sa.Column(
            "role", sa.Text(),
            server_default=sa.text("'view'"), nullable=False,
        ),
        sa.Column(
            "granted_by", PgUUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
    )
    op.create_index("ix_bot_grants_user_id", "bot_grants", ["user_id"])
    op.create_index("ix_bot_grants_bot_id", "bot_grants", ["bot_id"])


def downgrade() -> None:
    op.drop_index("ix_bot_grants_bot_id", table_name="bot_grants")
    op.drop_index("ix_bot_grants_user_id", table_name="bot_grants")
    op.drop_table("bot_grants")
