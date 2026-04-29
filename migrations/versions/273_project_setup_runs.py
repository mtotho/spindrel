"""project setup runs

Revision ID: 273_project_setup_runs
Revises: 272_project_blueprints
Create Date: 2026-04-29
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "273_project_setup_runs"
down_revision = "272_project_blueprints"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "project_setup_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'pending'"), nullable=False),
        sa.Column("source", sa.Text(), server_default=sa.text("'blueprint_snapshot'"), nullable=False),
        sa.Column("plan", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("logs", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("started_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("completed_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_project_setup_runs_project_id", "project_setup_runs", ["project_id"])
    op.create_index("ix_project_setup_runs_project_created", "project_setup_runs", ["project_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_project_setup_runs_project_created", table_name="project_setup_runs")
    op.drop_index("ix_project_setup_runs_project_id", table_name="project_setup_runs")
    op.drop_table("project_setup_runs")
