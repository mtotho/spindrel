"""project setup commands

Revision ID: 275_project_setup_commands
Revises: 274_merge_project_widget_heads
Create Date: 2026-04-29
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "275_project_setup_commands"
down_revision = "274_merge_project_widget_heads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "project_blueprints",
        sa.Column(
            "setup_commands",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("project_blueprints", "setup_commands")
