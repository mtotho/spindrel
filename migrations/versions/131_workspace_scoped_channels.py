"""Add workspace_id FK to channels and workspace_only flag to bots.

Channels get a direct FK to shared_workspaces so we can filter by workspace
at the DB level. Existing channels are backfilled from shared_workspace_bots.

Bots get a workspace_only flag so workspace-specific bots can be hidden
from the global channel list.

Revision ID: 131
Revises: 130
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "131"
down_revision = "130"


def upgrade() -> None:
    # -- channels.workspace_id FK --
    op.add_column(
        "channels",
        sa.Column(
            "workspace_id",
            UUID(as_uuid=True),
            sa.ForeignKey("shared_workspaces.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_channels_workspace_id", "channels", ["workspace_id"])

    # Backfill from shared_workspace_bots
    op.execute(
        """
        UPDATE channels
        SET workspace_id = swb.workspace_id
        FROM shared_workspace_bots swb
        WHERE channels.bot_id = swb.bot_id
          AND channels.workspace_id IS NULL
        """
    )

    # -- bots.workspace_only --
    op.add_column(
        "bots",
        sa.Column(
            "workspace_only",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("bots", "workspace_only")
    op.drop_index("ix_channels_workspace_id", table_name="channels")
    op.drop_column("channels", "workspace_id")
