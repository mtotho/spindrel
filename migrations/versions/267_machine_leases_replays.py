"""machine target leases and webhook replay keys

Revision ID: 267_machine_leases_replays
Revises: 266_workspace_missions
Create Date: 2026-04-28
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "267_machine_leases_replays"
down_revision = "266_workspace_missions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "machine_target_leases",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider_id", sa.Text(), nullable=False),
        sa.Column("target_id", sa.Text(), nullable=False),
        sa.Column("lease_id", sa.Text(), nullable=False),
        sa.Column("granted_at", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("expires_at", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("capabilities", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("handle_id", sa.Text(), nullable=True),
        sa.Column("connection_id", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", name="uq_machine_target_leases_session"),
        sa.UniqueConstraint("provider_id", "target_id", name="uq_machine_target_leases_target"),
        sa.UniqueConstraint("lease_id", name="uq_machine_target_leases_lease_id"),
    )
    op.create_index("ix_machine_target_leases_expires_at", "machine_target_leases", ["expires_at"])
    op.create_index("ix_machine_target_leases_user_id", "machine_target_leases", ["user_id"])

    # Backfill active legacy metadata leases. If multiple sessions claim the
    # same target, keep the newest granted lease so the unique target invariant
    # is valid immediately after migration.
    op.execute(
        """
        INSERT INTO machine_target_leases (
            session_id, user_id, provider_id, target_id, lease_id, granted_at,
            expires_at, capabilities, handle_id, connection_id, metadata
        )
        SELECT DISTINCT ON (provider_id, target_id)
            session_id, user_id, provider_id, target_id, lease_id, granted_at,
            expires_at, capabilities, handle_id, connection_id, metadata
        FROM (
            SELECT
                s.id AS session_id,
                ((s.metadata -> 'machine_target_lease' ->> 'user_id')::uuid) AS user_id,
                COALESCE(NULLIF(s.metadata -> 'machine_target_lease' ->> 'provider_id', ''), 'local_companion') AS provider_id,
                s.metadata -> 'machine_target_lease' ->> 'target_id' AS target_id,
                s.metadata -> 'machine_target_lease' ->> 'lease_id' AS lease_id,
                ((s.metadata -> 'machine_target_lease' ->> 'granted_at')::timestamptz) AS granted_at,
                ((s.metadata -> 'machine_target_lease' ->> 'expires_at')::timestamptz) AS expires_at,
                COALESCE(s.metadata -> 'machine_target_lease' -> 'capabilities', '[]'::jsonb) AS capabilities,
                COALESCE(
                    s.metadata -> 'machine_target_lease' ->> 'handle_id',
                    s.metadata -> 'machine_target_lease' ->> 'connection_id'
                ) AS handle_id,
                s.metadata -> 'machine_target_lease' ->> 'connection_id' AS connection_id,
                s.metadata -> 'machine_target_lease' AS metadata
            FROM sessions s
            WHERE jsonb_typeof(s.metadata -> 'machine_target_lease') = 'object'
        ) legacy
        WHERE user_id IS NOT NULL
          AND target_id IS NOT NULL
          AND target_id <> ''
          AND lease_id IS NOT NULL
          AND lease_id <> ''
          AND granted_at IS NOT NULL
          AND expires_at > now()
        ORDER BY provider_id, target_id, granted_at DESC
        """
    )

    op.create_table(
        "inbound_webhook_replays",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("surface", sa.Text(), nullable=False),
        sa.Column("dedupe_key", sa.Text(), nullable=False),
        sa.Column("first_seen_at", postgresql.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("expires_at", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("surface", "dedupe_key", name="uq_inbound_webhook_replays_surface_key"),
    )
    op.create_index("ix_inbound_webhook_replays_expires_at", "inbound_webhook_replays", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_inbound_webhook_replays_expires_at", table_name="inbound_webhook_replays")
    op.drop_table("inbound_webhook_replays")
    op.drop_index("ix_machine_target_leases_user_id", table_name="machine_target_leases")
    op.drop_index("ix_machine_target_leases_expires_at", table_name="machine_target_leases")
    op.drop_table("machine_target_leases")
