"""Make trace_events.correlation_id nullable to support session-scoped events (e.g. compaction).

Revision ID: 022
Revises: 021
"""
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "022"
down_revision: Union[str, None] = "021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("trace_events", "correlation_id", nullable=True)


def downgrade() -> None:
    op.alter_column("trace_events", "correlation_id", nullable=False)
