"""task machine grants

Revision ID: 281_task_machine_grants
Revises: 280_execution_receipts
Create Date: 2026-04-30
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "281_task_machine_grants"
down_revision = "280_execution_receipts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "task_machine_grants",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider_id", sa.Text(), nullable=False),
        sa.Column("target_id", sa.Text(), nullable=False),
        sa.Column("grant_id", sa.Text(), nullable=False),
        sa.Column("granted_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("capabilities", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("allow_agent_tools", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("expires_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("revoked_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["granted_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("grant_id", name="uq_task_machine_grants_grant_id"),
        sa.UniqueConstraint("task_id", name="uq_task_machine_grants_task"),
    )
    op.create_index("ix_task_machine_grants_target", "task_machine_grants", ["provider_id", "target_id"])
    op.create_index("ix_task_machine_grants_expires_at", "task_machine_grants", ["expires_at"])
    op.create_index("ix_task_machine_grants_granted_by_user_id", "task_machine_grants", ["granted_by_user_id"])


def downgrade() -> None:
    op.drop_index("ix_task_machine_grants_granted_by_user_id", table_name="task_machine_grants")
    op.drop_index("ix_task_machine_grants_expires_at", table_name="task_machine_grants")
    op.drop_index("ix_task_machine_grants_target", table_name="task_machine_grants")
    op.drop_table("task_machine_grants")
