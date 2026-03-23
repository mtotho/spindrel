"""Add workspace JSONB to bots and workspace_rag to channels.

Data migration: converts existing bot_sandbox / host_exec_config / filesystem_indexes
into the unified workspace JSONB.

Revision ID: 055
Revises: 054
"""
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "055"
down_revision: Union[str, None] = "054"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "bots",
        sa.Column("workspace", JSONB(), server_default=sa.text("'{\"enabled\": false}'::jsonb"), nullable=False),
    )
    op.add_column(
        "channels",
        sa.Column("workspace_rag", sa.Boolean(), server_default=sa.text("true"), nullable=False),
    )

    # Data migration: convert existing configs to workspace format
    conn = op.get_bind()
    rows = conn.execute(
        sa.text(
            "SELECT id, bot_sandbox, host_exec_config, filesystem_indexes "
            "FROM bots"
        )
    ).fetchall()

    for row in rows:
        bot_id = row[0]
        bot_sandbox = row[1] or {}
        host_exec = row[2] or {}
        fs_indexes = row[3] or []

        workspace = {"enabled": False}

        # bot_sandbox takes priority
        if bot_sandbox.get("enabled"):
            workspace["enabled"] = True
            workspace["type"] = "docker"
            workspace["docker"] = {
                "image": bot_sandbox.get("image", "python:3.12-slim"),
                "network": bot_sandbox.get("network", "none"),
                "env": bot_sandbox.get("env", {}),
                "ports": bot_sandbox.get("ports", []),
                "mounts": bot_sandbox.get("mounts", []),
                "user": bot_sandbox.get("user", ""),
            }
        elif host_exec.get("enabled"):
            workspace["enabled"] = True
            workspace["type"] = "host"
            workspace["host"] = {
                "root": "",
                "commands": host_exec.get("commands", []),
                "blocked_patterns": host_exec.get("blocked_patterns", []),
                "env_passthrough": host_exec.get("env_passthrough", []),
            }
            if host_exec.get("timeout"):
                workspace["timeout"] = host_exec["timeout"]
            if host_exec.get("max_output_bytes"):
                workspace["max_output_bytes"] = host_exec["max_output_bytes"]

        # Merge filesystem_indexes into workspace indexing
        if fs_indexes:
            first = fs_indexes[0] if isinstance(fs_indexes, list) and fs_indexes else {}
            workspace["indexing"] = {
                "enabled": True,
                "patterns": first.get("patterns", ["**/*.py", "**/*.md", "**/*.yaml"]),
                "similarity_threshold": first.get("similarity_threshold"),
                "watch": first.get("watch", False),
                "cooldown_seconds": first.get("cooldown_seconds", 300),
            }

        import json
        conn.execute(
            sa.text("UPDATE bots SET workspace = :ws::jsonb WHERE id = :id"),
            {"ws": json.dumps(workspace), "id": bot_id},
        )


def downgrade() -> None:
    op.drop_column("channels", "workspace_rag")
    op.drop_column("bots", "workspace")
