"""heartbeat include pinned widgets toggle

Revision ID: 255_hb_include_pinned
Revises: 254_bot_harness_fields
Create Date: 2026-04-26 16:00:00.000000

Adds a per-heartbeat opt-in to inject the channel's pinned dashboard widget
context block into heartbeat runs. Defaults to false because heartbeats run
on a fixed schedule and the extra context is rarely needed; chat already has
its own ``channel.config["pinned_widget_context_enabled"]`` switch.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "255_hb_include_pinned"
down_revision = "254_bot_harness_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "channel_heartbeats",
        sa.Column(
            "include_pinned_widgets",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("channel_heartbeats", "include_pinned_widgets")
