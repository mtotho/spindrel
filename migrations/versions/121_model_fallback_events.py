"""Model fallback events table for circuit breaker visibility.

Revision ID: 121
Revises: 120
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, TIMESTAMP

revision = "121"
down_revision = "120"


def upgrade() -> None:
    op.create_table(
        "model_fallback_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("fallback_model", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("session_id", UUID(as_uuid=True), sa.ForeignKey("sessions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("channel_id", UUID(as_uuid=True), sa.ForeignKey("channels.id", ondelete="SET NULL"), nullable=True),
        sa.Column("bot_id", sa.Text(), nullable=True),
        sa.Column("cooldown_until", TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_model_fallback_events_model_created", "model_fallback_events", ["model", "created_at"])
    op.create_index("ix_model_fallback_events_created", "model_fallback_events", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_model_fallback_events_created", table_name="model_fallback_events")
    op.drop_index("ix_model_fallback_events_model_created", table_name="model_fallback_events")
    op.drop_table("model_fallback_events")
