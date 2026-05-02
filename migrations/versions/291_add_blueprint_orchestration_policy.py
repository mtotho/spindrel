"""Add Symphony-equivalent orchestration policy fields to project_blueprints.

Phase 4BB.3 of the Project Factory cohesion pass. Three nullable columns -
NULL means "use the cohesion-plan defaults" (stall=1200s, turn=3600s,
unlimited concurrency) so existing blueprints keep working without backfill.

Revision ID: 291_add_blueprint_orchestration_policy
Revises: 290_add_tool_embedding_metadata
Create Date: 2026-05-02
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "291_add_blueprint_orchestration_policy"
down_revision = "290_add_tool_embedding_metadata"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "project_blueprints",
        sa.Column("stall_timeout_seconds", sa.Integer(), nullable=True),
    )
    op.add_column(
        "project_blueprints",
        sa.Column("turn_timeout_seconds", sa.Integer(), nullable=True),
    )
    op.add_column(
        "project_blueprints",
        sa.Column("max_concurrent_runs", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("project_blueprints", "max_concurrent_runs")
    op.drop_column("project_blueprints", "turn_timeout_seconds")
    op.drop_column("project_blueprints", "stall_timeout_seconds")
