"""spatial bot presence and heartbeat prompt

Revision ID: 249_spatial_bot_presence
Revises: 248
Create Date: 2026-04-26 06:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "249_spatial_bot_presence"
down_revision = "248"
branch_labels = None
depends_on = None


_BOT_W = 260.0
_BOT_H = 180.0


def upgrade() -> None:
    op.add_column("bots", sa.Column("avatar_emoji", sa.Text(), nullable=True))
    op.add_column(
        "channel_heartbeats",
        sa.Column(
            "append_spatial_prompt",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    # Existing bot nodes were tiny 72x72 circles. Preserve their centers while
    # expanding the authored world bounds so far-zoom bot markers read as actors.
    op.execute(
        sa.text(
            """
            UPDATE workspace_spatial_nodes
            SET
              world_x = world_x + (world_w - :bot_w) / 2.0,
              world_y = world_y + (world_h - :bot_h) / 2.0,
              world_w = :bot_w,
              world_h = :bot_h
            WHERE bot_id IS NOT NULL
              AND (world_w < :bot_w OR world_h < :bot_h)
            """
        ).bindparams(bot_w=_BOT_W, bot_h=_BOT_H)
    )


def downgrade() -> None:
    op.drop_column("channel_heartbeats", "append_spatial_prompt")
    op.drop_column("bots", "avatar_emoji")
