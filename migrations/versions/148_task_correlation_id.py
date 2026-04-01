"""Add correlation_id to tasks table for cost attribution.

Revision ID: 148
Revises: 147b
"""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from alembic import op

revision = "148"
down_revision = "147b"


def upgrade() -> None:
    op.add_column(
        "tasks",
        sa.Column("correlation_id", UUID(as_uuid=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tasks", "correlation_id")
