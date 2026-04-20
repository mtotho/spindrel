"""Widget SDK Phase B.3 — cron subscriptions for @on_cron handlers.

One row per (pin, cron_name) pairing declared in a bundle's ``widget.yaml``.
The task scheduler sweeps this table every 5s (same loop as
``ChannelPipelineSubscription``) and fires
``app.services.widget_py.invoke_cron(pin, cron_name)`` under the pin's
``source_bot_id`` when ``next_fire_at <= now``. Cascades on pin delete.

Revision ID: 225
Revises: 224
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision = "225"
down_revision = "224"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "widget_cron_subscriptions",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "pin_id", UUID(as_uuid=True),
            sa.ForeignKey("widget_dashboard_pins.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("cron_name", sa.Text(), nullable=False),
        sa.Column("schedule", sa.Text(), nullable=False),
        sa.Column("handler", sa.Text(), nullable=False),
        sa.Column(
            "enabled", sa.Boolean(), nullable=False,
            server_default=sa.text("TRUE"),
        ),
        sa.Column(
            "next_fire_at", sa.TIMESTAMP(timezone=True), nullable=True,
        ),
        sa.Column(
            "last_fired_at", sa.TIMESTAMP(timezone=True), nullable=True,
        ),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.UniqueConstraint(
            "pin_id", "cron_name",
            name="uq_widget_cron_subscriptions_pin_name",
        ),
    )
    op.create_index(
        "ix_widget_cron_subscriptions_due",
        "widget_cron_subscriptions",
        ["next_fire_at"],
        postgresql_where=sa.text("enabled = TRUE AND next_fire_at IS NOT NULL"),
    )
    op.create_index(
        "ix_widget_cron_subscriptions_pin",
        "widget_cron_subscriptions",
        ["pin_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_widget_cron_subscriptions_pin",
        table_name="widget_cron_subscriptions",
    )
    op.drop_index(
        "ix_widget_cron_subscriptions_due",
        table_name="widget_cron_subscriptions",
    )
    op.drop_table("widget_cron_subscriptions")
