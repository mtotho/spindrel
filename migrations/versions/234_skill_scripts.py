"""Add skills.scripts for bot-authored named run_script snippets.

Revision ID: 234
Revises: 233
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "234"
down_revision = "233"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    if dialect == "postgresql":
        op.add_column(
            "skills",
            sa.Column(
                "scripts",
                sa.dialects.postgresql.JSONB,
                nullable=False,
                server_default=sa.text("'[]'::jsonb"),
            ),
        )
    else:
        with op.batch_alter_table("skills") as batch:
            batch.add_column(
                sa.Column(
                    "scripts",
                    sa.JSON(),
                    nullable=False,
                    server_default=sa.text("'[]'"),
                )
            )


def downgrade() -> None:
    with op.batch_alter_table("skills") as batch:
        batch.drop_column("scripts")
