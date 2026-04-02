"""Add workspace_file_path and workspace_id columns for direct workspace file prompts.

Adds to tasks, channel_heartbeats, and channels (compaction variant).

Revision ID: 093
Revises: 092
"""
import sqlalchemy as sa
from alembic import op

revision = "093"
down_revision = "092"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Tasks
    op.add_column("tasks", sa.Column("workspace_file_path", sa.Text(), nullable=True))
    op.add_column("tasks", sa.Column(
        "workspace_id", sa.UUID(),
        sa.ForeignKey("shared_workspaces.id", ondelete="SET NULL"),
        nullable=True,
    ))

    # Channel heartbeats
    op.add_column("channel_heartbeats", sa.Column("workspace_file_path", sa.Text(), nullable=True))
    op.add_column("channel_heartbeats", sa.Column(
        "workspace_id", sa.UUID(),
        sa.ForeignKey("shared_workspaces.id", ondelete="SET NULL"),
        nullable=True,
    ))

    # Channels (compaction prompt from workspace file)
    op.add_column("channels", sa.Column("compaction_workspace_file_path", sa.Text(), nullable=True))
    op.add_column("channels", sa.Column(
        "compaction_workspace_id", sa.UUID(),
        sa.ForeignKey("shared_workspaces.id", ondelete="SET NULL"),
        nullable=True,
    ))


def downgrade() -> None:
    op.drop_column("channels", "compaction_workspace_id")
    op.drop_column("channels", "compaction_workspace_file_path")
    op.drop_column("channel_heartbeats", "workspace_id")
    op.drop_column("channel_heartbeats", "workspace_file_path")
    op.drop_column("tasks", "workspace_id")
    op.drop_column("tasks", "workspace_file_path")
