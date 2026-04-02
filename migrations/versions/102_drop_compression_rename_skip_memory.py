"""Drop compression columns, rename compaction_skip_memory_phase to trigger_heartbeat_before_compaction.

Revision ID: 102
Revises: 101
Create Date: 2026-03-27
"""
from alembic import op
import sqlalchemy as sa

revision = "102"
down_revision = "101"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- Channels: drop compression columns ---
    op.drop_column("channels", "context_compression")
    op.drop_column("channels", "compression_model")
    op.drop_column("channels", "compression_threshold")
    op.drop_column("channels", "compression_keep_turns")
    op.drop_column("channels", "compression_prompt")

    # --- Channels: rename compaction_skip_memory_phase → trigger_heartbeat_before_compaction ---
    op.alter_column(
        "channels",
        "compaction_skip_memory_phase",
        new_column_name="trigger_heartbeat_before_compaction",
    )
    # Invert existing values: old skip=True → new trigger=False, old skip=False → new trigger=True
    op.execute(
        "UPDATE channels SET trigger_heartbeat_before_compaction = NOT trigger_heartbeat_before_compaction "
        "WHERE trigger_heartbeat_before_compaction IS NOT NULL"
    )

    # --- Bots: drop compression_config ---
    op.drop_column("bots", "compression_config")


def downgrade() -> None:
    # --- Bots: restore compression_config ---
    op.add_column(
        "bots",
        sa.Column("compression_config", sa.JSON(), server_default=sa.text("'{}'::jsonb"), nullable=True),
    )

    # --- Channels: rename back ---
    op.execute(
        "UPDATE channels SET trigger_heartbeat_before_compaction = NOT trigger_heartbeat_before_compaction "
        "WHERE trigger_heartbeat_before_compaction IS NOT NULL"
    )
    op.alter_column(
        "channels",
        "trigger_heartbeat_before_compaction",
        new_column_name="compaction_skip_memory_phase",
    )

    # --- Channels: restore compression columns ---
    op.add_column("channels", sa.Column("compression_prompt", sa.Text(), nullable=True))
    op.add_column("channels", sa.Column("compression_keep_turns", sa.Integer(), nullable=True))
    op.add_column("channels", sa.Column("compression_threshold", sa.Integer(), nullable=True))
    op.add_column("channels", sa.Column("compression_model", sa.Text(), nullable=True))
    op.add_column("channels", sa.Column("context_compression", sa.Boolean(), nullable=True))
