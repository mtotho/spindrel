"""Add correlation_id and flush_result to compaction_logs

Revision ID: 123
Revises: 122
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "123"
down_revision = "122"


def upgrade() -> None:
    op.add_column("compaction_logs", sa.Column("correlation_id", UUID(as_uuid=True), nullable=True))
    op.add_column("compaction_logs", sa.Column("flush_result", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("compaction_logs", "flush_result")
    op.drop_column("compaction_logs", "correlation_id")
