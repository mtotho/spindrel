"""Docker sandbox tables.

Revision ID: 014
Revises: 013
Create Date: 2026-03-20

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "014"
down_revision: Union[str, None] = "013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sandbox_profiles",
        sa.Column("id", sa.UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.Text(), unique=True, nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("image", sa.Text(), nullable=False),
        sa.Column("scope_mode", sa.Text(), nullable=False, server_default="session"),
        sa.Column("network_mode", sa.Text(), nullable=False, server_default="none"),
        sa.Column("read_only_root", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("create_options", JSONB(), nullable=False, server_default="{}"),
        sa.Column("mount_specs", JSONB(), nullable=False, server_default="[]"),
        sa.Column("env", JSONB(), nullable=False, server_default="{}"),
        sa.Column("labels", JSONB(), nullable=False, server_default="{}"),
        sa.Column("idle_ttl_seconds", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "sandbox_bot_access",
        sa.Column("bot_id", sa.Text(), nullable=False),
        sa.Column("profile_id", sa.UUID(), nullable=False),
        sa.PrimaryKeyConstraint("bot_id", "profile_id"),
        sa.ForeignKeyConstraint(["profile_id"], ["sandbox_profiles.id"], ondelete="CASCADE"),
    )

    op.create_table(
        "sandbox_instances",
        sa.Column("id", sa.UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("profile_id", sa.UUID(), nullable=False),
        sa.Column("scope_type", sa.Text(), nullable=False),
        sa.Column("scope_key", sa.Text(), nullable=False),
        sa.Column("container_id", sa.Text(), nullable=True),
        sa.Column("container_name", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="unknown"),
        sa.Column("created_by_bot", sa.Text(), nullable=False),
        sa.Column("locked_operations", JSONB(), nullable=False, server_default="[]"),
        sa.Column("last_inspected_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["profile_id"], ["sandbox_profiles.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("profile_id", "scope_type", "scope_key", name="uq_sandbox_instance_scope"),
    )
    op.create_index("idx_sandbox_instance_status", "sandbox_instances", ["status"])
    op.create_index("idx_sandbox_instance_last_used", "sandbox_instances", ["last_used_at"])

    # Seed: one example session-scoped profile for testing
    op.execute("""
        INSERT INTO sandbox_profiles (name, description, image, scope_mode, network_mode,
            read_only_root, create_options, mount_specs, env, labels)
        VALUES (
            'python-scratch',
            'Ephemeral Python 3.12 scratch environment. Session-scoped, no network access.',
            'python:3.12-slim',
            'session',
            'none',
            false,
            '{"cpus": "1.0", "memory": "512m"}',
            '[]',
            '{}',
            '{"agent-server": "true"}'
        )
    """)


def downgrade() -> None:
    op.drop_table("sandbox_instances")
    op.drop_table("sandbox_bot_access")
    op.drop_table("sandbox_profiles")
