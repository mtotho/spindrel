"""bot harness runtime fields

Revision ID: 254_bot_harness_fields
Revises: 253_spatial_map_view
Create Date: 2026-04-26 13:00:00.000000

Adds three nullable columns to ``bots`` so a bot can delegate its turn to
an external agent harness (Claude Code, Codex, ...) instead of running the
RAG loop. NULL ``harness_runtime`` means "regular Spindrel bot" — no behavior
change for any existing row.

See app/services/agent_harnesses/ and docs/guides/agent-harnesses.md.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "254_bot_harness_fields"
down_revision = "253_spatial_map_view"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "bots",
        sa.Column("harness_runtime", sa.Text(), nullable=True),
    )
    op.add_column(
        "bots",
        sa.Column("harness_workdir", sa.Text(), nullable=True),
    )
    op.add_column(
        "bots",
        sa.Column(
            "harness_session_state",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("bots", "harness_session_state")
    op.drop_column("bots", "harness_workdir")
    op.drop_column("bots", "harness_runtime")
