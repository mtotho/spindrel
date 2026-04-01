"""Drop model elevation columns and table.

Model elevation is removed — smart model routing belongs in the
workflow system, not the inner tool loop.

Revision ID: 147b
Revises: 147
"""

import sqlalchemy as sa
from alembic import op

revision = "147b"
down_revision = "147"


def upgrade() -> None:
    # Drop columns from bots
    op.drop_column("bots", "elevation_enabled")
    op.drop_column("bots", "elevation_threshold")
    op.drop_column("bots", "elevated_model")

    # Drop columns from channels
    op.drop_column("channels", "elevation_enabled")
    op.drop_column("channels", "elevation_threshold")
    op.drop_column("channels", "elevated_model")

    # Drop model_elevation_log table (indexes are dropped automatically)
    op.drop_table("model_elevation_log")


def downgrade() -> None:
    from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID

    # Recreate model_elevation_log table
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
        sa.Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_elevation_log_bot_ts", "model_elevation_log", ["bot_id", sa.text("created_at DESC")])
    op.create_index("ix_elevation_log_turn", "model_elevation_log", ["turn_id"])
    op.create_index("ix_elevation_log_channel_ts", "model_elevation_log", ["channel_id", sa.text("created_at DESC")])

    # Recreate columns on channels
    op.add_column("channels", sa.Column("elevation_enabled", sa.Boolean(), nullable=True))
    op.add_column("channels", sa.Column("elevation_threshold", sa.Float(), nullable=True))
    op.add_column("channels", sa.Column("elevated_model", sa.Text(), nullable=True))

    # Recreate columns on bots
    op.add_column("bots", sa.Column("elevation_enabled", sa.Boolean(), nullable=True))
    op.add_column("bots", sa.Column("elevation_threshold", sa.Float(), nullable=True))
    op.add_column("bots", sa.Column("elevated_model", sa.Text(), nullable=True))
