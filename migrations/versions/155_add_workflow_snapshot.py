"""Add workflow_snapshot column to workflow_runs.

Revision ID: 155
Revises: 154
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "155"
down_revision = "154"


def upgrade() -> None:
    op.add_column("workflow_runs", sa.Column("workflow_snapshot", JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("workflow_runs", "workflow_snapshot")
