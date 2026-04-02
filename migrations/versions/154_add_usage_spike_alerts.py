"""Add usage_spike_config and usage_spike_alerts tables.

Revision ID: 154
Revises: 153
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID

revision = "154"
down_revision = "153"


def upgrade() -> None:
    op.create_table(
        "usage_spike_config",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("window_minutes", sa.Integer(), nullable=False, server_default=sa.text("30")),
        sa.Column("baseline_hours", sa.Integer(), nullable=False, server_default=sa.text("24")),
        sa.Column("relative_threshold", sa.Float(), nullable=False, server_default=sa.text("2.0")),
        sa.Column("absolute_threshold_usd", sa.Float(), nullable=False, server_default=sa.text("0")),
        sa.Column("cooldown_minutes", sa.Integer(), nullable=False, server_default=sa.text("60")),
        sa.Column("targets", JSONB(), server_default=sa.text("'[]'::jsonb")),
        sa.Column("last_alert_at", TIMESTAMP(timezone=True), nullable=True),
        sa.Column("last_check_at", TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", TIMESTAMP(timezone=True), server_default=sa.text("now()")),
    )

    op.create_table(
        "usage_spike_alerts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("window_rate_usd_per_hour", sa.Float(), nullable=False),
        sa.Column("baseline_rate_usd_per_hour", sa.Float(), nullable=False),
        sa.Column("spike_ratio", sa.Float(), nullable=True),
        sa.Column("trigger_reason", sa.Text(), nullable=False),
        sa.Column("top_models", JSONB(), server_default=sa.text("'[]'::jsonb")),
        sa.Column("top_bots", JSONB(), server_default=sa.text("'[]'::jsonb")),
        sa.Column("recent_traces", JSONB(), server_default=sa.text("'[]'::jsonb")),
        sa.Column("targets_attempted", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("targets_succeeded", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("delivery_details", JSONB(), server_default=sa.text("'[]'::jsonb")),
        sa.Column("created_at", TIMESTAMP(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_usage_spike_alerts_created_at", "usage_spike_alerts", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_usage_spike_alerts_created_at", table_name="usage_spike_alerts")
    op.drop_table("usage_spike_alerts")
    op.drop_table("usage_spike_config")
