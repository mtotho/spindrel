"""Add source_task_id to sessions for delegation visibility.

Revision ID: 090
Revises: 089
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "090"
down_revision = "089"


def upgrade() -> None:
    op.add_column(
        "sessions",
        sa.Column("source_task_id", UUID(as_uuid=True), nullable=True),
    )
    op.create_index("ix_sessions_source_task_id", "sessions", ["source_task_id"])


def downgrade() -> None:
    op.drop_index("ix_sessions_source_task_id", table_name="sessions")
    op.drop_column("sessions", "source_task_id")
