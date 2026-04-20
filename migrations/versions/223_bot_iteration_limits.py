"""Add per-bot iteration + script-budget overrides.

``bots.max_iterations`` per-bot override of ``settings.AGENT_MAX_ITERATIONS``
(channel-level override already exists on ``channels.max_iterations``, this
closes the override chain at channel → bot → global).

``bots.max_script_tool_calls`` caps how many tool calls a single ``run_script``
invocation may dispatch through ``/api/v1/internal/tools/exec``. Defends
against prompt-injected scripts looping around the loop's
``max_iterations`` fence — a single ``run_script`` counts as one iteration
but can otherwise trigger unbounded inner dispatches.

Both columns are nullable; NULL means "inherit global default". No backfill.

Revision ID: 223
Revises: 222
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "223"
down_revision = "222"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("bots", sa.Column("max_iterations", sa.Integer(), nullable=True))
    op.add_column(
        "bots",
        sa.Column("max_script_tool_calls", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("bots", "max_script_tool_calls")
    op.drop_column("bots", "max_iterations")
