"""Add Project intake convention columns.

Phase 4BD.1 of the Project Factory issue substrate plan. Records the user's
chosen issue-capture convention per Project so the generic intake skill can
read it once and write to the right place (a repo file, a repo folder, an
external tracker, or warn when unset).

Revision ID: 292_project_intake_config
Revises: 291_blueprint_orch_policy
Create Date: 2026-05-02
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "292_project_intake_config"
down_revision = "291_blueprint_orch_policy"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column(
            "intake_kind",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'unset'"),
        ),
    )
    op.add_column(
        "projects",
        sa.Column("intake_target", sa.Text(), nullable=True),
    )
    op.add_column(
        "projects",
        sa.Column(
            "intake_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("projects", "intake_metadata")
    op.drop_column("projects", "intake_target")
    op.drop_column("projects", "intake_kind")
