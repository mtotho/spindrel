"""Add source_task_id to sessions for delegation visibility.

Revision ID: 098
Revises: 097
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "098"
down_revision = "097"


def upgrade() -> None:
    conn = op.get_bind()
    result = conn.execute(sa.text(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name = 'sessions' AND column_name = 'source_task_id'"
    ))
    if not result.fetchone():
        op.add_column(
            "sessions",
            sa.Column("source_task_id", UUID(as_uuid=True), nullable=True),
        )
    # Create index only if it doesn't exist
    op.create_index(
        "ix_sessions_source_task_id", "sessions", ["source_task_id"],
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index("ix_sessions_source_task_id", table_name="sessions")
    op.drop_column("sessions", "source_task_id")
