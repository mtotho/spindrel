"""project dependency stack compatibility

Revision ID: 285_dependency_stack_compat
Revises: 284_project_runtime_stacks
Create Date: 2026-04-30
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql


revision = "285_dependency_stack_compat"
down_revision = "284_project_runtime_stacks"
branch_labels = None
depends_on = None


def _table_names() -> set[str]:
    return set(inspect(op.get_bind()).get_table_names())


def _column_names(table: str) -> set[str]:
    return {column["name"] for column in inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    tables = _table_names()
    if "project_dependency_stack_instances" not in tables and "project_runtime_stack_instances" in tables:
        op.rename_table("project_runtime_stack_instances", "project_dependency_stack_instances")

    if "project_dependency_stack_instances" not in _table_names():
        return

    columns = _column_names("project_dependency_stack_instances")
    if "env" not in columns:
        op.add_column(
            "project_dependency_stack_instances",
            sa.Column("env", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        )
    for column in ("app_service", "app_url", "health_path"):
        if column in _column_names("project_dependency_stack_instances"):
            op.drop_column("project_dependency_stack_instances", column)


def downgrade() -> None:
    tables = _table_names()
    if "project_dependency_stack_instances" in tables and "project_runtime_stack_instances" not in tables:
        op.rename_table("project_dependency_stack_instances", "project_runtime_stack_instances")
    if "project_runtime_stack_instances" not in _table_names():
        return
    columns = _column_names("project_runtime_stack_instances")
    if "app_service" not in columns:
        op.add_column("project_runtime_stack_instances", sa.Column("app_service", sa.Text(), nullable=True))
    if "app_url" not in columns:
        op.add_column("project_runtime_stack_instances", sa.Column("app_url", sa.Text(), nullable=True))
    if "health_path" not in columns:
        op.add_column("project_runtime_stack_instances", sa.Column("health_path", sa.Text(), nullable=True))
    if "env" in _column_names("project_runtime_stack_instances"):
        op.drop_column("project_runtime_stack_instances", "env")
