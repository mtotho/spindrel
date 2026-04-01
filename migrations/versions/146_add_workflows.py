"""Add workflows and workflow_runs tables.

Core workflow system for reusable, parameterized workflow templates
with conditionals, approval gates, and scoped secrets.

Revision ID: 146
Revises: 145
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from alembic import op

revision = "146"
down_revision = "145"


def upgrade() -> None:
    op.create_table(
        "workflows",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("params", JSONB, server_default=sa.text("'{}'::jsonb")),
        sa.Column("secrets", JSONB, server_default=sa.text("'[]'::jsonb")),
        sa.Column("defaults", JSONB, server_default=sa.text("'{}'::jsonb")),
        sa.Column("steps", JSONB, server_default=sa.text("'[]'::jsonb")),
        sa.Column("triggers", JSONB, server_default=sa.text("'{}'::jsonb")),
        sa.Column("tags", JSONB, server_default=sa.text("'[]'::jsonb")),
        sa.Column("source_type", sa.Text(), nullable=False, server_default=sa.text("'manual'")),
        sa.Column("source_path", sa.Text(), nullable=True),
        sa.Column("content_hash", sa.Text(), nullable=True),
        sa.Column("created_at", TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", TIMESTAMP(timezone=True), server_default=sa.text("now()")),
    )

    op.create_table(
        "workflow_runs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("workflow_id", sa.Text(), sa.ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False),
        sa.Column("bot_id", sa.Text(), nullable=False),
        sa.Column("channel_id", UUID(as_uuid=True), sa.ForeignKey("channels.id", ondelete="SET NULL"), nullable=True),
        sa.Column("session_id", UUID(as_uuid=True), nullable=True),
        sa.Column("params", JSONB, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'running'")),
        sa.Column("current_step_index", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("step_states", JSONB, server_default=sa.text("'[]'::jsonb")),
        sa.Column("dispatch_type", sa.Text(), nullable=False, server_default=sa.text("'none'")),
        sa.Column("dispatch_config", JSONB, nullable=True),
        sa.Column("triggered_by", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", TIMESTAMP(timezone=True), server_default=sa.text("now()")),
        sa.Column("completed_at", TIMESTAMP(timezone=True), nullable=True),
    )

    op.create_index("ix_workflow_runs_status", "workflow_runs", ["status"])
    op.create_index("ix_workflow_runs_workflow_id", "workflow_runs", ["workflow_id"])


def downgrade() -> None:
    op.drop_index("ix_workflow_runs_workflow_id", table_name="workflow_runs")
    op.drop_index("ix_workflow_runs_status", table_name="workflow_runs")
    op.drop_table("workflow_runs")
    op.drop_table("workflows")
