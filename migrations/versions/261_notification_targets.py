"""notification targets

Revision ID: 261_notification_targets
Revises: 260_heartbeat_runner_mode
Create Date: 2026-04-27 00:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "261_notification_targets"
down_revision = "260_heartbeat_runner_mode"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notification_targets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("config", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("allowed_bot_ids", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("created_by", sa.Text(), nullable=True),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint("slug", name="uq_notification_targets_slug"),
    )
    op.create_index("ix_notification_targets_kind", "notification_targets", ["kind"])
    op.create_index("ix_notification_targets_enabled", "notification_targets", ["enabled"])

    op.create_table(
        "notification_deliveries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("target_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("root_target_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("sender_type", sa.Text(), nullable=False),
        sa.Column("sender_id", sa.Text(), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("body_preview", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("severity", sa.Text(), nullable=False, server_default=sa.text("'info'")),
        sa.Column("tag", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("succeeded", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("delivery_details", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["target_id"], ["notification_targets.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["root_target_id"], ["notification_targets.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_notification_deliveries_created_at", "notification_deliveries", ["created_at"])
    op.create_index("ix_notification_deliveries_target", "notification_deliveries", ["target_id"])
    op.create_index("ix_notification_deliveries_root_target", "notification_deliveries", ["root_target_id"])

    op.add_column(
        "usage_spike_config",
        sa.Column("target_ids", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
    )


def downgrade() -> None:
    op.drop_column("usage_spike_config", "target_ids")
    op.drop_index("ix_notification_deliveries_root_target", table_name="notification_deliveries")
    op.drop_index("ix_notification_deliveries_target", table_name="notification_deliveries")
    op.drop_index("ix_notification_deliveries_created_at", table_name="notification_deliveries")
    op.drop_table("notification_deliveries")
    op.drop_index("ix_notification_targets_enabled", table_name="notification_targets")
    op.drop_index("ix_notification_targets_kind", table_name="notification_targets")
    op.drop_table("notification_targets")
