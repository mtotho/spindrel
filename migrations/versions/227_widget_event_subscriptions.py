"""Widget SDK Phase B.4 — event subscriptions for @on_event handlers.

One row per (pin, event_kind, handler) triple declared in a bundle's
``widget.yaml``. Unlike cron (B.3), which polls the DB every 5s, event
subscribers are push-based — a live ``asyncio.Task`` reads
``app.services.channel_events.subscribe(channel_id)`` and fires
``app.services.widget_py.invoke_event`` when a matching kind arrives.
Cascades on pin delete.

Revision ID: 227
Revises: 226
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision = "227"
down_revision = "226"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "widget_event_subscriptions",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "pin_id", UUID(as_uuid=True),
            sa.ForeignKey("widget_dashboard_pins.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_kind", sa.Text(), nullable=False),
        sa.Column("handler", sa.Text(), nullable=False),
        sa.Column(
            "enabled", sa.Boolean(), nullable=False,
            server_default=sa.text("TRUE"),
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
            "pin_id", "event_kind", "handler",
            name="uq_widget_event_subscriptions_pin_kind_handler",
        ),
    )
    op.create_index(
        "ix_widget_event_subscriptions_pin",
        "widget_event_subscriptions",
        ["pin_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_widget_event_subscriptions_pin",
        table_name="widget_event_subscriptions",
    )
    op.drop_table("widget_event_subscriptions")
