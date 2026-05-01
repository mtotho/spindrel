"""dependency stack blueprint compatibility

Revision ID: 286_dep_stack_blueprint
Revises: 285_dependency_stack_compat
Create Date: 2026-04-30
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql


revision = "286_dep_stack_blueprint"
down_revision = "285_dependency_stack_compat"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {column["name"] for column in inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    if "dependency_stack" not in _columns("project_blueprints"):
        op.add_column(
            "project_blueprints",
            sa.Column(
                "dependency_stack",
                postgresql.JSONB(astext_type=sa.Text()),
                server_default=sa.text("'{}'::jsonb"),
                nullable=False,
            ),
        )


def downgrade() -> None:
    if "dependency_stack" in _columns("project_blueprints"):
        op.drop_column("project_blueprints", "dependency_stack")
