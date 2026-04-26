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
    # Idempotent: a previous attempt of this migration with an over-long
    # revision id added the column but failed to record the version bump
    # (StringDataRightTruncation on alembic_version.version_num). Re-running
    # would otherwise fail with "column already exists".
    op.execute(
        "ALTER TABLE channel_heartbeats "
        "ADD COLUMN IF NOT EXISTS include_pinned_widgets BOOLEAN "
        "NOT NULL DEFAULT FALSE"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE channel_heartbeats DROP COLUMN IF EXISTS include_pinned_widgets"
    )
