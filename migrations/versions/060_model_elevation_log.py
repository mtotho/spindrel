"""Create model_elevation_log table.

Revision ID: 060
Revises: 059
Create Date: 2026-03-24
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "060"
down_revision = "059"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "model_elevation_log",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("turn_id", UUID(as_uuid=True), nullable=True),
        sa.Column("bot_id", sa.Text(), nullable=False),
        sa.Column("channel_id", UUID(as_uuid=True), sa.ForeignKey("channels.id", ondelete="SET NULL"), nullable=True),
        sa.Column("session_id", UUID(as_uuid=True), nullable=True),
        sa.Column("iteration", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("base_model", sa.Text(), nullable=False),
        sa.Column("model_chosen", sa.Text(), nullable=False),
        sa.Column("was_elevated", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("classifier_score", sa.Float(), nullable=False, server_default=sa.text("0")),
        sa.Column("elevation_reason", sa.Text(), nullable=True),
        sa.Column("rules_fired", JSONB(), server_default=sa.text("'[]'::jsonb")),
        sa.Column("signal_scores", JSONB(), server_default=sa.text("'{}'::jsonb")),
        sa.Column("tokens_used", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_elevation_log_bot_ts", "model_elevation_log", ["bot_id", sa.text("created_at DESC")])
    op.create_index("ix_elevation_log_turn", "model_elevation_log", ["turn_id"])
    op.create_index("ix_elevation_log_channel_ts", "model_elevation_log", ["channel_id", sa.text("created_at DESC")])


def downgrade() -> None:
    op.drop_index("ix_elevation_log_channel_ts", table_name="model_elevation_log")
    op.drop_index("ix_elevation_log_turn", table_name="model_elevation_log")
    op.drop_index("ix_elevation_log_bot_ts", table_name="model_elevation_log")
    op.drop_table("model_elevation_log")
