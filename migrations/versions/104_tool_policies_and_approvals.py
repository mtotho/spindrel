"""Add tool_policy_rules, tool_approvals tables and tool_calls indexes.

Revision ID: 104
Revises: 103
Create Date: 2026-03-27
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID, TIMESTAMP

revision = "104"
down_revision = "103"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # -- Phase 1: indexes on tool_calls for audit queries --
    op.create_index("ix_tool_calls_bot_id_created_at", "tool_calls", ["bot_id", "created_at"], if_not_exists=True)
    op.create_index("ix_tool_calls_tool_name_created_at", "tool_calls", ["tool_name", "created_at"], if_not_exists=True)

    # -- Phase 2: tool_policy_rules --
    op.create_table(
        "tool_policy_rules",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("bot_id", sa.Text(), nullable=True),
        sa.Column("tool_name", sa.Text(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),  # allow | deny | require_approval
        sa.Column("conditions", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False, server_default=sa.text("100")),
        sa.Column("approval_timeout", sa.Integer(), nullable=False, server_default=sa.text("300")),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_tool_policy_rules_bot_id", "tool_policy_rules", ["bot_id"])
    op.create_index("ix_tool_policy_rules_tool_name", "tool_policy_rules", ["tool_name"])

    # -- Phase 3: tool_approvals --
    op.create_table(
        "tool_approvals",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("session_id", UUID(as_uuid=True), nullable=True),
        sa.Column("channel_id", UUID(as_uuid=True), nullable=True),
        sa.Column("bot_id", sa.Text(), nullable=False),
        sa.Column("client_id", sa.Text(), nullable=True),
        sa.Column("correlation_id", UUID(as_uuid=True), nullable=True),
        sa.Column("tool_name", sa.Text(), nullable=False),
        sa.Column("tool_type", sa.Text(), nullable=False),
        sa.Column("arguments", JSONB, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("policy_rule_id", UUID(as_uuid=True), sa.ForeignKey("tool_policy_rules.id", ondelete="SET NULL"), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("decided_by", sa.Text(), nullable=True),
        sa.Column("decided_at", TIMESTAMP(timezone=True), nullable=True),
        sa.Column("dispatch_type", sa.Text(), nullable=True),
        sa.Column("dispatch_metadata", JSONB, nullable=True),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False, server_default=sa.text("300")),
        sa.Column("created_at", TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_tool_approvals_status", "tool_approvals", ["status"])
    op.create_index("ix_tool_approvals_bot_id", "tool_approvals", ["bot_id"])


def downgrade() -> None:
    op.drop_index("ix_tool_approvals_bot_id", table_name="tool_approvals")
    op.drop_index("ix_tool_approvals_status", table_name="tool_approvals")
    op.drop_table("tool_approvals")

    op.drop_index("ix_tool_policy_rules_tool_name", table_name="tool_policy_rules")
    op.drop_index("ix_tool_policy_rules_bot_id", table_name="tool_policy_rules")
    op.drop_table("tool_policy_rules")

    op.drop_index("ix_tool_calls_tool_name_created_at", table_name="tool_calls")
    op.drop_index("ix_tool_calls_bot_id_created_at", table_name="tool_calls")
