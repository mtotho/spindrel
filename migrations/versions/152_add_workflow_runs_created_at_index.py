"""Add created_at index to workflow_runs for efficient recent-runs queries.

Revision ID: 152
Revises: 151
"""
from alembic import op

revision = "152"
down_revision = "151"


def upgrade() -> None:
    op.create_index(
        "ix_workflow_runs_created_at",
        "workflow_runs",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_workflow_runs_created_at", table_name="workflow_runs")
