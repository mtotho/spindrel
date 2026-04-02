"""Bot system_prompt workspace file + channel prompt workspace file.

Revision ID: 117
Revises: 116
"""
from alembic import op
import sqlalchemy as sa

revision = "117"
down_revision = "116"


def upgrade() -> None:
    # Bot: system_prompt_workspace_file, system_prompt_write_protected
    op.add_column("bots", sa.Column("system_prompt_workspace_file", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("bots", sa.Column("system_prompt_write_protected", sa.Boolean(), nullable=False, server_default=sa.text("false")))

    # Channel: channel_prompt workspace file support
    op.add_column("channels", sa.Column("channel_prompt_workspace_file_path", sa.Text(), nullable=True))
    op.add_column("channels", sa.Column("channel_prompt_workspace_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "fk_channels_channel_prompt_workspace_id",
        "channels",
        "shared_workspaces",
        ["channel_prompt_workspace_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_channels_channel_prompt_workspace_id", "channels", type_="foreignkey")
    op.drop_column("channels", "channel_prompt_workspace_id")
    op.drop_column("channels", "channel_prompt_workspace_file_path")
    op.drop_column("bots", "system_prompt_write_protected")
    op.drop_column("bots", "system_prompt_workspace_file")
