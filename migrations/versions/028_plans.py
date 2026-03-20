"""Add plans and plan_items tables.

Revision ID: 028
Revises: 027
"""
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "028"
down_revision: Union[str, None] = "027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "plans",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("bot_id", sa.Text(), nullable=False),
        sa.Column("session_id", UUID(as_uuid=True), sa.ForeignKey("sessions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="active"),
    )
    op.create_index("ix_plans_session_id", "plans", ["session_id"])
    op.create_index("ix_plans_bot_id_status", "plans", ["bot_id", "status"])

    op.create_table(
        "plan_items",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("plan_id", UUID(as_uuid=True), sa.ForeignKey("plans.id", ondelete="CASCADE"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_plan_items_plan_id", "plan_items", ["plan_id"])


def downgrade() -> None:
    op.drop_index("ix_plan_items_plan_id", "plan_items")
    op.drop_table("plan_items")
    op.drop_index("ix_plans_bot_id_status", "plans")
    op.drop_index("ix_plans_session_id", "plans")
    op.drop_table("plans")
