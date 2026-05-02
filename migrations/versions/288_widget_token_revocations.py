"""Widget JWT revocation list — kill compromised widget tokens before
the 15-minute TTL expires.

Composite primary key (api_key_id, jti) — both come straight from the
JWT payload. ``expires_at`` mirrors the original token's ``exp`` so a
purge sweep can reclaim rows once the underlying token is dead anyway.

Revision ID: 288_widget_token_revocations
Revises: 287_clear_cross_workspace_access
Create Date: 2026-05-01
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "288_widget_token_revocations"
down_revision = "287_clear_cross_workspace_access"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "widget_token_revocations",
        sa.Column(
            "api_key_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("jti", sa.Text(), nullable=False),
        sa.Column(
            "revoked_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "expires_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("api_key_id", "jti"),
    )
    # Purge sweep filter is on expires_at — index drops the table scan.
    op.create_index(
        "ix_widget_token_revocations_expires_at",
        "widget_token_revocations",
        ["expires_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_widget_token_revocations_expires_at",
        table_name="widget_token_revocations",
    )
    op.drop_table("widget_token_revocations")
